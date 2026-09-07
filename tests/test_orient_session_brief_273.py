"""Plan 273: session_brief router -- Session + plan Status, not the diary."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.detail import apply_detail
from agentscaffold.mcp.next_action import next_actions
from agentscaffold.mcp.session_brief import build_session_brief
from agentscaffold.mcp.workflow_state import parse_workflow_text

GOVERNANCE_DIARY = """# Workflow State

## Blockers
- Rebellion MCP version skew (standing inventory).
- Cloud git push 403.

## Current Implementation
| Plan | Status |
| 249 | **In Progress.** Phase A code-complete |

## Next Steps
- Keep working Plan 249.
"""

PLAN_251 = """# Remainder

## 0. Metadata
- Plan: 251
- Approval Required: Yes
- Status: Draft

## 8. Execution Steps
- [ ] Step 1: still open
"""

PLAN_270 = """# In flight

## 0. Metadata
- Plan: 270
- Approval Required: No
- Status: In Progress

## 8. Execution Steps
- [x] Step 1: done
- [ ] Step 2: next
- [ ] Step 3: later
"""

PLAN_COMPLETE = """# Done

## 0. Metadata
- Plan: 271
- Status: Complete

## 8. Execution Steps
- [x] Step 1: done
"""


def _write_plan(tmp_path: Path, number: int, body: str) -> Path:
    path = tmp_path / "docs" / "ai" / "plans" / f"{number}-plan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _row(number: int, path: Path, status: str, title: str = "T") -> dict:
    return {
        "p.number": number,
        "p.title": title,
        "p.status": status,
        "p.filePath": str(path),
        "p.lastUpdated": "",
    }


def _no_related() -> list:
    return [
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
    ]


def test_diary_249_does_not_win_over_session_251(tmp_path: Path) -> None:
    path_251 = _write_plan(tmp_path, 251, PLAN_251)
    _write_plan(tmp_path, 249, PLAN_COMPLETE.replace("271", "249"))
    workflow = parse_workflow_text(GOVERNANCE_DIARY)
    assert "249" in "".join(workflow.get("in_progress_plans") or [])

    store = MagicMock()
    session = {"id": "session::test", "plan_numbers": [251], "decisions": []}
    row = _row(251, path_251, "Draft", "Remainder")
    patches = [
        patch(
            "agentscaffold.graph.sessions.find_open_session",
            return_value=session,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=row,
        ),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[row],
        ),
        *_no_related(),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        brief = build_session_brief(store, root=tmp_path, workflow=workflow)

    assert brief["current_work"]["kind"] == "idle"
    assert brief["current_work"]["plan_number"] is None
    assert brief["next"]["tool"] == "scaffold_begin_plan"
    assert brief["next"]["arguments"]["plan_number"] == 251
    assert brief["next"]["arguments"]["dry_run"] is True
    assert "approval" in brief["next"]["rationale"].lower()
    assert brief["focus_plan"] == 251
    assert "249" not in str(brief["next"])


def test_in_flight_continues_and_ignores_house_blockers(tmp_path: Path) -> None:
    path = _write_plan(tmp_path, 270, PLAN_270)
    workflow = parse_workflow_text(GOVERNANCE_DIARY)
    store = MagicMock()
    row = _row(270, path, "In Progress", "In flight")
    session = {"id": "session::test", "plan_numbers": [270], "decisions": []}
    patches = [
        patch(
            "agentscaffold.graph.sessions.find_open_session",
            return_value=session,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=row,
        ),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[row],
        ),
        *_no_related(),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        brief = build_session_brief(store, root=tmp_path, workflow=workflow)
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow=workflow,
            session_brief=brief,
        )

    assert brief["current_work"]["kind"] == "in_flight"
    assert brief["current_work"]["plan_number"] == 270
    assert brief["next"]["tool"] == "scaffold_diff_plan_vs_code"
    assert brief["house_blockers_count"] >= 1
    assert not any(b.get("kind") == "named_blocker" for b in brief["blockers_for_work"])
    assert not any(a.get("tool") == "scaffold_orient" for a in result["actions"])


def test_complete_only_session_falls_through_to_idle_next(tmp_path: Path) -> None:
    done = _write_plan(tmp_path, 271, PLAN_COMPLETE)
    nxt = _write_plan(tmp_path, 251, PLAN_251)
    store = MagicMock()
    session = {"id": "session::test", "plan_numbers": [271], "decisions": []}

    def _by_number(_store: object, number: int) -> dict | None:
        if number == 271:
            return _row(271, done, "Complete")
        if number == 251:
            return _row(251, nxt, "Draft", "Remainder")
        return None

    patches = [
        patch(
            "agentscaffold.graph.sessions.find_open_session",
            return_value=session,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            side_effect=_by_number,
        ),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[
                _row(271, done, "Complete"),
                _row(251, nxt, "Draft", "Remainder"),
            ],
        ),
        *_no_related(),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        brief = build_session_brief(store, root=tmp_path, workflow={"blockers": "None"})

    assert brief["current_work"]["kind"] == "idle"
    assert brief["next"]["arguments"]["plan_number"] == 251


def test_empty_session_plan_numbers_falls_through(tmp_path: Path) -> None:
    path = _write_plan(tmp_path, 251, PLAN_251)
    store = MagicMock()
    session = {"id": "session::empty", "plan_numbers": [], "decisions": []}
    row = _row(251, path, "Draft")
    patches = [
        patch(
            "agentscaffold.graph.sessions.find_open_session",
            return_value=session,
        ),
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value=row,
        ),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[row],
        ),
        *_no_related(),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        brief = build_session_brief(store, root=tmp_path, workflow={"blockers": "None"})

    assert brief["next"]["arguments"]["plan_number"] == 251
    assert brief["current_work"]["kind"] == "idle"


def test_related_decisions_only_from_sessions_that_name_the_plan(
    tmp_path: Path,
) -> None:
    path = _write_plan(tmp_path, 273, PLAN_270.replace("270", "273"))
    store = MagicMock()
    row = _row(273, path, "In Progress")
    wanted = [{"decision": "Approve 273", "kind": "strategic"}]
    patches = [
        patch(
            "agentscaffold.graph.sessions.find_open_session",
            return_value={"id": "s", "plan_numbers": [273], "decisions": []},
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
            return_value=wanted,
        ),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        brief = build_session_brief(store, root=tmp_path, workflow={"blockers": "None"})

    assert brief["related"]["session_decisions"] == wanted


def test_no_session_no_gated_plan_is_idle_without_orient(tmp_path: Path) -> None:
    store = MagicMock()
    patches = [
        patch(
            "agentscaffold.graph.sessions.find_open_session",
            return_value=None,
        ),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[],
        ),
        *_no_related(),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        brief = build_session_brief(store, root=tmp_path, workflow={"blockers": "None"})
        result = next_actions(
            store,
            root=tmp_path,
            config=MagicMock(),
            workflow={"blockers": "None"},
            session_brief=brief,
        )

    assert brief["current_work"]["kind"] == "idle"
    assert brief["next"]["tool"] is None
    assert not any(a.get("tool") == "scaffold_orient" for a in result["actions"])


def test_summary_omits_workflow_diary_bodies() -> None:
    payload = {
        "session_brief": {"current_work": {"kind": "idle"}},
        "stats": {"files": 1},
        "recent_plans": [1],
        "hot_files": ["a"],
        "workflow_state": {
            "blockers": "standing",
            "next_steps": "do the diary",
            "current_implementation": "249 In Progress",
            "path": "/tmp/workflow_state.md",
        },
    }
    summary = apply_detail(payload, "summary")
    full = apply_detail(payload, "full")

    assert "next_steps" not in (summary.get("workflow_state") or {})
    assert "current_implementation" not in (summary.get("workflow_state") or {})
    assert "stats" not in summary
    assert "recent_plans" not in summary
    assert "hot_files" not in summary
    assert summary.get("session_brief")
    assert full["workflow_state"]["next_steps"] == "do the diary"
