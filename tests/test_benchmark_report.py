"""Offline tests for benchmark result reporting."""

from __future__ import annotations

from agentscaffold.benchmark.metrics import (
    ArmResult,
    BenchmarkMetrics,
    BenchmarkSummary,
    load_summary,
    write_summary,
)
from agentscaffold.benchmark.report import compare_summary, render_markdown
from agentscaffold.cli import app


def _summary() -> BenchmarkSummary:
    return BenchmarkSummary(
        run_id="run-1",
        model="claude-haiku",
        model_id="openrouter/anthropic/claude-3.5-haiku",
        pricing_source="litellm",
        results=(
            ArmResult(
                task_id="sample-router-tests",
                arm="baseline",
                seed=1,
                passed=True,
                metrics=BenchmarkMetrics(cost_usd=0.20, api_calls=4, wall_time_seconds=10.0),
            ),
            ArmResult(
                task_id="sample-router-tests",
                arm="equipped",
                seed=1,
                passed=True,
                metrics=BenchmarkMetrics(
                    cost_usd=0.15,
                    api_calls=3,
                    wall_time_seconds=8.0,
                    scaffold_tool_calls=2,
                ),
            ),
            ArmResult(
                task_id="sample-router-planted-defect",
                arm="baseline",
                seed=1,
                passed=False,
                defect_caught=False,
                metrics=BenchmarkMetrics(cost_usd=0.10, api_calls=2),
            ),
            ArmResult(
                task_id="sample-router-planted-defect",
                arm="equipped",
                seed=1,
                passed=True,
                defect_caught=True,
                metrics=BenchmarkMetrics(cost_usd=0.12, api_calls=2, scaffold_tool_calls=1),
            ),
        ),
    )


def test_summary_round_trip_and_compare(tmp_path) -> None:
    path = tmp_path / "summary.json"
    write_summary(_summary(), path)

    comparison = compare_summary(load_summary(path))
    by_arm = comparison.by_arm()

    assert by_arm["baseline"].pass_rate == 0.5
    assert by_arm["equipped"].pass_rate == 1.0
    assert by_arm["equipped"].defect_caught_rate == 1.0
    assert by_arm["equipped"].scaffold_tool_calls == 3


def test_markdown_report_includes_cost_and_delta() -> None:
    markdown = render_markdown(compare_summary(_summary()))

    assert "# AgentScaffold Benchmark Report" in markdown
    assert "| equipped | 2 | 100.0%" in markdown
    assert "Cost delta" in markdown


def test_markdown_report_includes_seed_variance_for_multiple_seeds() -> None:
    summary = BenchmarkSummary(
        run_id="run-variance",
        model="claude-haiku",
        model_id="openrouter/anthropic/claude-3.5-haiku",
        pricing_source="litellm",
        results=(
            ArmResult(task_id="a", arm="baseline", seed=1, passed=True),
            ArmResult(task_id="b", arm="baseline", seed=1, passed=False),
            ArmResult(task_id="a", arm="baseline", seed=2, passed=True),
            ArmResult(task_id="b", arm="baseline", seed=2, passed=True),
        ),
    )

    markdown = render_markdown(compare_summary(summary))

    assert "## Seed Variance" in markdown
    assert "`baseline` pass-rate range: `50.0%` to `100.0%`" in markdown


def test_benchmark_compare_and_report_cli(tmp_path, cli_runner) -> None:
    path = tmp_path / "result"
    write_summary(_summary(), path / "summary.json")

    compare = cli_runner.invoke(app, ["benchmark", "compare", str(path)])
    report = cli_runner.invoke(app, ["benchmark", "report", str(path)])

    assert compare.exit_code == 0, compare.output
    assert "equipped" in compare.output
    assert "100.0%" in compare.output
    assert report.exit_code == 0, report.output
    assert "AgentScaffold Benchmark Report" in report.output
