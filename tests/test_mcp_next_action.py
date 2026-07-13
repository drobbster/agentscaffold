"""Plan 246: next_action router."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.next_action import next_actions


def test_next_action_bounded_with_tool_names(tmp_path: Path) -> None:
    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={
                "p.number": 10,
                "p.title": "T",
                "p.status": "In Progress",
                "p.filePath": "",
                "p.lastUpdated": "",
            },
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
            workflow={"blockers": "None", "in_progress_plans": ["10: T"]},
            meta={},
            plan_number=10,
        )

    assert 1 <= result["action_count"] <= 3
    assert all("tool" in a and a["tool"].startswith("scaffold_") for a in result["actions"])
