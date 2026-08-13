"""BacklogItem write-back logic.

Provides ``record_backlog_item()`` and ``resolve_backlog_item()`` that persist
BacklogItem nodes in the DuckPGQ knowledge graph.

BacklogItem IDs are content hashes ``bi::`` + SHA1 of
``{project?}backlog::{plan_number}::{title[:64]}``, not the human IDs in
``backlog.md``. ``resolve_backlog_item`` accepts the hash, a Plan 225
project-qualified form, or a unique human-id / title prefix.

The markdown files (backlog.md, backlog_archive.md, plan appendices) remain the
human-readable record -- graph writes are strictly additive.

Performance target: <200ms per write.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

_VALID_STATUSES = frozenset({"open", "blocked", "unblockable", "archived"})
_VALID_PRIORITIES = frozenset({"P1", "P2", "P3", "P4", "P5"})


def _sync_governance(store: GraphBackend) -> None:
    """Re-serialize governance to the git-backed artifact if write-through is on."""
    from agentscaffold.graph.governance_store import sync_if_enabled  # noqa: PLC0415

    sync_if_enabled(store)


def _backlog_id(plan_number: int, title: str, project: str | None = None) -> str:
    """Derive a deterministic, project-scoped ID from plan number + title.

    Plan numbers are NOT unique across projects in a multi-project workspace, so
    the project is folded into the hash key to prevent cross-project backlog-ID
    collisions. A falsy *project* reproduces the original (unscoped) ID for
    single-project back-compat.
    """
    prefix = f"{project}::" if project else ""
    key = f"{prefix}backlog::{plan_number}::{title[:64]}"
    return "bi::" + hashlib.sha1(key.encode()).hexdigest()[:12]  # noqa: S324


def record_backlog_item(
    store: GraphBackend,
    *,
    plan_number: int,
    title: str,
    priority: str = "P3",
    effort: str = "",
    source: str = "",
    status: str = "open",
    project: str | None = None,
) -> dict[str, Any]:
    """Record a backlog item in the knowledge graph.

    Creates a BacklogItem node and links it to the plan via a BACKLOG_ITEM_OF
    edge. Silently ignores duplicates (same plan_number + title).

    Args:
        store: Open GraphBackend instance.
        plan_number: The plan this item relates to (e.g. 133).
        title: Short description matching the title in backlog.md.
        priority: P1-P5 priority matching the backlog.md convention.
        effort: Effort estimate string (e.g. "Small (2h)").
        source: Review source reference (e.g. "DA Future Regret", "EX-8").
        status: Initial status -- "open", "blocked", or "unblockable".
        project: Owning project in a multi-project workspace; stamps the
            ``project`` column and scopes the deterministic ID and Plan lookup.
            None (single-project) keeps the original unscoped behavior.

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()
    item_id = _backlog_id(plan_number, title, project)
    now = datetime.now(timezone.utc).isoformat()
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""

    props: dict[str, Any] = {
        "id": item_id,
        "planNumber": plan_number,
        "title": title,
        "priority": priority,
        "effort": effort,
        "status": status,
        "source": source,
        "createdAt": now,
        "archivedAt": "",
        "resolution": "",
        "project": project or "",
    }

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.create_node("BacklogItem", props)

        # Link to plan (scoped to the owning project: plan numbers are not unique
        # across projects in a multi-project workspace).
        plan_rows = store.query(f"SELECT id FROM Plan WHERE number = {plan_number}{proj_filter}")
        if plan_rows:
            store.create_edge("BACKLOG_ITEM_OF", "BacklogItem", item_id, "Plan", plan_rows[0]["id"])

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "id": item_id,
        "plan_number": plan_number,
        "title": title,
        "priority": priority,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "created_at": now,
    }


