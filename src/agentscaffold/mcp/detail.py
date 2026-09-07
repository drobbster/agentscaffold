"""Detail mode helpers for MCP token control (Plan 246/247)."""

from __future__ import annotations

from typing import Any

_SUMMARY_LIST_CAPS: dict[str, int] = {
    "challenges": 5,
    "gaps": 5,
    "open_findings": 5,
    "open_backlog_items": 5,
    "governing_adrs": 5,
    "recent_plans": 5,
    "hot_files": 5,
    "recent_studies": 3,
    "active_adrs": 5,
    "impacted_files": 8,
    "recommended_actions": 3,
    "symbol_spot_checks": 5,
}

_SUMMARY_DROP_KEYS = frozenset(
    {
        "recent_plans",
        "hot_files",
        "recent_studies",
        "active_adrs",
        "stats",
    }
)

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_SUMMARY_WORKFLOW_CHARS = 2000
_FULL_WORKFLOW_CHARS = 8000
_WORKFLOW_PROSE_KEYS = ("blockers", "next_steps", "current_implementation")


def apply_detail(payload: dict[str, Any], detail: str | None) -> dict[str, Any]:
    """Trim list-heavy fields when ``detail=summary`` (default).

    Plan 247: challenges/gaps/open_findings are severity-sorted before capping
    so summary keeps the highest-value routing signals.
    Plan 266: cap workflow_state prose on ``detail=full``.
    Plan 273: summary omits diary bodies and dump lists.
    """
    mode = (detail or "summary").strip().lower()
    payload = dict(payload)
    payload["detail"] = "full" if mode == "full" else "summary"
    if mode == "full":
        return _cap_workflow_prose(payload, _FULL_WORKFLOW_CHARS)
    dropped = {k: v for k, v in payload.items() if k not in _SUMMARY_DROP_KEYS}
    return _omit_workflow_prose(_trim(dropped))


def _omit_workflow_prose(payload: dict[str, Any]) -> dict[str, Any]:
    """Summary omits diary bodies (Plan 273). Full still uses the 266 caps."""
    workflow = payload.get("workflow_state")
    if not isinstance(workflow, dict):
        return payload
    kept = {key: value for key, value in workflow.items() if key not in _WORKFLOW_PROSE_KEYS}
    out = dict(payload)
    if kept:
        out["workflow_state"] = kept
    else:
        out.pop("workflow_state", None)
    return out


def _cap_workflow_prose(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    workflow = payload.get("workflow_state")
    if not isinstance(workflow, dict):
        return payload
    capped = dict(workflow)
    truncated: dict[str, int] = {}
    for key in _WORKFLOW_PROSE_KEYS:
        value = capped.get(key)
        if isinstance(value, str) and len(value) > limit:
            truncated[key] = len(value) - limit
            capped[key] = value[:limit]
    out = dict(payload)
    out["workflow_state"] = capped
    if truncated:
        out["workflow_state_truncated"] = truncated
    return out


def _sev_key(item: Any) -> int:
    if not isinstance(item, dict):
        return 9
    sev = str(item.get("severity") or item.get("rf.severity") or "medium").lower()
    return _SEVERITY_RANK.get(sev, 5)


def _trim(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            # Only string keys carry the markdown/cap conventions. Evidence dicts
            # can legitimately be keyed by ints (e.g. gaps.py similar_plans:
            # plan number -> shared-file count), so guard before string ops to
            # avoid ``'int' object has no attribute 'endswith'`` (Plan 248).
            if not isinstance(k, str):
                out[k] = _trim(v)
                continue
            if k.endswith("_markdown") or k == "markdown":
                continue
            if k in _SUMMARY_LIST_CAPS and isinstance(v, list):
                cap = _SUMMARY_LIST_CAPS[k]
                items = list(v)
                if k in {"challenges", "gaps", "open_findings"}:
                    items = sorted(items, key=_sev_key)
                out[k] = [_trim(x) for x in items[:cap]]
                if len(items) > cap:
                    out[f"{k}_truncated"] = len(items) - cap
            else:
                out[k] = _trim(v)
        return out
    if isinstance(obj, list):
        return [_trim(x) for x in obj]
    return obj
