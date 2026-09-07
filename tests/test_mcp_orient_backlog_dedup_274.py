"""Plan 274: orient backlog collapses qualified + unqualified copies."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.server import (
    _dedup_backlog_items,
    _tool_orient,
    _unqualified_backlog_id,
)


def test_unqualified_backlog_id_strips_project_prefix() -> None:
    assert (
        _unqualified_backlog_id("agentscaffold-governance::bi::57aae5941206") == "bi::57aae5941206"
    )
    assert _unqualified_backlog_id("bi::57aae5941206") == "bi::57aae5941206"


def test_dedup_prefers_qualified_id_and_keeps_unique_count() -> None:
    rows = [
        {"id": "bi::57aae5941206", "title": "dup", "priority": "P1"},
        {
            "id": "agentscaffold-governance::bi::57aae5941206",
            "title": "dup",
            "priority": "P1",
        },
        {"id": "bi::aaaaaaaaaaaa", "title": "other", "priority": "P2"},
    ]
    unique = _dedup_backlog_items(rows)
    assert len(unique) == 2
    assert unique[0]["id"] == "agentscaffold-governance::bi::57aae5941206"
    assert unique[1]["id"] == "bi::aaaaaaaaaaaa"
    suffixes = {_unqualified_backlog_id(str(r["id"])) for r in unique}
    assert len(suffixes) == 2


def test_dedup_fetch_window_yields_three_unique_when_first_rows_are_dups() -> None:
    rows = [
        {"id": "bi::111111111111", "title": "a"},
        {"id": "proj::bi::111111111111", "title": "a"},
        {"id": "bi::222222222222", "title": "b"},
        {"id": "bi::333333333333", "title": "c"},
        {"id": "bi::444444444444", "title": "d"},
    ]
    top3 = _dedup_backlog_items(rows, limit=3)
    assert len(top3) == 3
    suffixes = [_unqualified_backlog_id(str(r["id"])) for r in top3]
    assert suffixes == ["bi::111111111111", "bi::222222222222", "bi::333333333333"]
    assert top3[0]["id"] == "proj::bi::111111111111"


def _orient_stack(tmp_path: Path, *, backlog_rows: list[dict], count_rows: list[dict]):
    store = MagicMock()
    store.get_stats.return_value = {"files": 1, "plans": 1}
    store.query.return_value = count_rows
    config = MagicMock()
    patches = (
        patch(
            "agentscaffold.mcp.coverage.repo_coverage",
            return_value={"available": True, "parsed_pct": 90},
        ),
        patch("agentscaffold.review.queries.get_all_plans", return_value=[]),
        patch("agentscaffold.review.queries.get_hot_files", return_value=[]),
        patch("agentscaffold.review.queries.get_all_studies", return_value=[]),
        patch("agentscaffold.review.queries.get_all_adrs", return_value=[]),
        patch(
            "agentscaffold.review.queries.get_open_backlog_items",
            return_value=backlog_rows,
        ),
        patch(
            "agentscaffold.mcp.server._parse_workflow_state",
            return_value={"blockers": "None", "next_steps": "", "in_progress_plans": []},
        ),
        patch(
            "agentscaffold.mcp.session_brief.build_session_brief",
            return_value={
                "current_work": {"kind": "idle", "plan_number": None},
                "next": None,
                "focus_plan": None,
                "blockers_for_work": [],
                "related": {},
                "house_blockers_count": 0,
            },
        ),
        patch("agentscaffold.graph.sessions.find_open_session", return_value=None),
        patch(
            "agentscaffold.mcp.next_action.next_actions",
            return_value={"focus_plan": None, "actions": []},
        ),
        patch("agentscaffold.mcp.server._current_project_or_none", return_value=None),
    )
    return store, config, patches


def test_orient_top3_and_count_use_unique_backlog_ids(tmp_path: Path) -> None:
    backlog_rows = [
        {"bi.id": "bi::57aae5941206", "bi.title": "dup", "bi.priority": "P1"},
        {
            "bi.id": "agentscaffold-governance::bi::57aae5941206",
            "bi.title": "dup",
            "bi.priority": "P1",
        },
        {"bi.id": "bi::bbbbbbbbbbbb", "bi.title": "other", "bi.priority": "P2"},
    ]
    count_rows = [
        {"id": "bi::57aae5941206"},
        {"id": "agentscaffold-governance::bi::57aae5941206"},
        {"id": "bi::bbbbbbbbbbbb"},
    ]
    store, config, patches = _orient_stack(
        tmp_path, backlog_rows=backlog_rows, count_rows=count_rows
    )
    with ExitStack() as stack:
        for ctx in patches:
            stack.enter_context(ctx)
        result = _tool_orient(store, {}, tmp_path, config, {})

    top3 = result["open_backlog_top3"]
    assert len(top3) == 2
    ids = [row["id"] for row in top3]
    suffixes = {_unqualified_backlog_id(i) for i in ids}
    assert len(suffixes) == 2
    assert "agentscaffold-governance::bi::57aae5941206" in ids
    assert result["open_backlog_count"] == 2
