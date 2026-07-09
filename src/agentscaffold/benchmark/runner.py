"""Run planning for AgentScaffold Benchmark."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentscaffold.benchmark.arms import BenchmarkArm, list_arms
from agentscaffold.benchmark.doctor import DoctorReport, run_doctor
from agentscaffold.benchmark.environment import TaskEnvironmentPlan, create_workspace_plan
from agentscaffold.benchmark.metrics import (
    ArmResult,
    BenchmarkMetrics,
    BenchmarkSummary,
    metrics_from_trajectory,
    write_summary,
)
from agentscaffold.benchmark.models import BenchmarkModel
from agentscaffold.benchmark.tasks import GradingInput, ReportedFinding, grade_task, select_tasks

BENCHMARK_ARMS = ("baseline", "equipped")


@dataclass(frozen=True)
class BenchmarkRunRequest:
    """User-selected benchmark run options."""

    model: BenchmarkModel
    task_slice: str
    max_cost_usd: float | None
    workers: int
    dry_run: bool
    confirm_live: bool
    seeds: int = 1

    @property
    def live_requested(self) -> bool:
        """Return whether this request would start live model calls."""

        return not self.dry_run


@dataclass(frozen=True)
class DryRunPlan:
    """Resolved execution plan for `scaffold benchmark run --dry-run`."""

    request: BenchmarkRunRequest
    doctor_report: DoctorReport
    arms: tuple[str, ...] = BENCHMARK_ARMS

    @property
    def will_start_live_calls(self) -> bool:
        """Dry-run plans never start live calls."""

        return False


def validate_live_request(request: BenchmarkRunRequest, report: DoctorReport) -> list[str]:
    """Return blocking validation errors for a live benchmark request."""

    errors: list[str] = []
    if request.live_requested and not request.confirm_live:
        errors.append("Live benchmark runs require --confirm-live.")
    if request.live_requested and request.max_cost_usd is None:
        errors.append("Live benchmark runs require --max-cost-usd.")
    if request.max_cost_usd is not None and request.max_cost_usd <= 0:
        errors.append("--max-cost-usd must be greater than 0.")
    if request.workers < 1:
        errors.append("--workers must be at least 1.")
    if request.seeds < 1:
        errors.append("--seeds must be at least 1.")
    if request.live_requested and not report.ok:
        failed = ", ".join(check.name for check in report.failed_required)
        errors.append(f"Required benchmark preflight checks failed: {failed}.")
    return errors


def build_dry_run_plan(request: BenchmarkRunRequest, report: DoctorReport) -> DryRunPlan:
    """Build a dry-run plan without starting containers or model calls."""

    return DryRunPlan(request=request, doctor_report=report)


@dataclass(frozen=True)
class ArmExecution:
    """Raw output returned by an arm executor."""

    validation_exit_code: int | None = None
    reported_findings: tuple[ReportedFinding, ...] = ()
    transcript_text: str = ""
    trajectory: dict[str, Any] | None = None
    executed_commands: tuple[str, ...] = ()
    wall_time_seconds: float | None = None
    exit_status: str = "completed"
    error: str | None = None


ArmExecutor = Callable[[BenchmarkRunRequest, TaskEnvironmentPlan], ArmExecution]


def run_benchmark(
    *,
    request: BenchmarkRunRequest,
    package_root: Path,
    output_dir: Path,
    executor: ArmExecutor | None = None,
    doctor_report: DoctorReport | None = None,
) -> BenchmarkSummary:
    """Run all selected tasks/arms/seeds and write a benchmark summary.

    Tests can inject a fake executor. The default executor intentionally fails
    closed until the mini-swe-agent Docker adapter is completed.
    """

    report = doctor_report or run_doctor(model=request.model, require_api_key=True)
    errors = validate_live_request(request, report)
    if errors:
        raise RuntimeError("; ".join(errors))

    resolved_executor = executor or _default_executor
    selected_tasks = select_tasks(request.task_slice)
    arms = list_arms()
    results: list[ArmResult] = []
    for task in selected_tasks:
        for arm in arms:
            for seed in range(1, request.seeds + 1):
                plan = create_workspace_plan(
                    task=task,
                    arm=arm,
                    seed=seed,
                    package_root=package_root,
                    output_root=output_dir / "workspaces",
                )
                results.append(_run_one(request, plan, resolved_executor))

    summary = BenchmarkSummary(
        run_id=f"{request.model.name}_{int(time.time())}",
        model=request.model.name,
        model_id=request.model.model_id,
        pricing_source=request.model.pricing_source,
        results=tuple(results),
    )
    write_summary(summary, output_dir / "summary.json")
    return summary


def _run_one(
    request: BenchmarkRunRequest,
    plan: TaskEnvironmentPlan,
    executor: ArmExecutor,
) -> ArmResult:
    execution = executor(request, plan)
    grade = grade_task(
        plan.task,
        GradingInput(
            validation_exit_code=execution.validation_exit_code,
            reported_findings=execution.reported_findings,
            transcript_text=execution.transcript_text,
        ),
    )
    metrics = _metrics_for_execution(request.model, plan.arm, execution)
    return ArmResult(
        task_id=plan.task.task_id,
        arm=plan.arm.name,
        seed=plan.seed,
        passed=grade.passed,
        defect_caught=grade.defect_caught,
        metrics=metrics,
        exit_status=execution.exit_status,
        error=execution.error,
    )


def _metrics_for_execution(
    model: BenchmarkModel,
    arm: BenchmarkArm,
    execution: ArmExecution,
) -> BenchmarkMetrics:
    scaffold_tool_calls = sum(
        1
        for command in execution.executed_commands
        if any(marker in command for marker in arm.tracked_tool_markers)
    )
    if execution.trajectory is None:
        return BenchmarkMetrics(
            scaffold_tool_calls=scaffold_tool_calls,
            wall_time_seconds=execution.wall_time_seconds,
            pricing_source=model.pricing_source,
        )
    return metrics_from_trajectory(
        execution.trajectory,
        pricing_source=model.pricing_source,
        scaffold_tool_calls=scaffold_tool_calls,
        wall_time_seconds=execution.wall_time_seconds,
    )


def _default_executor(
    request: BenchmarkRunRequest,
    plan: TaskEnvironmentPlan,
) -> ArmExecution:
    from agentscaffold.benchmark.adapter import MiniSweAgentExecutor

    return MiniSweAgentExecutor()(request, plan)
