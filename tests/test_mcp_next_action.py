"""Plan 246 / 273: next_action router."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.next_action import next_actions


def test_next_action_never_recommends_orient(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ai" / "plans" / "10-t.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "## 0. Metadata\n- Status: In Progress\n\n## 8. Execution Steps\n- [x] a\n- [ ] b\n",
        encoding="utf-8",
    )
    row = {
        "p.number": 10,
        "p.title": "T",
        "p.status": "In Progress",
        "p.filePath": str(path),
        "p.lastUpdated": "",
    }
    store = MagicMock()
    with (
        patch(
            "agentscaffold.graph.sessions.find_open_session",
            return_value=None,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=row,
        ),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[row],
        ),
        patch(
            "agentscaffold.graph.findings.get_open_findings",
            return_value=[],
        ),
        patch(
            "agentscaffold.graph.backlog.get_backlog_items_for_plan",
            return_value=[],
        ),
        patch(
            "agentscaffold.graph.sessions.session_decisions_for_plan",
            return_value=[],
        ),
    ):
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow={"blockers": "None", "in_progress_plans": ["249: stale"]},
            meta={},
            plan_number=10,
        )

    assert 1 <= result["action_count"] <= 3
    assert not any(a.get("tool") == "scaffold_orient" for a in result["actions"])
    assert any(a.get("tool") == "scaffold_diff_plan_vs_code" for a in result["actions"])