def record_backlog_items_batch(
    store: GraphBackend,
    *,
    plan_number: int,
    items: list[dict[str, Any]],
    project: str | None = None,
) -> dict[str, Any]:
    """Record multiple BacklogItem nodes in a single transaction.

    Each item in ``items`` must have a ``title`` key. Optional keys per item:
    ``priority``, ``effort``, ``source``, ``status``.

    Args:
        store: Open GraphBackend instance.
        plan_number: Plan number all items relate to.
        items: List of backlog item dicts.
        project: Owning project in a multi-project workspace; stamps the
            ``project`` column and scopes the deterministic IDs and Plan lookup.

    Returns:
        Dict with ``ids``, ``count``, and timing info.
    """
    t0 = time.monotonic()
    if not items:
        return {"ids": [], "count": 0, "elapsed_ms": 0.0}

    now = datetime.now(timezone.utc).isoformat()
    ids: list[str] = []
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""

    plan_rows = store.query(f"SELECT id FROM Plan WHERE number = {plan_number}{proj_filter}")
    plan_id = plan_rows[0]["id"] if plan_rows else None

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.execute("BEGIN TRANSACTION")
        try:
            for item in items:
                title = item.get("title", "")
                if not title:
                    continue
                item_id = _backlog_id(plan_number, title, project)
                props: dict[str, Any] = {
                    "id": item_id,
                    "planNumber": plan_number,
                    "title": title,
                    "priority": item.get("priority", "P3"),
                    "effort": item.get("effort", ""),
                    "status": item.get("status", "open"),
                    "source": item.get("source", ""),
                    "createdAt": now,
                    "archivedAt": "",
                    "resolution": "",
                    "project": project or "",
                }
                store.create_node("BacklogItem", props)
                if plan_id:
                    store.create_edge("BACKLOG_ITEM_OF", "BacklogItem", item_id, "Plan", plan_id)
                ids.append(item_id)

            store.execute("COMMIT")
        except Exception:
            store.execute("ROLLBACK")
            raise

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "ids": ids,
        "count": len(ids),
        "plan_number": plan_number,
        "elapsed_ms": elapsed_ms,
        "created_at": now,
    }


def _returning_id(rows: list[dict[str, Any]]) -> str | None:
    """Id from UPDATE ... RETURNING, or None.

    DuckDB UPDATE without RETURNING yields ``[{Count: 0}]`` -- a non-empty list.
    Only a row with an ``id`` key counts as a hit.
    """
    for row in rows:
        rid = row.get("id")
        if rid:
            return str(rid)
    return None


def _id_candidates(raw_id: str, project: str | None) -> list[str]:
    """Exact-id forms to try: as given, plus Plan 225 qualified/unqualified."""
    raw_id = raw_id.strip()
    if not raw_id:
        return []
    out = [raw_id]
    if not project:
        return out
    from agentscaffold.graph.scoping import qualify_id, unqualify_id  # noqa: PLC0415

    prefix = f"{project}::"
    if not raw_id.startswith(prefix):
        qualified = qualify_id(project, raw_id)
        if qualified not in out:
            out.append(qualified)
    _head, rest = unqualify_id(raw_id, known_projects={project})
    if rest and rest not in out:
        out.append(rest)
    return out


def _lookup_backlog_canonical(
    store: GraphBackend,
    item_id: str,
    project: str | None,
) -> dict[str, Any]:
    """Resolve caller input to a stored BacklogItem id, or a miss/ambiguous dict.

    Returns ``{"status": "ok", "id": canonical}`` on a unique match.
    """
    candidates = _id_candidates(item_id, project)
    if not candidates:
        return {"status": "not_found"}

    placeholders = ", ".join(["?"] * len(candidates))
    params: dict[str, Any] = {f"id{i}": v for i, v in enumerate(candidates)}
    sql = f"SELECT id, title FROM BacklogItem WHERE id IN ({placeholders})"
    if project:
        sql += " AND project = ?"
        params["project"] = project
    exact = store.query(sql, params)
    exact_ids = list(dict.fromkeys(str(r["id"]) for r in exact if r.get("id")))
    if len(exact_ids) == 1:
        return {"status": "ok", "id": exact_ids[0]}
    if len(exact_ids) > 1:
        return {
            "status": "ambiguous",
            "candidates": [{"id": r["id"], "title": r.get("title", "")} for r in exact],
        }

    title_params: dict[str, Any] = {"title": item_id, "colon": f"{item_id}:"}
    title_sql = "SELECT id, title FROM BacklogItem WHERE (title = ? OR starts_with(title, ?)"
    if "-" in item_id:
        title_sql += " OR starts_with(title, ?)"
        title_params["space"] = f"{item_id} "
    title_sql += ")"
    if project:
        title_sql += " AND project = ?"
        title_params["project"] = project
    titles = store.query(title_sql, title_params)
    title_ids = list(dict.fromkeys(str(r["id"]) for r in titles if r.get("id")))
    if len(title_ids) == 1:
        return {"status": "ok", "id": title_ids[0]}
    if len(title_ids) > 1:
        return {
            "status": "ambiguous",
            "candidates": [{"id": r["id"], "title": r.get("title", "")} for r in titles],
        }
    return {"status": "not_found"}


