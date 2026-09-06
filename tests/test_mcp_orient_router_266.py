"""Plan 266: scaffold_orient session-router regressions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.detail import apply_detail
from agentscaffold.mcp.next_action import next_actions
from agentscaffold.mcp.plan_card import build_plan_card
from agentscaffold.mcp.workflow_state import parse_workflow_text
from agentscaffold.review.filters import normalize_plan_status

REBELLION_WORKFLOW = """# Workflow State

## Blockers
- **Plan 022 (Revenue Quality)**: Blocked on Plan 023.
- ~~**Plan 103**~~: UNBLOCKED (2026-02-27).
- **Plan 106 (Alternative Data)**: Blocked on external vendors.

## Current Implementation
- **EA removed from the D-1 freeze, 2026-09-06.**
  Next on Plan 270 is Step 7 IBKR. Do not flip 263 / D-4.
- **B-DATA-16 paper-book half landed, 2026-09-06.**
  Cadence stays on B-DATA-16. Next on Plan 270 is Step 7 IBKR.

## Next Steps
Plans 261-270 were reviewed. **270** is layer assembly.

## History
- **B-PROC-1 closed, 2026-08-18.** Plan 259 is no longer IN PROGRESS.
- **Plan 260 IN PROGRESS (Strategy catalog conformance), 2026-08-06.**
"""

PLAN_270 = """# Layer Assembly

## 0. Metadata
- Created: 2026-08-31

## 8. Tests
- [ ] Unit tests for core logic

## 9. Execution Steps
- [x] Step 0: Decide section 5.2
- [x] Step 6: Wire runtime keys
- [ ] Step 7: IBKR paper evidence session
- [ ] Step 8: Docs
"""

CLEAN_WORKFLOW = """# Workflow State

## Blockers
None

