"""Offline tests for benchmark environment and runner contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.benchmark.arms import count_scaffold_tool_calls, get_arm, list_arms
from agentscaffold.benchmark.doctor import CheckResult, CheckStatus, DoctorReport
from agentscaffold.benchmark.environment import create_workspace_plan, render_setup_script
from agentscaffold.benchmark.metrics import metrics_from_trajectory
from agentscaffold.benchmark.models import get_model
from agentscaffold.benchmark.runner import ArmExecution, BenchmarkRunRequest, run_benchmark
from agentscaffold.benchmark.tasks import ReportedFinding, select_tasks


def _package_root(tmp_path: Path) -> Path:
    root = tmp_path / "package"
    repo = root / "tests/fixtures/sample_repo"
    repo.mkdir(parents=True)
    (repo / "router.py").write_text("def normalize_symbol(symbol):\n    return symbol.upper()\n")
    (repo / ".scaffold").mkdir()
    (repo / ".scaffold" / "graph.duckdb").write_text("ignore")
    return root


def _request() -> BenchmarkRunRequest:
    return BenchmarkRunRequest(
        model=get_model("claude-haiku"),
        task_slice="0:2",
        max_cost_usd=1.0,
        workers=1,
        dry_run=False,
        confirm_live=True,
    )


def _passing_report() -> DoctorReport:
    return DoctorReport(
        checks=(
            CheckResult(name="docker", status=CheckStatus.PASS, message="ok"),
            CheckResult(name="api-key", status=CheckStatus.PASS, message="ok"),
            CheckResult(name="pricing", status=CheckStatus.PASS, message="ok"),
        )
    )


def test_builtin_arms_have_expected_tracking() -> None:
    arms = list_arms()

    assert [arm.name for arm in arms] == ["baseline", "equipped"]
    assert count_scaffold_tool_calls(("scaffold index", "pytest -q"), get_arm("equipped")) == 1
    assert count_scaffold_tool_calls(("scaffold index",), get_arm("baseline")) == 0


def test_create_workspace_plan_copies_repo_without_scaffold_cache(tmp_path) -> None:
    root = _package_root(tmp_path)
    task = select_tasks("0:1")[0]

    plan = create_workspace_plan(
        task=task,
        arm=get_arm("equipped"),
        seed=1,
        package_root=root,
        output_root=tmp_path / "out",
    )

    assert plan.workspace.is_dir()
    assert (plan.workspace / "router.py").is_file()
    assert not (plan.workspace / ".scaffold").exists()
    assert "scaffold index" in render_setup_script(plan)


def test_metrics_from_trajectory_extracts_model_stats() -> None:
    metrics = metrics_from_trajectory(
        {
            "info": {
                "model_stats": {
                    "instance_cost": 0.42,
                    "api_calls": 5,
                    "input_tokens": 100,
                    "output_tokens": 25,
                }
            }
        },
        pricing_source="litellm",
        scaffold_tool_calls=3,
        wall_time_seconds=1.5,
    )

    assert metrics.cost_usd == 0.42
    assert metrics.api_calls == 5
    assert metrics.total_tokens == 125
    assert metrics.scaffold_tool_calls == 3


def test_run_benchmark_uses_injected_executor_and_writes_summary(tmp_path) -> None:
    root = _package_root(tmp_path)

    def executor(_request: BenchmarkRunRequest, plan) -> ArmExecution:
        if plan.task.task_id.endswith("planted-defect"):
            return ArmExecution(
                reported_findings=(
                    ReportedFinding(
                        finding_id="router-normalization-case-loss",
                        category="normalization",
                    ),
                ),
                executed_commands=("scaffold graph search normalization",),
                trajectory={"info": {"model_stats": {"instance_cost": 0.01, "api_calls": 1}}},
            )
        return ArmExecution(
            validation_exit_code=0,
            executed_commands=("pytest -q",),
            trajectory={"info": {"model_stats": {"instance_cost": 0.02, "api_calls": 2}}},
        )

    summary = run_benchmark(
        request=_request(),
        package_root=root,
        output_dir=tmp_path / "results",
        executor=executor,
        doctor_report=_passing_report(),
    )

    assert len(summary.results) == 4
    assert (tmp_path / "results" / "summary.json").is_file()
    assert all(result.passed for result in summary.results)
    equipped_results = [result for result in summary.results if result.arm == "equipped"]
    assert sum(result.metrics.scaffold_tool_calls for result in equipped_results) == 1


def test_run_benchmark_fails_closed_without_live_executor(tmp_path) -> None:
    root = _package_root(tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        run_benchmark(
            request=_request(),
            package_root=root,
            output_dir=tmp_path / "results",
            doctor_report=_passing_report(),
        )
    message = str(exc_info.value)
    assert (
        "Missing optional live benchmark dependencies" in message
        or "Docker execution is not implemented yet" in message
    )
