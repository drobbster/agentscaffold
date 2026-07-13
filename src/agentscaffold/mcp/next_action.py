"""Session next-action router for MCP agents (Plan 246)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentscaffold.mcp.plan_card import build_plan_card
from agentscaffold.review.filters import normalize_plan_status


def next_actions(
    store: Any,
    *,
    root: Path,
    config: Any,
    workflow: dict[str, Any],
    meta: dict[str, Any] | None = None,
    plan_number: int | None = None,
) -> dict[str, Any]:
    """Return 1–3 concrete next moves with suggested tool calls."""
    from agentscaffold.review.queries import get_all_plans, get_plan_by_number

    actions: list[dict[str, Any]] = []
    meta = meta or {}

    # Prefer explicit plan, else first in-progress from workflow, else newest draft/in-progress
    target_pn = plan_number
    if target_pn is None:
        in_prog = workflow.get("in_progress_plans") or []
        if in_prog:
            # entries may be strings like "243: title" or just numbers
            target_pn = _parse_plan_ref(in_prog[0])

    plan = get_plan_by_number(store, target_pn) if target_pn is not None else None
    if plan is None:
        plans = get_all_plans(store)
        for p in plans:
            st = normalize_plan_status(p.get("p.status"))
            if st in {"In Progress", "Ready", "Draft", "Review"}:
                plan = p
                target_pn = int(p.get("p.number"))
                break

    card = None
    if target_pn is not None:
        card = build_plan_card(store, int(target_pn), root=root, plan_row=plan)

    blockers = (workflow.get("blockers") or "").strip()
    if blockers and blockers.lower() not in {"none", "n/a", "-"}:
        actions.append(
            {
                "priority": 1,
                "action": "Resolve workflow blockers before new implementation.",
                "tool": "scaffold_orient",
                "arguments": {},
                "rationale": "workflow_state reports active blockers",
            }
        )

    if card:
        status = card.get("status_normalized")
        if status in {"Draft", "Review"}:
            actions.append(
                {
                    "priority": 2,
                    "action": f"Run pre-implementation review for Plan {card['plan_number']}.",
                    "tool": "scaffold_begin_plan",
                    "arguments": {"plan_number": card["plan_number"], "dry_run": True},
                    "rationale": "plan not yet through begin-plan / reviewedAt gate",
                }
            )
        elif status in {"Ready", "In Progress"}:
            if card.get("unchecked_steps", 0) > 0:
                actions.append(
                    {
                        "priority": 2,
                        "action": (
                            f"Continue Plan {card['plan_number']}: "
                            f"{card['unchecked_steps']} unchecked steps remain."
                        ),
                        "tool": "scaffold_diff_plan_vs_code",
                        "arguments": {"plan_number": card["plan_number"]},
                        "rationale": "unchecked execution steps remain",
                    }
                )
            else:
                actions.append(
                    {
                        "priority": 2,
                        "action": (
                            f"Close out Plan {card['plan_number']} "
                            "with post-implementation review."
                        ),
                        "tool": "scaffold_complete_plan",
                        "arguments": {"plan_number": card["plan_number"], "dry_run": True},
                        "rationale": "no unchecked steps; ready for retro rehearsal",
                    }
                )
        elif status == "Complete":
            actions.append(
                {
                    "priority": 2,
                    "action": "Orient for the next priority plan.",
                    "tool": "scaffold_orient",
                    "arguments": {},
                    "rationale": "target plan already complete",
                }
            )

    if meta.get("retrieval_status") == "degraded":
        actions.append(
            {
                "priority": 3,
                "action": "Search is degraded; use keyword/grep fallbacks.",
                "tool": "scaffold_grep_graph",
                "arguments": {"pattern": "TODO"},
                "rationale": meta.get("retrieval_reason") or "retrieval degraded",
            }
        )

    if not actions:
        actions.append(
            {
                "priority": 1,
                "action": "Orient on current blockers and recent plans.",
                "tool": "scaffold_orient",
                "arguments": {},
                "rationale": "no stronger signal available",
            }
        )

    # Bound to 3, sort by priority
    actions = sorted(actions, key=lambda a: a.get("priority", 99))[:3]
    return {
        "plan_card": card,
        "focus_plan": target_pn,
        "actions": actions,
        "action_count": len(actions),
    }


def _parse_plan_ref(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    # "243: title" or "Plan 243" or "243"
    import re

    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None
