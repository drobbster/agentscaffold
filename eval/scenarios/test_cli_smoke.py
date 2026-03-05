"""CLI smoke tests: key scaffold commands via CliRunner."""

from __future__ import annotations

import os
import shutil

import pytest
from typer.testing import CliRunner

from eval.conftest import SIM_PROJECT
from eval.runner import EvalResult, collect_result

runner = CliRunner()


@pytest.fixture()
def cli_sim(tmp_path):
    """Copy sim project and return its path."""
    dest = tmp_path / "sim"
    shutil.copytree(SIM_PROJECT, dest)
    return dest


class TestIndexCommand:
    """Scenario: scaffold index on the simulation project."""

    def test_index_runs(self, cli_sim):
        from agentscaffold.cli import app

        cwd = os.getcwd()
        try:
            os.chdir(cli_sim)
            result = runner.invoke(app, ["index"])
        finally:
            os.chdir(cwd)

        passed = result.exit_code == 0

        eval_result = EvalResult(
            scenario="cli_index",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Exit code 0",
            actual=f"Exit code: {result.exit_code}",
            observations=[result.output[:200] if result.output else "no output"],
            category="cli",
        )
        collect_result(eval_result)
        assert passed, f"scaffold index failed: {result.output}"


class TestSearchCommand:
    """Scenario: scaffold graph search after indexing."""

    def test_search_runs(self, cli_sim):
        from agentscaffold.cli import app

        cwd = os.getcwd()
        try:
            os.chdir(cli_sim)
            runner.invoke(app, ["index"])
            result = runner.invoke(app, ["graph", "search", "DataRouter"])
        finally:
            os.chdir(cwd)

        passed = result.exit_code == 0

        eval_result = EvalResult(
            scenario="cli_search",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Exit code 0",
            actual=f"Exit code: {result.exit_code}",
            observations=[result.output[:200] if result.output else "no output"],
            category="cli",
        )
        collect_result(eval_result)
        assert passed, f"scaffold graph search failed: {result.output}"


class TestReviewCommand:
    """Scenario: scaffold review brief after indexing."""

    def test_review_brief_runs(self, cli_sim):
        from agentscaffold.cli import app

        cwd = os.getcwd()
        try:
            os.chdir(cli_sim)
            runner.invoke(app, ["index"])
            result = runner.invoke(app, ["review", "brief", "42"])
        finally:
            os.chdir(cwd)

        passed = result.exit_code == 0

        eval_result = EvalResult(
            scenario="cli_review_brief",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Exit code 0",
            actual=f"Exit code: {result.exit_code}",
            observations=[result.output[:200] if result.output else "no output"],
            category="cli",
        )
        collect_result(eval_result)
        assert passed, f"scaffold review brief failed: {result.output}"


class TestSessionCommand:
    """Scenario: scaffold session start/list/end cycle."""

    def test_session_lifecycle(self, cli_sim):
        from agentscaffold.cli import app

        cwd = os.getcwd()
        try:
            os.chdir(cli_sim)
            runner.invoke(app, ["index"])

            r1 = runner.invoke(app, ["session", "start", "--plan", "42", "--summary", "test"])
            r2 = runner.invoke(app, ["session", "list"])

            passed = r1.exit_code == 0 and r2.exit_code == 0
        finally:
            os.chdir(cwd)

        eval_result = EvalResult(
            scenario="cli_session_lifecycle",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="session start and list succeed",
            actual=f"start: {r1.exit_code}, list: {r2.exit_code}",
            observations=[r1.output[:100] if r1.output else "no output"],
            category="cli",
        )
        collect_result(eval_result)
        assert passed


class TestCommunitiesCommand:
    """Scenario: scaffold graph communities."""

    def test_communities_runs(self, cli_sim):
        from agentscaffold.cli import app

        cwd = os.getcwd()
        try:
            os.chdir(cli_sim)
            runner.invoke(app, ["index"])
            result = runner.invoke(app, ["graph", "communities"])
        finally:
            os.chdir(cwd)

        passed = result.exit_code == 0

        eval_result = EvalResult(
            scenario="cli_communities",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Exit code 0",
            actual=f"Exit code: {result.exit_code}",
            observations=[result.output[:200] if result.output else "no output"],
            category="cli",
        )
        collect_result(eval_result)
        assert passed


class TestReviewTemplate:
    """Scenario: scaffold review challenges --template produces well-formed output."""

    def test_review_template_wellformed(self, cli_sim):
        from agentscaffold.cli import app
        from eval.runner import check_template_wellformedness

        cwd = os.getcwd()
        try:
            os.chdir(cli_sim)
            runner.invoke(app, ["index"])
            result = runner.invoke(app, ["review", "challenges", "42", "--template"])
        finally:
            os.chdir(cwd)

        passed = result.exit_code == 0
        issues = []
        if passed and result.output:
            issues = check_template_wellformedness(result.output)

        eval_result = EvalResult(
            scenario="cli_review_template_wellformed",
            passed=passed and len(issues) == 0,
            score=1.0 if passed and not issues else 0.5,
            expected="Well-formed template output (no Jinja2 residue)",
            actual=f"Exit: {result.exit_code}, issues: {issues}",
            category="cli",
        )
        collect_result(eval_result)
        assert passed
