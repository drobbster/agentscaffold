"""Plan 276: orient checks the workflow diary against plan Status and its age."""

from __future__ import annotations

from datetime import date

import pytest

from agentscaffold.mcp.workflow_state import (
    blockers_that_name_focus,
    find_contradictions,
    house_blockers_count,
    parse_workflow_text,
)


def test_zero_padded_blocker_names_its_plan() -> None:
    blockers = "- Plan 028 waits on the vendor.\n- Plan 2800 is unrelated."
    assert blockers_that_name_focus(blockers, 28) == ["- Plan 028 waits on the vendor."]
    assert house_blockers_count(blockers, 28) == 1


def test_old_last_updated_is_stale() -> None:
    parsed = parse_workflow_text("**Last Updated**: 2026-01-05 (sample)\n", today=date(2026, 3, 1))
    assert parsed["stale"] is True
    assert parsed["last_updated"] == "2026-01-05"


def test_recent_last_updated_is_not_stale() -> None:
    parsed = parse_workflow_text("**Last Updated**: 2026-02-25\n", today=date(2026, 3, 1))
    assert parsed["stale"] is False


def test_missing_last_updated_is_unknown() -> None:
    parsed = parse_workflow_text("# Workflow State\n", today=date(2026, 3, 1))
    assert parsed["stale"] is None
    assert parsed["last_updated"] is None


def test_contradictions_name_both_views() -> None:
    statuses = {42: "Complete", 85: "Superseded", 90: "In Progress", 91: "Unknown"}
    found = find_contradictions(["42", "85", "90", "91"], statuses.get)
    assert found == [
        {"plan_number": 42, "workflow_state": "In Progress", "plan_status": "Complete"},
        {"plan_number": 85, "workflow_state": "In Progress", "plan_status": "Superseded"},
    ]


# ---------------------------------------------------------------------------
# orient
# ---------------------------------------------------------------------------

pytest.importorskip("duckdb", reason="duckdb not installed")


@pytest.fixture()
def orient(tmp_path, monkeypatch):
    from agentscaffold.mcp.server import _dispatch_tool
    from tests.fixtures.lone_project import STALE_WORKFLOW, build_lone_project

    monkeypatch.delenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", raising=False)
    repo = build_lone_project(tmp_path, workflow=STALE_WORKFLOW, draft_plan=True)
    return _dispatch_tool("scaffold_orient", {"working_path": str(repo)})


def test_orient_reports_the_diary_contradiction(orient) -> None:
    ws = orient["workflow_state"]
    assert {"plan_number": 42, "workflow_state": "In Progress", "plan_status": "Complete"} in ws[
        "contradictions"
    ]
    assert ws["stale"] is True
    assert ws["last_updated"] == "2026-01-05"


def test_idle_next_row_carries_title_and_status(orient) -> None:
    from tests.fixtures.lone_project import DRAFT_PLAN_NUMBER, DRAFT_PLAN_TITLE

    rows = [r for r in orient["plan_progress"] if r["plan_number"] == DRAFT_PLAN_NUMBER]
    assert rows, orient["plan_progress"]
    assert DRAFT_PLAN_TITLE in rows[0]["title"]
    assert rows[0]["status"] == "Draft"
