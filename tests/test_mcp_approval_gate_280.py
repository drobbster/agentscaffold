"""Plan 280: implementation prep refuses an approval-required plan until approval is recorded."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.mcp.governance_delivery import approval_record

pytest.importorskip("duckdb", reason="duckdb not installed")

GATED = 91
PLAN_PATH = f"docs/ai/plans/plan_{GATED:03d}_rotate_keys.md"


def _plan(*, status: str = "Draft", required: str = "Yes", approved: str = "") -> str:
    approved_line = f"- Approved: {approved}\n" if approved else ""
    return (
        f"# Plan {GATED:03d}: Rotate signing keys\n\n"
        "## 0. Metadata\n"
        f"- Plan: {GATED}\n"
        f"- Status: {status}\n"
        f"- Approval Required: {required}\n"
        f"{approved_line}"
        "- Created: 2026-03-02\n"
        "- Last Updated: 2026-03-02\n\n"
        "## 6. Execution Steps\n"
        "- [ ] Step 1: Write the failing test.\n"
    )


def _workflow(approvals: str = "", next_steps: str = "- None\n") -> str:
    return (
        "# Workflow State\n\n**Last Updated**: 2026-11-04\n\n"
        "## Blockers\n\n- None\n\n"
        f"## Approvals\n\n{approvals}\n"
        f"## Next Steps\n\n{next_steps}"
    )


def _build(tmp_path, *, plan: str | None = None, workflow: str | None = None, extra_config=""):
    from tests.fixtures.lone_project import build_lone_project

    return build_lone_project(
        tmp_path,
        workflow=workflow or _workflow(),
        manual="## Execution Rules\nFollow the steps in order.\n",
        extra_files={PLAN_PATH: plan or _plan()},
        extra_config=extra_config,
    )


def _prepare(root: Path, **arguments):
    from agentscaffold.mcp.server import _dispatch_tool

    return _dispatch_tool(
        "scaffold_prepare_implementation",
        {"working_path": str(root), "plan_number": GATED, **arguments},
    )


def _brief_next(root: Path) -> str:
    from agentscaffold.mcp.server import _dispatch_tool

    result = _dispatch_tool("scaffold_orient", {"working_path": str(root), "plan_number": GATED})
    return result["session_brief"]["next"]["action"]


def test_unapproved_plan_gets_only_the_gate_and_its_rules(tmp_path) -> None:
    root = _build(tmp_path)
    result = _prepare(root)
    assert "brief" not in result and "impacted_files" not in result
    gate = result["gate"]
    assert gate["blocked"] is True
    assert gate["reason"] == "approval_missing"
    assert gate["ask"] == f"Do you approve proceeding with Plan {GATED} implementation?"
    assert "- Approved: YYYY-MM-DD by <name>" in gate["record"]
    sections = result["governance_sections"]
    assert sections["step"] == "implementation"
    assert sections["sections"][0]["heading"] == "Execution Rules"


def test_the_gate_does_not_depend_on_gate_transition(tmp_path) -> None:
    root = _build(tmp_path)
    assert _prepare(root, gate_transition=False)["gate"]["blocked"] is True


def test_an_approved_line_in_the_plan_passes(tmp_path) -> None:
    root = _build(tmp_path)
    (root / PLAN_PATH).write_text(_plan(approved="2026-11-04 by daverobb"))
    result = _prepare(root)
    assert "gate" not in result
    assert "brief" in result
    assert result["approval"] == {
        "recorded": True,
        "source": "plan",
        "line": "- Approved: 2026-11-04 by daverobb",
    }


def test_a_workflow_state_approval_passes(tmp_path) -> None:
    entry = f"- **Plan {GATED:03d} -- APPROVED 2026-11-04 by daverobb.** Key rotation.\n"
    root = _build(tmp_path, workflow=_workflow(approvals=entry))
    result = _prepare(root)
    assert "gate" not in result
    assert result["approval"]["source"] == "workflow_state"
    assert result["approval"]["line"].startswith(f"- **Plan {GATED:03d} -- APPROVED")


def test_pending_is_not_an_approval(tmp_path) -> None:
    root = _build(tmp_path, plan=_plan(approved="Pending"))
    assert _prepare(root)["gate"]["blocked"] is True


def test_an_approval_outside_the_approvals_section_does_not_count(tmp_path) -> None:
    stray = f"- **Plan {GATED} -- APPROVED** once the keys are rotated.\n"
    root = _build(tmp_path, workflow=_workflow(next_steps=stray))
    assert _prepare(root)["gate"]["blocked"] is True


def test_approval_gates_off_skips_the_check(tmp_path) -> None:
    config = "gates:\n  ready_to_in_progress:\n    approval_gates: false\n"
    root = _build(tmp_path, extra_config=config)
    result = _prepare(root)
    assert "gate" not in result and "approval" not in result
    assert "brief" in result


def test_a_plan_without_required_approval_is_not_gated(tmp_path) -> None:
    root = _build(tmp_path, plan=_plan(required="No"))
    result = _prepare(root)
    assert "gate" not in result and "approval" not in result


@pytest.mark.parametrize("status", ["Draft", "Review", "Ready"])
def test_session_brief_presents_for_approval_until_recorded(tmp_path, status) -> None:
    root = _build(tmp_path, plan=_plan(status=status))
    assert _brief_next(root) == f"Present Plan {GATED} for approval (do not implement)."

    (root / PLAN_PATH).write_text(_plan(status=status, approved="2026-11-04 by daverobb"))
    assert not _brief_next(root).startswith("Present Plan")


def test_record_matches_the_shapes_this_repository_uses() -> None:
    plan_line = "- Approved: 2026-11-04 by daverobb"
    assert approval_record(f"## 0. Metadata\n{plan_line}\n", 276, None)["line"] == plan_line
    assert approval_record("- Approved: Pending\n", 276, None) is None