def resolve_backlog_item(
    store: GraphBackend,
    item_id: str,
    *,
    resolution: str = "",
    project: str | None = None,
) -> dict[str, Any]:
    """Mark a BacklogItem as archived (completed).

    Sets status to 'archived' and records the archived timestamp and optional
    resolution note. The item remains in the graph for retrospective queries.

    ``item_id`` may be the canonical ``bi::`` hash (or its project-qualified
    form), or a unique human id / title prefix (``DQ-043``, ``B-249-1``).

    A miss returns ``status="not_found"`` and does not fabricate success. Two
    or more title matches return ``status="ambiguous"``.

    Args:
        store: Open GraphBackend instance.
        item_id: The ID of the backlog item to archive.
        resolution: Optional note describing how the item was completed.
        project: When set, only archives the item if it belongs to this
            project (defense-in-depth against cross-project resolves).

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()
    now = datetime.now(timezone.utc).isoformat()
    caller_id = (item_id or "").strip()

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        looked = _lookup_backlog_canonical(store, caller_id, project)
        if looked["status"] != "ok":
            elapsed_ms = (time.monotonic() - t0) * 1000
            payload: dict[str, Any] = {
                "id": caller_id,
                "status": looked["status"],
                "elapsed_ms": elapsed_ms,
            }
            if looked["status"] == "ambiguous":
                payload["candidates"] = looked.get("candidates", [])
            return payload

        canonical_id = looked["id"]
        params: dict[str, Any] = {
            "archivedAt": now,
            "resolution": resolution,
            "id": canonical_id,
        }
        sql = (
            "UPDATE BacklogItem SET status = 'archived', archivedAt = ?, resolution = ?"
            " WHERE id = ?"
        )
        if project:
            sql += " AND project = ?"
            params["project"] = project
        sql += " RETURNING id"
        rows = store.query(sql, params)
        matched = _returning_id(rows)
        if matched is None:
            elapsed_ms = (time.monotonic() - t0) * 1000
            return {"id": caller_id, "status": "not_found", "elapsed_ms": elapsed_ms}

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "id": matched,
        "status": "archived",
        "resolution": resolution,
        "archived_at": now,
        "elapsed_ms": elapsed_ms,
    }


def get_open_backlog_items(
    store: GraphBackend,
    *,
    plan_number: int | None = None,
    limit: int = 20,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Return open (non-archived) BacklogItems, optionally filtered by plan.

    Results are sorted by priority (P1 first).

    Args:
        store: Open GraphBackend instance.
        plan_number: If provided, filter to items for this plan only.
        limit: Maximum number of items to return.
        project: When set, only return items stamped with this project
            (multi-project scoping). None returns items regardless of project.

    Returns:
        List of backlog item dicts.
    """
    from agentscaffold.graph.query_compat import ql  # noqa: PLC0415

    plan_filter = f" AND planNumber = {plan_number}" if plan_number is not None else ""
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""
    rows = ql(
        store,
        sql=(
            f'SELECT id AS "bi.id", planNumber AS "bi.planNumber",'
            f' title AS "bi.title", priority AS "bi.priority",'
            f' effort AS "bi.effort", status AS "bi.status", source AS "bi.source"'
            f" FROM BacklogItem"
            f" WHERE status NOT IN ('archived', 'unblockable'){plan_filter}{proj_filter}"
            f" ORDER BY priority"
            f" LIMIT {limit}"
        ),
    )
    return rows


def get_backlog_items_for_plan(
    store: GraphBackend,
    plan_number: int,
    *,
    include_archived: bool = False,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Return all BacklogItems for a specific plan.

    Args:
        store: Open GraphBackend instance.
        plan_number: Plan number to filter by.
        include_archived: If True, include archived items.
        project: When set, only return items stamped with this project
            (multi-project scoping). None returns items regardless of project.

    Returns:
        List of backlog item dicts ordered by priority.
    """
    from agentscaffold.graph.query_compat import ql  # noqa: PLC0415

    status_filter = "" if include_archived else " AND status != 'archived'"
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""
    rows = ql(
        store,
        sql=(
            f'SELECT id AS "bi.id", planNumber AS "bi.planNumber",'
            f' title AS "bi.title", priority AS "bi.priority",'
            f' effort AS "bi.effort", status AS "bi.status", source AS "bi.source"'
            f" FROM BacklogItem"
            f" WHERE planNumber = {plan_number}{status_filter}{proj_filter}"
            f" ORDER BY priority"
        ),
    )
    return rows


def delete_backlog_item(store: GraphBackend, item_id: str) -> None:
    """Delete a BacklogItem and its BACKLOG_ITEM_OF edges.

    Used by selective pruning. Removes the item's edges first (src = id), then
    the node itself.
    """
    iid = _esc(item_id)
    try:
        store.execute(f"DELETE FROM BACKLOG_ITEM_OF WHERE src = '{iid}'")
    except Exception:  # noqa: BLE001 - edge table may be absent
        pass
    store.execute(f"DELETE FROM BacklogItem WHERE id = '{iid}'")


def _esc(s: str) -> str:
    """Minimal SQL string escaping (single-quote doubling)."""
    return s.replace("'", "''")
