"""Tests for plan lifecycle commands (create, lint, status)."""

from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from agentscaffold.cli import app


def test_plan_create(tmp_project: Path, cli_runner: CliRunner) -> None:
    """plan create produces a plan file with the correct number and name."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["plan", "create", "Add Widgets"])
        assert result.exit_code == 0
        plans = list((tmp_project / "docs/ai/plans").glob("001-add-widgets.md"))
        assert len(plans) == 1
        content = plans[0].read_text()
        assert len(content) > 50
    finally:
        os.chdir(orig_cwd)


def test_plan_create_increments_number(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Creating two plans produces 001 and 002."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        cli_runner.invoke(app, ["plan", "create", "First Plan"])
        cli_runner.invoke(app, ["plan", "create", "Second Plan"])
        plans_dir = tmp_project / "docs/ai/plans"
        files = sorted(plans_dir.glob("*.md"))
        names = [f.name for f in files]
        assert "001-first-plan.md" in names
        assert "002-second-plan.md" in names
    finally:
        os.chdir(orig_cwd)


def test_plan_create_bugfix(tmp_project: Path, cli_runner: CliRunner) -> None:
    """plan create --type bugfix uses the bugfix template."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["plan", "create", "Fix Login", "-t", "bugfix"])
        assert result.exit_code == 0
        plans = list((tmp_project / "docs/ai/plans").glob("001-fix-login.md"))
        assert len(plans) == 1
    finally:
        os.chdir(orig_cwd)


def test_plan_create_refactor(tmp_project: Path, cli_runner: CliRunner) -> None:
    """plan create --type refactor uses the refactor template."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["plan", "create", "Clean Up DB Layer", "-t", "refactor"])
        assert result.exit_code == 0
        plans = list((tmp_project / "docs/ai/plans").glob("001-clean-up-db-layer.md"))
        assert len(plans) == 1
    finally:
        os.chdir(orig_cwd)


def _make_valid_plan(plans_dir: Path, name: str = "001-test-plan.md") -> Path:
    """Write a minimal but valid plan file for lint testing."""
    plan_file = plans_dir / name
    plan_file.write_text(
        "---\ntitle: Test Plan\nstatus: draft\n---\n\n"
        "## Metadata\n\n"
        "## Objective\n\nDo the thing.\n\n"
        "## File Impact Map\n\n"
        "| File | Action |\n|------|--------|\n| src/foo.py | Add |\n\n"
        "## Execution Steps\n\n"
        "- [ ] Step one\n"
        "- [ ] Step two\n\n"
        "## Tests\n\ntest_foo.py\n\n"
        "## Validation Commands\n\n```bash\npytest\n```\n\n"
        "## Rollback Plan\n\nRevert the commit.\n"
    )
    return plan_file


def test_plan_lint_valid(tmp_project: Path, cli_runner: CliRunner) -> None:
    """lint a properly structured plan -- should pass."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        plans_dir = tmp_project / "docs/ai/plans"
        _make_valid_plan(plans_dir)
        result = cli_runner.invoke(app, ["plan", "lint", "-p", "001"])
        assert result.exit_code == 0
        assert "PASS" in result.output
    finally:
        os.chdir(orig_cwd)


def test_plan_lint_missing_sections(tmp_project: Path, cli_runner: CliRunner) -> None:
    """lint a plan missing required sections -- should fail."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        plans_dir = tmp_project / "docs/ai/plans"
        bad_plan = plans_dir / "001-bad-plan.md"
        bad_plan.write_text("# Bad Plan\n\nThis plan has no required sections.\n")
        result = cli_runner.invoke(app, ["plan", "lint", "-p", "001"])
        assert result.exit_code == 1
        assert "FAIL" in result.output
    finally:
        os.chdir(orig_cwd)


def test_plan_status_empty(tmp_project: Path, cli_runner: CliRunner) -> None:
    """status with no plans shows a warning message."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["plan", "status"])
        assert result.exit_code == 0
        assert "No plan files found" in result.output
    finally:
        os.chdir(orig_cwd)


def test_plan_status_with_plans(tmp_project: Path, cli_runner: CliRunner) -> None:
    """status with plans shows the correct status and progress."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        plans_dir = tmp_project / "docs/ai/plans"

        draft = plans_dir / "001-draft-plan.md"
        draft.write_text("# Draft\n\nNo checkboxes here.\n")

        in_progress = plans_dir / "002-in-progress.md"
        in_progress.write_text("# In Progress\n\n- [x] Done step\n- [ ] Pending step\n")

        complete = plans_dir / "003-done-plan.md"
        complete.write_text("# Complete\n\n- [x] Step A\n- [x] Step B\n")

        result = cli_runner.invoke(app, ["plan", "status"])
        assert result.exit_code == 0
        assert "Draft" in result.output or "draft" in result.output.lower()
        assert "In Progress" in result.output or "in progress" in result.output.lower()
        assert "Complete" in result.output or "complete" in result.output.lower()
    finally:
        os.chdir(orig_cwd)
