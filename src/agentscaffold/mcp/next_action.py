"""Session next-action router for MCP agents (Plan 246 / 266 / 273)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentscaffold.mcp.session_brief import build_session_brief


def next_actions(
    store: Any,
    *,
    root: Path,
    config: Any,
    workflow: dict[str, Any],
    meta: dict[str, Any] | None = None,
    plan_number: int | None = None,
    project: str | None = None,
    session_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return 1–3 concrete next moves driven by ``session_brief``.

    Never recommends ``scaffold_orient``. Diary ``in_progress_plans`` is
    ignored (Plan 273).
    """
    meta = meta or {}
    brief = session_brief or build_session_brief(
        store,
        root=root,
        workflow=workflow,
        project=project,
        plan_number=plan_number,
    )
    actions: list[dict[str, Any]] = []
    nxt = brief.get("next") or {}
    if nxt.get("action"):
        entry = {
            "priority": 1,
            "action": nxt["action"],
            "tool": nxt.get("tool"),
            "arguments": nxt.get("arguments") or {},
            "rationale": nxt.get("rationale") or "",
        }
        if entry["tool"] != "scaffold_orient":
            actions.append(entry)

    if _unexpected_retrieval_degradation(meta):
        actions.append(
            {
                "priority": 2,
                "action": "Search is degraded; use keyword/grep fallbacks.",
                "tool": "scaffold_grep_graph",
                "arguments": {"pattern": "TODO"},
                "rationale": meta.get("retrieval_reason") or "retrieval degraded",
            }
        )

    actions = sorted(actions, key=lambda a: a.get("priority", 99))[:3]
    return {
        "plan_card": None,
        "focus_plan": brief.get("focus_plan"),
        "actions": actions,
        "action_count": len(actions),
        "session_brief": brief,
    }


def _unexpected_retrieval_degradation(meta: dict[str, Any]) -> bool:
    if meta.get("retrieval_status") != "degraded":
        return False
    policy = str(meta.get("embedding_policy") or "").strip().lower()
    return policy != "off"
