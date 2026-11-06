"""The ``scaffold_inventory`` tool: read-only views of the system inventory.

``check`` is ``scaffold inventory check --format json``; ``review`` is the
architecture review packet; ``component`` is one component's effective values,
each with where it came from (a pin, or the derivation rule). The response
names the requested mode ``view``, because the check JSON's ``mode`` is the
enforcement mode (``warn`` or ``fail``).
"""

from __future__ import annotations

import datetime as dt
import difflib
from collections.abc import Callable
from pathlib import Path
from typing import Any

MODES = ("check", "review", "component")
ENABLE_HINT = "The inventory is off; run `scaffold inventory enable` to turn it on."

#: Items per packet list under ``detail=summary``; ``counts`` keeps the totals.
SUMMARY_CAP = 10
_PACKET_LISTS = ("duplicates", "unreferenced", "unresolved")

#: Effective field -> the field naming its source.
_PROVENANCE = {
    "owner_plan": "owner_from",
    "layer": "layer_from",
    "roadmap_stage": "roadmap_stage_from",
}
_FIELDS = (
    "kind",
    "name",
    "source",
    "entrypoint",
    "image",
    "lifecycle",
    "since",
    "reason",
    "review_by",
    "exit_criteria",
    "replaced_by",
    "reads",
    "touched_by",
)

GovernanceLookup = Callable[[str], dict[str, Any] | None]


def _component(
    report: Any, component_id: str, root: Path, governance: GovernanceLookup | None
) -> dict[str, Any]:
    from agentscaffold.inventory import paths as inv_paths  # noqa: PLC0415

    by_id = {c.id: c for c in report.inventory.components if c.id}
    entry = by_id.get(component_id)
    if entry is None:
        return {
            "found": False,
            "component_id": component_id,
            "suggestions": difflib.get_close_matches(component_id, list(by_id), n=5, cutoff=0.4),
        }
    out: dict[str, Any] = {
        "found": True,
        "component": component_id,
        **{name: getattr(entry, name) for name in _FIELDS},
        "fields": {
            name: {"value": getattr(entry, name), "from": getattr(entry, source)}
            for name, source in _PROVENANCE.items()
        },
        "findings": [f.to_dict() for f in report.findings if f.component == component_id],
    }
    target = inv_paths.entrypoint_path(entry.entrypoint)
    graph_target = inv_paths.graph_path(root, target) if target else None
    if governance is not None and graph_target:
        out["governance"] = governance(graph_target) or {}
    return out


def _review(root: Path, config: Any, today: dt.date, store: Any, detail: str) -> dict[str, Any]:
    from agentscaffold.inventory.review import build_packet, render_markdown  # noqa: PLC0415

    packet = build_packet(root, config, today=today, store=store)
    markdown = render_markdown(packet)
    if detail != "full":
        counts = {key: len(packet[key]) for key in _PACKET_LISTS}
        packet = {
            **packet,
            **{key: packet[key][:SUMMARY_CAP] for key in _PACKET_LISTS},
            "counts": counts,
        }
    return {**packet, "markdown": markdown}


def inventory_tool(
    arguments: dict[str, Any],
    root: Path,
    config: Any,
    *,
    store: Any = None,
    today: dt.date | None = None,
    governance: GovernanceLookup | None = None,
) -> dict[str, Any]:
    """Answer one ``scaffold_inventory`` call; never writes.

    *governance* maps a graph file path to its governance facts (findings,
    learnings, ADRs, contracts); component mode applies it to the entrypoint.
    """
    from agentscaffold.inventory.project import check_project  # noqa: PLC0415
    from agentscaffold.inventory.schema import InventoryError  # noqa: PLC0415

    inv_cfg = getattr(config, "inventory", None)
    if inv_cfg is None or not inv_cfg.enabled:
        return {"enabled": False, "hint": ENABLE_HINT}
    mode = str(arguments.get("mode") or "check").strip().lower()
    if mode not in MODES:
        return {"error": f"mode must be one of {', '.join(MODES)}, got {mode!r}"}
    detail = str(arguments.get("detail") or "summary").strip().lower()
    today = today or dt.date.today()
    try:
        if mode == "review":
            return {"enabled": True, "view": mode, **_review(root, config, today, store, detail)}
        report = check_project(root, config, today=today)
    except InventoryError as exc:
        return {
            "enabled": True,
            "view": mode,
            "error": str(exc),
            "remediation": "run `scaffold inventory check` locally; `scaffold inventory init` "
            "writes a first inventory",
        }
    if mode == "check":
        return {"enabled": True, "view": mode, **report.to_dict()}
    component_id = str(arguments.get("component_id") or "").strip()
    if not component_id:
        return {"error": "mode 'component' needs component_id (for example 'compose:api')"}
    return {
        "enabled": True,
        "view": mode,
        **_component(report, component_id, Path(root), governance),
    }


__all__ = ["ENABLE_HINT", "MODES", "SUMMARY_CAP", "inventory_tool"]