## Next Steps
- Keep the graph walk as the focus signal.
"""


def _plan_270_path(tmp_path: Path) -> Path:
    path = tmp_path / "docs" / "ai" / "plans" / "270-layer-assembly.md"
    path.parent.mkdir(parents=True)
    path.write_text(PLAN_270, encoding="utf-8")
    return path


def _full_plan_row(tmp_path: Path) -> dict:
    return {
        "p.number": 270,
        "p.title": "Layer assembly",
        "p.status": "unknown",
        "p.filePath": str(_plan_270_path(tmp_path)),
        "p.lastUpdated": "",
    }


def test_rebellion_shaped_focus_is_270_not_259() -> None:
    parsed = parse_workflow_text(REBELLION_WORKFLOW)
    assert parsed["in_progress_plans"][0] == "270"
    assert "259" not in parsed["in_progress_plans"]
    assert parsed["workflow_live"]["focus_plan"] == 270
    assert parsed["live_blockers"] == []


def test_named_focus_blocker_escalates_struck_does_not() -> None:
    text = REBELLION_WORKFLOW.replace(
        "- **Plan 106 (Alternative Data)**: Blocked on external vendors.",
        "- **Plan 270**: Blocked on a live broker credential.\n"
        "- ~~**Plan 270** leftover~~: already done.",
    )
    parsed = parse_workflow_text(text)
    assert len(parsed["live_blockers"]) == 1
    assert "270" in parsed["live_blockers"][0]


def test_plan_card_refetch_when_get_all_plans_row_omits_filepath(tmp_path: Path) -> None:
    full = _full_plan_row(tmp_path)
    partial = {
        "p.number": 270,
        "p.title": "Layer assembly",
        "p.status": "unknown",
    }
    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=full,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_impacted_files",
            return_value=[],
        ),
        patch(
            "agentscaffold.mcp.plan_card._open_finding_summary",
            return_value={"count": 0, "ids": []},
        ),
    ):
        card = build_plan_card(store, 270, root=tmp_path, plan_row=partial)

    assert card is not None
    assert card["unchecked_steps"] == 2
    assert card["checked_steps"] == 2
    assert "Step 7" in (card["next_unchecked_step"] or "")


def test_next_actions_continue_270_skips_standing_blockers_and_policy_off(
    tmp_path: Path,
) -> None:
    parsed = parse_workflow_text(REBELLION_WORKFLOW)
    full = _full_plan_row(tmp_path)
    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=full,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_impacted_files",
            return_value=[],
        ),
        patch(
            "agentscaffold.mcp.plan_card._open_finding_summary",
            return_value={"count": 0, "ids": []},
        ),
    ):
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow=parsed,
            meta={
                "retrieval_status": "degraded",
                "retrieval_reason": "no embeddings indexed",
                "embedding_policy": "off",
            },
        )

    actions = [a["action"] for a in result["actions"]]
    assert result["focus_plan"] == 270
    assert any("Continue Plan 270" in a and "unchecked" in a for a in actions)
    assert any(a.get("tool") == "scaffold_diff_plan_vs_code" for a in result["actions"])
    assert not any("blockers" in a.lower() for a in actions)
    assert not any("orient again" in a.lower() or "next priority" in a.lower() for a in actions)
    assert not any("degraded" in a.lower() for a in actions)


def test_search_degraded_action_when_embeddings_not_policy_off(tmp_path: Path) -> None:
    parsed = parse_workflow_text(REBELLION_WORKFLOW)
    full = _full_plan_row(tmp_path)
    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=full,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_impacted_files",
            return_value=[],
        ),
        patch(
            "agentscaffold.mcp.plan_card._open_finding_summary",
            return_value={"count": 0, "ids": []},
        ),
    ):
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow=parsed,
            meta={
                "retrieval_status": "degraded",
                "retrieval_reason": "no embeddings indexed",
                "embedding_policy": "idle",
            },
        )

    assert any("degraded" in a["action"].lower() for a in result["actions"])


def test_named_blocker_is_priority_one(tmp_path: Path) -> None:
    text = REBELLION_WORKFLOW.replace(
        "- **Plan 106 (Alternative Data)**: Blocked on external vendors.",
        "- **Plan 270**: Waiting on broker paper credentials.",
    )
    parsed = parse_workflow_text(text)
    full = _full_plan_row(tmp_path)
    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=full,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_impacted_files",
            return_value=[],
        ),
        patch(
            "agentscaffold.mcp.plan_card._open_finding_summary",
            return_value={"count": 0, "ids": []},
        ),
    ):
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow=parsed,
            meta={"embedding_policy": "off"},
        )

    assert result["actions"][0]["priority"] == 1
    assert "blockers" in result["actions"][0]["action"].lower()


def test_explicit_plan_number_wins_over_extracted_focus(tmp_path: Path) -> None:
    parsed = parse_workflow_text(REBELLION_WORKFLOW)
    other = {
        "p.number": 10,
        "p.title": "Other",
        "p.status": "In Progress",
        "p.filePath": "",
        "p.lastUpdated": "",
    }
    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=other,
        ),
        patch(
            "agentscaffold.mcp.next_action.build_plan_card",
            return_value={
                "plan_number": 10,
                "status_normalized": "In Progress",
                "unchecked_steps": 3,
                "checked_steps": 1,
            },
        ),
    ):
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow=parsed,
            meta={},
            plan_number=10,
        )

    assert result["focus_plan"] == 10
    assert any("Continue Plan 10" in a["action"] for a in result["actions"])


def test_clean_workflow_falls_through_to_graph_in_progress(tmp_path: Path) -> None:
    parsed = parse_workflow_text(CLEAN_WORKFLOW)
    assert parsed["in_progress_plans"] == []
    store = MagicMock()
    graph_row = {
        "p.number": 10,
        "p.title": "Clean plan",
        "p.status": "In Progress",
        "p.filePath": "",
        "p.lastUpdated": "",
    }
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=None,
        ),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[graph_row],
        ),
        patch(
            "agentscaffold.mcp.next_action.build_plan_card",
            return_value={
                "plan_number": 10,
                "status_normalized": "In Progress",
                "unchecked_steps": 2,
                "checked_steps": 0,
            },
        ),
    ):
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow=parsed,
            meta={},
        )

    assert result["focus_plan"] == 10
    assert not any("blockers" in a["action"].lower() for a in result["actions"])


def test_normalize_complete_before_embedded_review() -> None:
    assert (
        normalize_plan_status(
            "COMPLETE (post-implementation review in section 14; CI green on 968c44c6)"
        )
        == "Complete"
    )


def test_summary_caps_workflow_prose_and_keeps_excerpt() -> None:
    huge = "x" * 10_000
    payload = {
        "workflow_state": {
            "blockers": "None",
            "next_steps": huge,
            "current_implementation": "- Next on Plan 270 is Step 7.\n- Follow-through.",
        },
        "workflow_live": {
            "focus_plan": 270,
            "current_excerpt": "- Next on Plan 270 is Step 7.",
            "live_blocker_count": 0,
        },
    }
    summary = apply_detail(payload, "summary")
    full = apply_detail(payload, "full")

    assert len(summary["workflow_state"]["next_steps"]) == 2000
    assert summary["workflow_state_truncated"]["next_steps"] == 8000
    assert summary["workflow_live"]["current_excerpt"].startswith("- Next on Plan 270")
    assert len(full["workflow_state"]["next_steps"]) == 8000
    assert full["workflow_state_truncated"]["next_steps"] == 2000


def test_empty_workflow_has_no_focus() -> None:
    parsed = parse_workflow_text("")
    assert parsed["in_progress_plans"] == []
    assert parsed["live_blockers"] == []
    assert parsed["workflow_live"]["focus_plan"] is None
