"""The architecture review packet (``scaffold inventory review``, ``scaffold_inventory``).

One packet gathers what a periodic review needs: lifecycle debt, health
status, duplicate and unreferenced-entrypoint candidates, components whose
owner or layer is unresolved (with the cheapest fix for each), derivation
coverage and the check summary. Candidates are advisory and labelled
``unconfirmed``; nothing here proves a component is dead.
"""

from __future__ import annotations

import datetime as dt
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from agentscaffold.inventory import checks, health
from agentscaffold.inventory import paths as inv_paths
from agentscaffold.inventory.collectors import CollectionResult
from agentscaffold.inventory.derived_file import PROVENANCE
from agentscaffold.inventory.project import check_project, inventory_path, run_collectors
from agentscaffold.inventory.schema import Component, Inventory

#: ``lifecycle_debt`` keys that are status, not debt.
_STATUS_KEYS = frozenset({"health_snapshot", "error"})
_ITEM_CAP = 25


def duplicates(inventory: Inventory, collected: CollectionResult) -> list[dict[str, Any]]:
    """Scheduled jobs sharing an entrypoint with different parameters; services sharing
    image and command. Same entrypoint and parameters is INV-006, not a candidate."""
    found = collected.by_id()
    jobs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    services: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in inventory.components:
        if not entry.id:
            continue
        hit = found.get(entry.id)
        entrypoint = (hit.entrypoint if hit and hit.entrypoint else entry.entrypoint) or ""
        if entry.kind == "scheduled_job" and entrypoint:
            jobs[entrypoint].append((entry.id, hit.parameters_key() if hit else "{}"))
        image = (hit.image if hit and hit.image else entry.image) or ""
        if entry.kind == "service" and image and entrypoint:
            services[(image, entrypoint)].append(entry.id)
    out: list[dict[str, Any]] = []
    for entrypoint, rows in jobs.items():
        if len(rows) > 1 and len({params for _id, params in rows}) > 1:
            out.append(
                {
                    "components": [cid for cid, _ in rows],
                    "reason": f"scheduled jobs share entrypoint {entrypoint} with different "
                    "parameters",
                    "confidence": "unconfirmed",
                }
            )
    for (image, command), ids in services.items():
        if len(ids) > 1:
            out.append(
                {
                    "components": ids,
                    "reason": f"services share image {image} and command {command}",
                    "confidence": "unconfirmed",
                }
            )
    return out


def unreferenced(root: Path, inventory: Inventory) -> list[dict[str, Any]]:
    """Components whose entrypoint file is not in the project (it may be built elsewhere)."""
    out: list[dict[str, Any]] = []
    for entry in inventory.components:
        file_part = inv_paths.entrypoint_path(entry.entrypoint)
        if not entry.id or not file_part or entry.lifecycle == "deprecated":
            continue
        disk = inv_paths.resolve(root, file_part)
        if disk is not None and not disk.exists():
            out.append(
                {
                    "component": entry.id,
                    "entrypoint": file_part,
                    "reason": "entrypoint file not found in the project",
                    "confidence": "unconfirmed",
                }
            )
    return out


def cheapest_fix(entry: Component, missing: list[str]) -> str:
    """The one-line change that resolves *missing* for *entry*."""
    prefix = (entry.id or "").split(":", 1)[0]
    source = entry.source or "its source"
    if prefix == "compose":
        labels = ", ".join(f"agentscaffold.{f}: <{f}>" for f in missing)
        return f"labels {{{labels}}} on service {entry.name} in {source}"
    if prefix == "prefect":
        tags = ", ".join(
            {"owner_plan": "plan:<n>", "layer": "layer:<id>"}.get(f, f"{f}:<id>") for f in missing
        )
        return f"tags [{tags}] on deployment {entry.name} in {source}"
    if prefix == "github_workflows":
        pairs = " ".join(f"{f}=<{f}>" for f in missing)
        return f"a line `# agentscaffold: {pairs}` in {source}"
    return f"pin {', '.join(missing)} on {entry.id} in the inventory"


def unresolved(inventory: Inventory) -> list[dict[str, Any]]:
    """INV-011 components with what is missing and the cheapest fix."""
    out: list[dict[str, Any]] = []
    for entry in inventory.components:
        missing = [f for f in ("owner_plan", "layer") if not getattr(entry, f)]
        if entry.id and missing:
            out.append(
                {
                    "component": entry.id,
                    "missing": missing,
                    "touched_by": list(entry.touched_by),
                    "fix": cheapest_fix(entry, missing),
                }
            )
    return out


def coverage(inventory: Inventory) -> dict[str, dict[str, int]]:
    """Per derived field: resolved count, total, and count by ``*_from`` tag."""
    ids = [c for c in inventory.components if c.id]
    out: dict[str, dict[str, int]] = {}
    for name, from_key in PROVENANCE.items():
        counts: dict[str, int] = {}
        for comp in ids:
            if getattr(comp, name):
                tag = getattr(comp, from_key) or "unknown"
                counts[tag] = counts.get(tag, 0) + 1
        out[name] = {"resolved": sum(counts.values()), "total": len(ids), **counts}
    return out


def has_debt(packet: dict[str, Any]) -> bool:
    """Debt or errors: what ``--exit-code`` and the scheduled issue act on."""
    debt = packet.get("lifecycle_debt") or {}
    if any(key not in _STATUS_KEYS for key in debt) or "error" in debt:
        return True
    return bool(packet["unresolved"]) or packet["check"]["errors"] > 0


