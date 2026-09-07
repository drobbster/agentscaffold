"""Plan 274: staleness plan_card reads Execution Steps via default_start()."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

PLAN_274_BODY = """# Plan 274 card fixture

## 8. Tests
- [x] Ignore this checklist

## 9. Execution Steps
- [x] One
- [x] Two
- [ ] Three
"""


def _plan_row(rel_path: str) -> dict:
    return {
        "p.number": 274,
        "p.title": "Card counts",
        "p.status": "Draft",
        "p.filePath": rel_path,
        "p.lastUpdated": "2026-09-07",
    }


def _staleness_patches(plan_row: dict):
    return (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=plan_row,
        ),
        patch("agentscaffold.review.queries.get_plan_impacted_files", return_value=[]),
        patch("agentscaffold.review.queries.get_all_plans", return_value=[]),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
        patch(
            "agentscaffold.mcp.plan_card._open_finding_summary",
            return_value={"count": 0, "ids": []},
        ),
    )


def test_staleness_plan_card_reads_steps_when_default_start_is_plan_root(
    tmp_path: Path,
) -> None:
    from agentscaffold.mcp.server import _tool_staleness_check

    rel = "docs/ai/plans/274-card.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(PLAN_274_BODY, encoding="utf-8")

    store = MagicMock()
    store.get_stats.return_value = {"files": 1, "plans": 1}
    with ExitStack() as stack:
        for ctx in _staleness_patches(_plan_row(rel)):
            stack.enter_context(ctx)
        stack.enter_context(patch("agentscaffold.active_root.default_start", return_value=tmp_path))
        result = _tool_staleness_check(store, {"plan_number": 274}, {})

    card = result["plan_card"]
    assert card is not None
    assert card["checked_steps"] == 2
    assert card["unchecked_steps"] == 1
    assert "Three" in (card["next_unchecked_step"] or "")


def test_staleness_plan_card_stays_zero_when_default_start_misses_file(
    tmp_path: Path,
) -> None:
    from agentscaffold.mcp.server import _tool_staleness_check

    rel = "docs/ai/plans/274-card.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(PLAN_274_BODY, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    store = MagicMock()
    store.get_stats.return_value = {"files": 1, "plans": 1}
    with ExitStack() as stack:
        for ctx in _staleness_patches(_plan_row(rel)):
            stack.enter_context(ctx)
        stack.enter_context(
            patch("agentscaffold.active_root.default_start", return_value=elsewhere)
        )
        result = _tool_staleness_check(store, {"plan_number": 274}, {})

    card = result["plan_card"]
    assert card is not None
    assert card["checked_steps"] == 0
    assert card["unchecked_steps"] == 0
