"""Offline CLI tests for ``scaffold benchmark``."""

from __future__ import annotations

from agentscaffold.benchmark.doctor import CheckResult, CheckStatus, DoctorReport
from agentscaffold.benchmark.models import get_model
from agentscaffold.benchmark.runner import BenchmarkRunRequest, validate_live_request
from agentscaffold.cli import app


def test_benchmark_models_lists_builtin_models(cli_runner) -> None:
    result = cli_runner.invoke(app, ["benchmark", "models"])

    assert result.exit_code == 0
    assert "claude-haiku" in result.output
    assert "openrouter" in result.output
    assert "litellm" in result.output


def test_benchmark_dry_run_does_not_require_live_key_or_dependencies(cli_runner) -> None:
    result = cli_runner.invoke(app, ["benchmark", "run", "--dry-run", "--model", "claude-haiku"])

    assert result.exit_code == 0, result.output
    assert "Benchmark dry-run only" in result.output
    assert "Live calls: no" in result.output


def test_benchmark_live_run_requires_confirmation_and_cost_cap() -> None:
    request = BenchmarkRunRequest(
        model=get_model("claude-haiku"),
        task_slice="0:1",
        max_cost_usd=None,
        workers=1,
        dry_run=False,
        confirm_live=False,
    )
    report = DoctorReport(
        checks=(
            CheckResult(
                name="docker",
                status=CheckStatus.PASS,
                message="ok",
            ),
        )
    )

    errors = validate_live_request(request, report)

    assert "Live benchmark runs require --confirm-live." in errors
    assert "Live benchmark runs require --max-cost-usd." in errors


def test_benchmark_rejects_unknown_model(cli_runner) -> None:
    result = cli_runner.invoke(app, ["benchmark", "run", "--dry-run", "--model", "missing"])

    assert result.exit_code == 1
    assert "Unknown benchmark model" in result.output
