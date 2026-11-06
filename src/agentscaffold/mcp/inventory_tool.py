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
from pathlib import Path
from typing import Any

MODES = ("check", "review", "component")

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


def _component(report: Any, component_id: str) -> dict[str, Any]:
    by_id = {c.id: c for c in report.inventory.components if c.id}
    entry = by_id.get(component_id)
    if entry is None:
        return {
            "found": False,
            "component_id": component_id,
            "suggestions": difflib.get_close_matches(component_id, list(by_id), n=5, cutoff=0.4),
        }
    effective = {
        name: {"value": getattr(entry, name), "from": getattr(entry, source)}
        for name, source in _PROVENANCE.items()
    }
    return {
        "found": True,
        "component_id": component_id,
        **{name: getattr(entry, name) for name in _FIELDS},
        "effective": effective,
        "findings": [f.to_dict() for f in report.findings if f.component == component_id],
    }


def inventory_tool(
    arguments: dict[str, Any],
    root: Path,
    config: Any,
    *,
    store: Any = None,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Answer one ``scaffold_inventory`` call; never writes."""
    from agentscaffold.inventory.project import check_project  # noqa: PLC0415
    from agentscaffold.inventory.schema import InventoryError  # noqa: PLC0415

    inv_cfg = getattr(config, "inventory", None)
    if inv_cfg is None or not inv_cfg.enabled:
        return {
            "enabled": False,
            "reason": "inventory.enabled is false; run `scaffold inventory enable`",
        }
    mode = str(arguments.get("mode") or "check").strip().lower()
    if mode not in MODES:
        return {"error": f"mode must be one of {', '.join(MODES)}, got {mode!r}"}
    today = today or dt.date.today()
    try:
        if mode == "review":
            from agentscaffold.inventory.review import build_packet  # noqa: PLC0415

            return {
                "enabled": True,
                "view": mode,
                **build_packet(root, config, today=today, store=store),
            }
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
    return {"enabled": True, "view": mode, **_component(report, component_id)}


__all__ = ["MODES", "inventory_tool"]
