"""Plan 246: plan vs code diff."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.diff_plan import diff_plan_vs_code
from agentscaffold.mcp.plan_card import count_execution_checkboxes


def test_count_checkboxes() -> None:
    text = "## Execution Steps\n- [ ] Step one\n- [x] Step two\n- [X] Step three\n"
    unchecked, checked = count_execution_checkboxes(text)
    assert unchecked == 1
    assert checked == 2


def test_diff_reports_missing_and_existing(tmp_path: Path) -> None:
    plan = tmp_path / "docs" / "ai" / "plans" / "1-x.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "# Plan\n\n## File Impact Map\n\n| File | Change Type | Notes |\n"
        "|------|-------------|-------|\n"
        "| `src/exists.py` | NEW | |\n"
        "| `src/missing.py` | NEW | |\n\n"
        "## Execution Steps\n- [ ] Do thing\n- [x] Done\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "exists.py").write_text("x=1\n", encoding="utf-8")

    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={
                "p.number": 1,
                "p.title": "T",
                "p.status": "In Progress",
                "p.filePath": "docs/ai/plans/1-x.md",
                "p.lastUpdated": "2026-07-12",
            },
        ),
        patch("agentscaffold.review.queries.get_plan_impacted_files", return_value=[]),
        patch("agentscaffold.mcp.diff_plan._file_in_graph", return_value=False),
        patch(
            "agentscaffold.mcp.plan_card._open_finding_summary",
            return_value={"count": 0, "ids": []},
        ),
    ):
        result = diff_plan_vs_code(store, 1, root=tmp_path)

    assert "src/exists.py" in result["existing_on_disk"]
    assert "src/missing.py" in result["missing_on_disk"]
    assert result["unchecked_steps"] == 1
    assert result["checked_steps"] == 1
    assert result["next_unchecked_step"] == "Do thing"
    assert result["summary"]["coarse_status"] == "in_progress"
    assert result["summary"]["next_unchecked_step"] == "Do thing"
