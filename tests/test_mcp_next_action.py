"""The next_action router."""

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


def _route(brief: dict, meta: dict | None = None) -> list[dict]:
    result = next_actions(
        MagicMock(), root=Path("."), config=MagicMock(), workflow={}, meta=meta or {},
        session_brief=brief,
    )  # fmt: skip
    return result["actions"]


def test_overdue_architecture_review_is_one_priority_two_action() -> None:
    brief = {
        "next": {"action": "Continue plan 10", "tool": "scaffold_diff_plan_vs_code"},
        "lifecycle_debt": {
            "architecture_review": "last_architecture_review is not recorded",
            "expired_reviews": {"count": 2, "items": ["a", "b"]},
        },
    }
    actions = _route(brief)
    assert [a["priority"] for a in actions] == [1, 2]
    lifecycle = actions[1]
    assert lifecycle["tool"] == "scaffold_inventory"
    assert lifecycle["arguments"] == {"mode": "review"}
    assert lifecycle["rationale"] == "last_architecture_review is not recorded"


def test_expired_reviews_are_counted_when_the_review_is_current() -> None:
    debt = {
        "expired_reviews": {"count": 2, "items": ["job:a (review by 2026-01-01)", "job:b"]},
        "overdue_deprecations": {"count": 1, "items": ["job:c"]},
        "health_snapshot": {"status": "not_evaluated", "reason": "no snapshot"},
    }
    (action,) = _route({"lifecycle_debt": debt})
    assert action["action"] == "Review 3 components past review_by."
    assert action["rationale"].startswith("job:a")


def test_no_lifecycle_action_without_debt() -> None:
    health_only = {"health_snapshot": {"status": "not_evaluated", "reason": "x"}}
    assert _route({"lifecycle_debt": health_only}) == []
    assert _route({"lifecycle_debt": {"error": "unreadable"}}) == []
    assert _route({"next": {}}) == []


def test_lifecycle_action_keeps_the_cap_of_three() -> None:
    brief = {
        "next": {"action": "Continue plan 10", "tool": "scaffold_diff_plan_vs_code"},
        "lifecycle_debt": {"architecture_review": "overdue"},
    }
    meta = {"retrieval_status": "degraded", "embedding_policy": "auto"}
    actions = _route(brief, meta)
    assert len(actions) == 3
    assert not any(a["tool"] == "scaffold_orient" for a in actions)
