"""Plan 266 edge cases: diary idioms, routing inference, file/parse misses."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.detail import apply_detail
from agentscaffold.mcp.next_action import (
    _routing_status,
    _unexpected_retrieval_degradation,
    next_actions,
)
from agentscaffold.mcp.workflow_state import parse_workflow_file, parse_workflow_text
from agentscaffold.review.filters import normalize_plan_status


def _ws(*sections: str) -> str:
    return "# Workflow State\n\n" + "\n\n".join(sections) + "\n"


def _focus(text: str) -> int | None:
    return parse_workflow_text(text)["workflow_live"]["focus_plan"]


def test_first_next_on_in_newest_bullets_beats_stale_next_on() -> None:
    text = _ws(
        "## Current Implementation",
        "- **Plan 270 COMPLETE.**\n  Next: Plan 262 Steps 9-12.",
        "- **Older note.**\n  Next on Plan 270 is Step 7.",
    )
    assert _focus(text) == 262


def test_next_colon_and_next_on_are_both_live_signals() -> None:
    assert _focus(_ws("## Current Implementation", "- Next: Plan 12.")) == 12
    assert _focus(_ws("## Current Implementation", "- Next on Plan 12.")) == 12


def test_next_week_is_not_a_next_on_signal() -> None:
    """'Next week Plan 10' must not win as Next-on; frequency can still see Plan 5."""
    text = _ws(
        "## Current Implementation",
        "- Next week Plan 10 starts after the freeze.",
        "- Plan 5 mentioned.",
        "- Plan 5 again.",
    )
    assert _focus(text) == 5


def test_do_not_flip_other_plan_does_not_override_next_on() -> None:
    text = _ws(
        "## Current Implementation",
        "- Next on Plan 270 is Step 7. Do not flip 263 / D-4.",
    )
    parsed = parse_workflow_text(text)
    assert parsed["in_progress_plans"][0] == "270"


def test_frequency_fallback_when_no_next_on() -> None:
    text = _ws(
        "## Current Implementation",
        "- Plan 005 mentioned.",
        "- Plan 005 again, still no next-on.",
        "- Plan 010 once.",
    )
    assert _focus(text) == 5


def test_sixteenth_bullet_next_on_is_outside_the_cap() -> None:
    bullets = "\n".join(f"- Filler {i} Plan 001." for i in range(15))
    bullets += "\n- Next on Plan 99 is the live one."
    text = _ws("## Current Implementation", bullets)
    assert _focus(text) != 99
    assert _focus(text) == 1


def test_missing_current_implementation_uses_next_steps() -> None:
    text = _ws(
        "## Blockers\nNone",
        "## Next Steps",
        "- Next on Plan 10 after the review.",
    )
    assert _focus(text) == 10


def test_next_on_past_first_80_next_steps_lines_is_ignored() -> None:
    head = "\n".join(f"- History line {i}." for i in range(80))
    text = _ws("## Next Steps", head + "\n- Next on Plan 99 is too deep.")
    assert _focus(text) is None


def test_in_progress_fallback_skips_no_longer() -> None:
    text = _ws(
        "## Current Implementation",
        "Plan 259 is no longer IN PROGRESS.",
        "Plan 10 is IN PROGRESS.",
    )
    assert _focus(text) == 10


def test_not_in_progress_is_not_focus() -> None:
    text = _ws(
        "## Current Implementation",
        "Plan 10 is not in progress.",
    )
    assert _focus(text) is None


def test_history_in_progress_is_invisible_when_current_has_next_on() -> None:
    text = _ws(
        "## Current Implementation",
        "- Next on Plan 270 is Step 7.",
        "## History",
        "- Plan 260 IN PROGRESS (2026-08-06).",
        "- Plan 259 is no longer IN PROGRESS.",
    )
    parsed = parse_workflow_text(text)
    assert parsed["in_progress_plans"][0] == "270"
    assert "259" not in parsed["in_progress_plans"]
    assert "260" not in parsed["in_progress_plans"]


def test_blockers_plan_number_is_not_focus() -> None:
    text = _ws(
        "## Blockers",
        "- **Plan 022**: standing vendor wait.",
        "## Current Implementation",
        "- Keep assembling. No plan number here.",
    )
    assert _focus(text) is None


def test_struck_next_on_is_ignored() -> None:
    text = _ws(
        "## Current Implementation",
        "- ~~Next on Plan 99~~ already shipped.",
        "- Next on Plan 12 is live.",
    )
    assert _focus(text) == 12


def test_star_bullet_next_on() -> None:
    assert _focus(_ws("## Current Implementation", "* Next on Plan 8.")) == 8


def test_resolved_and_unblocked_blockers_that_name_focus_do_not_escalate() -> None:
    text = _ws(
        "## Blockers",
        "- **Plan 270**: RESOLVED 2026-09-06.",
        "- **Plan 270**: UNBLOCKED after credentials landed.",
        "## Current Implementation",
        "- Next on Plan 270 is Step 7.",
    )
    parsed = parse_workflow_text(text)
    assert parsed["workflow_live"]["focus_plan"] == 270
    assert parsed["live_blockers"] == []


def test_empty_blocker_sentinels_are_not_live() -> None:
    for body in ("None", "n/a", "-", "N/A"):
        parsed = parse_workflow_text(
            _ws(f"## Blockers\n{body}", "## Current Implementation\n- Next on Plan 3.")
        )
        assert parsed["live_blockers"] == []


def test_html_comment_only_blockers_are_not_live() -> None:
    text = _ws(
        "## Blockers",
        "<!-- Clear when resolved -->",
        "## Current Implementation",
        "- Next on Plan 3.",
    )
    assert parse_workflow_text(text)["live_blockers"] == []


def test_standing_blockers_without_focus_are_not_priority_one(tmp_path: Path) -> None:
    parsed = parse_workflow_text(
        _ws("## Blockers", "- **Plan 022**: standing.", "## Next Steps", "- Keep going.")
    )
    assert parsed["workflow_live"]["focus_plan"] is None
    result = next_actions(
        MagicMock(),
        root=tmp_path,
        config=MagicMock(),
        workflow=parsed,
        meta={},
    )
    assert not any("Resolve workflow blockers" in a["action"] for a in result["actions"])


def test_missing_workflow_file() -> None:
    result = parse_workflow_file(Path("/no/such/agentscaffold-root"), None)
    assert result["error"] == "workflow_state.md not found"


def test_parse_workflow_file_reads_disk(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ai" / "state" / "workflow_state.md"
    path.parent.mkdir(parents=True)
    path.write_text(_ws("## Current Implementation", "- Next on Plan 4."), encoding="utf-8")
    parsed = parse_workflow_file(tmp_path, None)
    assert parsed["workflow_live"]["focus_plan"] == 4
    assert parsed["path"] == str(path)


def test_routing_status_inferred_from_checkbox_mix() -> None:
    assert (
        _routing_status({"status_normalized": "Unknown", "unchecked_steps": 2, "checked_steps": 3})
        == "In Progress"
    )
    assert (
        _routing_status({"status_normalized": "Unknown", "unchecked_steps": 2, "checked_steps": 0})
        == "Draft"
    )
    assert (
        _routing_status({"status_normalized": "Unknown", "unchecked_steps": 0, "checked_steps": 4})
        == "Complete"
    )
    assert (
        _routing_status({"status_normalized": "Unknown", "unchecked_steps": 0, "checked_steps": 0})
        == "Unknown"
    )
    assert (
        _routing_status({"status_normalized": "Ready", "unchecked_steps": 0, "checked_steps": 4})
        == "Ready"
    )


def test_unknown_all_checked_recommends_close_out(tmp_path: Path) -> None:
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.number": 7, "p.status": "unknown", "p.filePath": ""},
        ),
        patch(
            "agentscaffold.mcp.next_action.build_plan_card",
            return_value={
                "plan_number": 7,
                "status_normalized": "Unknown",
                "unchecked_steps": 0,
                "checked_steps": 5,
            },
        ),
    ):
        result = next_actions(
            MagicMock(),
            root=tmp_path,
            config=MagicMock(),
            workflow={"in_progress_plans": ["7"], "live_blockers": []},
            meta={},
        )
    assert any("next priority plan" in a["action"].lower() for a in result["actions"])
    assert result["actions"][0]["rationale"] == "target plan already complete"


def test_unknown_all_unchecked_recommends_begin_plan(tmp_path: Path) -> None:
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.number": 7, "p.status": "unknown", "p.filePath": ""},
        ),
        patch(
            "agentscaffold.mcp.next_action.build_plan_card",
            return_value={
                "plan_number": 7,
                "status_normalized": "Unknown",
                "unchecked_steps": 4,
                "checked_steps": 0,
            },
        ),
    ):
        result = next_actions(
            MagicMock(),
            root=tmp_path,
            config=MagicMock(),
            workflow={"in_progress_plans": ["7"], "live_blockers": []},
            meta={},
        )
    assert any("pre-implementation review for Plan 7" in a["action"] for a in result["actions"])


def test_retrieval_policy_edges() -> None:
    degraded_off = {"retrieval_status": "degraded", "embedding_policy": "off"}
    degraded_idle = {"retrieval_status": "degraded", "embedding_policy": "idle"}
    available_off = {"retrieval_status": "available", "embedding_policy": "off"}
    degraded_empty = {"retrieval_status": "degraded", "embedding_policy": ""}
    assert _unexpected_retrieval_degradation(degraded_off) is False
    assert _unexpected_retrieval_degradation(degraded_idle) is True
    assert _unexpected_retrieval_degradation(available_off) is False
    assert _unexpected_retrieval_degradation({"retrieval_status": "degraded"}) is True
    assert _unexpected_retrieval_degradation(degraded_empty) is True
    assert _unexpected_retrieval_degradation({}) is False


def test_status_leftmost_and_ready_for_review() -> None:
    assert normalize_plan_status("Ready for review") == "Ready"
    assert normalize_plan_status("In Review") == "Review"
    assert normalize_plan_status("SUPERSEDED by Plan 12, was complete") == "Superseded"


def test_summary_does_not_truncate_short_prose() -> None:
    payload = {
        "workflow_state": {
            "blockers": "None",
            "next_steps": "short",
            "current_implementation": "also short",
        }
    }
    summary = apply_detail(payload, "summary")
    assert "workflow_state_truncated" not in summary
    assert summary["workflow_state"]["next_steps"] == "short"


def test_singular_blocker_heading() -> None:
    text = (
        "# Workflow State\n\n"
        "## Blocker\n- **Plan 3**: live wait.\n\n"
        "## Current Implementation\n- Next on Plan 3.\n"
    )
    parsed = parse_workflow_text(text)
    assert parsed["live_blockers"]
    assert "Plan 3" in parsed["live_blockers"][0]