def build_packet(root: Path, config: Any, *, today: dt.date, store: Any = None) -> dict[str, Any]:
    """The review packet. Raises InventoryError when the inventory cannot be read."""
    from agentscaffold.mcp.session_brief import lifecycle_debt  # noqa: PLC0415

    root = Path(root)
    inv_cfg = config.inventory
    report = check_project(root, config, today=today)
    inventory = report.inventory
    collected = run_collectors(root, config)
    snapshot = health.read_snapshot(
        root / inv_cfg.health_snapshot,
        today=today,
        max_bytes=inv_cfg.health_max_bytes,
        stale_days=inv_cfg.failing_days,
    )
    summary = checks.summary(inventory, report.findings)
    by_kind: dict[str, int] = defaultdict(int)
    for comp in inventory.components:
        by_kind[comp.kind or "unknown"] += 1
    packet: dict[str, Any] = {
        "today": today.isoformat(),
        "inventory": os.path.relpath(inventory_path(root, config), root),
        "components": len(inventory.components),
        "by_kind": dict(sorted(by_kind.items())),
        "last_architecture_review": inventory.last_architecture_review,
        "review_cadence_days": inventory.review_cadence_days,
        "review_due": checks.review_due(inventory, today),
        "current_roadmap_stage": inventory.current_roadmap_stage,
        "lifecycle_debt": lifecycle_debt(store, root, config, today=today) or {},
        "health": {"status": snapshot.status, "reason": snapshot.reason},
        "duplicates": duplicates(inventory, collected),
        "unreferenced": unreferenced(root, inventory),
        "unresolved": unresolved(inventory),
        "coverage": coverage(inventory),
        "check": {
            "mode": report.mode,
            "errors": summary["errors"],
            "warnings": summary["warnings"],
            "error_findings": [f.to_dict() for f in report.findings if f.severity == "error"][
                :_ITEM_CAP
            ],
        },
        "notices": [n for n in report.notices if n.get("kind") != "broad_reads"],
    }
    packet["has_debt"] = has_debt(packet)
    return packet


def _items(lines: list[str], items: list[str], empty: str = "None.") -> None:
    if not items:
        lines.append(empty)
    else:
        lines.extend(f"- {item}" for item in items[:_ITEM_CAP])
        if len(items) > _ITEM_CAP:
            lines.append(f"- ... and {len(items) - _ITEM_CAP} more")
    lines.append("")


def render_markdown(packet: dict[str, Any]) -> str:
    """The packet as the CLI prints it and the scheduled issue holds it."""
    lines = [f"# System inventory review, {packet['today']}", ""]
    kinds = ", ".join(f"{n} {k}" for k, n in packet["by_kind"].items()) or "none"
    lines += [
        f"{packet['components']} components ({kinds}) in `{packet['inventory']}`.",
        f"Check: {packet['check']['errors']} errors, {packet['check']['warnings']} warnings "
        f"(mode {packet['check']['mode']}).",
        f"Last architecture review: {packet['last_architecture_review'] or 'not recorded'}"
        + (" (due)" if packet["review_due"] else "")
        + f"; cadence {packet['review_cadence_days']} days.",
        f"Current roadmap stage: {packet['current_roadmap_stage'] or 'unknown'}.",
        "",
        "## Lifecycle debt",
        "",
    ]
    debt = packet["lifecycle_debt"]
    entries: list[str] = []
    for key, value in debt.items():
        if key in _STATUS_KEYS:
            continue
        if isinstance(value, dict):
            shown = ", ".join(value.get("items", []))
            entries.append(f"{key.replace('_', ' ')} ({value.get('count', 0)}): {shown}")
        else:
            entries.append(f"{key.replace('_', ' ')}: {value}")
    if "error" in debt:
        entries.append(str(debt["error"]))
    _items(lines, entries)

    status = packet["health"]["status"]
    label = {"not_evaluated": "not evaluated"}.get(status, status)
    lines += ["## Health", "", f"Status: {label}. {packet['health']['reason']}".rstrip(), ""]

    lines += ["## Unresolved owner or layer (INV-011)", ""]
    _items(
        lines,
        [
            f"{u['component']}: {' and '.join(u['missing'])}; fix: {u['fix']}"
            for u in packet["unresolved"]
        ],
    )
    lines += ["## Duplicate candidates (unconfirmed)", ""]
    _items(lines, [f"{', '.join(d['components'])}: {d['reason']}" for d in packet["duplicates"]])
    lines += ["## Unreferenced entrypoints (unconfirmed)", ""]
    _items(
        lines, [f"{u['component']}: {u['entrypoint']} not found" for u in packet["unreferenced"]]
    )

    lines += ["## Derivation coverage", ""]
    rows = []
    for name, counts in packet["coverage"].items():
        rules = ", ".join(f"{k} {v}" for k, v in counts.items() if k not in ("resolved", "total"))
        rows.append(
            f"{name}: {counts['resolved']}/{counts['total']}" + (f" ({rules})" if rules else "")
        )
    _items(lines, rows)

    if packet["check"]["error_findings"]:
        lines += ["## Check errors", ""]
        _items(
            lines,
            [
                f"{f['id']} {f['component'] or '(inventory)'}: {f['message']}"
                for f in packet["check"]["error_findings"]
            ],
        )
    if packet["notices"]:
        lines += ["## Notices", ""]
        _items(lines, [n["message"] for n in packet["notices"]])
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "build_packet",
    "cheapest_fix",
    "coverage",
    "duplicates",
    "has_debt",
    "render_markdown",
    "unreferenced",
    "unresolved",
]
