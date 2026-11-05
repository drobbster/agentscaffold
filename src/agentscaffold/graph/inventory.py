"""System inventory in the graph.

``process_inventory`` writes one ``Component`` node per inventory entry, with
``OWNED_BY`` to the owning Plan, ``ENTRYPOINT`` to the entrypoint's File, and
``READS`` to every indexed File a ``reads`` entry covers. Components are
derived: each run replaces the project's rows, and they are never exported.

The read helpers match paths in Python against the stored inventory paths, so a
directory target (``configs/``) finds the components that read under it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agentscaffold.inventory import paths as inv_paths
from agentscaffold.inventory.schema import Component, InventoryError

logger = logging.getLogger(__name__)

COMPONENT_PREFIX = "component::"

#: Graph column for each inventory field.
_COLUMNS: dict[str, str] = {
    "kind": "kind",
    "name": "name",
    "source": "source",
    "entrypoint": "entrypoint",
    "layer": "layer",
    "owner_plan": "ownerPlan",
    "roadmap_stage": "roadmapStage",
    "lifecycle": "lifecycle",
    "since": "since",
    "reason": "reason",
    "review_by": "reviewBy",
    "exit_criteria": "exitCriteria",
    "replaced_by": "replacedBy",
}


def _scoped(sql: str, project: str | None) -> tuple[str, dict[str, Any]]:
    if project is None:
        return sql, {}
    joiner = " AND " if " WHERE " in sql else " WHERE "
    return f"{sql}{joiner}project = ?", {"project": project}


def _plan_ids(store: Any, project: str | None) -> dict[int, str]:
    sql, params = _scoped("SELECT id, number FROM Plan", project)
    ids: dict[int, str] = {}
    for row in store.query(sql, params or None):
        number = row.get("number")
        if number is not None and int(number) not in ids:
            ids[int(number)] = str(row["id"])
    return ids


def _file_ids(store: Any, project: str | None) -> dict[str, str]:
    sql, params = _scoped("SELECT id, path FROM File", project)
    return {str(r["path"]): str(r["id"]) for r in store.query(sql, params or None) if r["path"]}


def _owner_number(value: str | None) -> int | None:
    try:
        return int(str(value)) if value else None
    except ValueError:
        return None


def _node(entry: Component) -> dict[str, Any]:
    props: dict[str, Any] = {
        "id": f"{COMPONENT_PREFIX}{entry.id}",
        "componentId": entry.id,
        "reads": json.dumps(list(entry.reads)),
    }
    for field_name, column in _COLUMNS.items():
        props[column] = getattr(entry, field_name)
    return props


def process_inventory(store: Any, root: Path, config: Any) -> dict[str, Any]:
    """Replace this project's Component nodes from the inventory file.

    A disabled or unreadable inventory leaves no Component rows; the error is
    logged (``scaffold inventory check`` reports it) and indexing continues.
    """
    project = getattr(store, "write_project", None)
    store.clear_table("Component", project=project)
    inv_cfg = getattr(config, "inventory", None)
    if inv_cfg is None or not inv_cfg.enabled:
        return {"enabled": False, "components": 0}
    from agentscaffold.inventory.project import load_project_inventory  # noqa: PLC0415

    try:
        inventory = load_project_inventory(Path(root), config)
    except InventoryError as exc:
        logger.warning("Inventory not indexed: %s", exc)
        return {"enabled": True, "components": 0, "error": str(exc)}

    plans = _plan_ids(store, project)
    files = _file_ids(store, project)
    seen: set[str] = set()
    counts = {"components": 0, "owned_by": 0, "entrypoint": 0, "reads": 0}
    for entry in inventory.components:
        if not entry.id or entry.id in seen:
            continue
        seen.add(entry.id)
        node = _node(entry)
        store.create_node("Component", node)
        counts["components"] += 1

        owner = _owner_number(entry.owner_plan)
        if owner is not None and owner in plans:
            store.create_edge("OWNED_BY", "Component", node["id"], "Plan", plans[owner])
            counts["owned_by"] += 1

        file_part = inv_paths.entrypoint_path(entry.entrypoint)
        target = inv_paths.graph_path(Path(root), file_part) if file_part else None
        if target and target in files:
            store.create_edge("ENTRYPOINT", "Component", node["id"], "File", files[target])
            counts["entrypoint"] += 1

        read_targets = [
            t for t in (inv_paths.graph_path(Path(root), r) for r in entry.reads) if t is not None
        ]
        for path, file_id in files.items():
            if any(inv_paths.covers(t, path) for t in read_targets):
                store.create_edge("READS", "Component", node["id"], "File", file_id)
                counts["reads"] += 1
    return {"enabled": True, **counts}


# ---------------------------------------------------------------------------
# Reads (MCP impact/context, review, verify)
# ---------------------------------------------------------------------------


def _rows(store: Any, scope: tuple[str, dict[str, Any]]) -> list[dict[str, Any]]:
    fragment, params = scope
    sql = "SELECT * FROM Component"
    if fragment:
        sql += f" WHERE {fragment}"
    try:
        return list(store.query(sql + " ORDER BY componentId", params or None))
    except Exception as exc:  # noqa: BLE001 - an older graph has no Component table
        logger.debug("Component query failed: %s", exc)
        return []


def _summary(row: dict[str, Any], touched: list[str]) -> dict[str, Any]:
    return {
        "component": row.get("componentId"),
        "kind": row.get("kind") or None,
        "lifecycle": row.get("lifecycle") or None,
        "owner_plan": row.get("ownerPlan") or None,
        "review_by": row.get("reviewBy") or None,
        "touched": touched,
    }


def _declared_paths(row: dict[str, Any], root: Path) -> list[tuple[str, str]]:
    """``(graph path, via)`` for a component row's reads and entrypoint."""
    out: list[tuple[str, str]] = []
    try:
        reads = json.loads(row.get("reads") or "[]")
    except ValueError:
        reads = []
    for read in reads if isinstance(reads, list) else []:
        target = inv_paths.graph_path(root, str(read))
        if target is not None:
            out.append((target, "reads"))
    file_part = inv_paths.entrypoint_path(row.get("entrypoint") or None)
    if file_part:
        target = inv_paths.graph_path(root, file_part)
        if target is not None:
            out.append((target, "entrypoint"))
    return out


def components_for_paths(
    store: Any,
    paths: list[str],
    *,
    root: Path,
    scope: tuple[str, dict[str, Any]] = ("", {}),
) -> list[dict[str, Any]]:
    """Components whose ``reads`` or entrypoint the graph *paths* touch.

    A path ending in ``/`` is a directory and touches every component that
    reads at or below it.
    """
    wanted = [p for p in (inv_paths.graph_path(root, p) for p in paths) if p is not None]
    if not wanted:
        return []
    out: list[dict[str, Any]] = []
    for row in _rows(store, scope):
        declared = _declared_paths(row, root)
        touched = sorted({p for p in wanted for t, _via in declared if inv_paths.touches(t, p)})
        if touched:
            via = sorted({v for t, v in declared for p in touched if inv_paths.touches(t, p)})
            out.append({**_summary(row, touched), "via": via})
    return out


def components_owned_by(
    store: Any,
    plan_number: int,
    *,
    scope: tuple[str, dict[str, Any]] = ("", {}),
) -> list[dict[str, Any]]:
    """Components whose ``owner_plan`` is *plan_number*."""
    return [
        _summary(row, [])
        for row in _rows(store, scope)
        if _owner_number(row.get("ownerPlan")) == int(plan_number)
    ]
