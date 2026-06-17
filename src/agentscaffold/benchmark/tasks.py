"""Curated benchmark task definitions and deterministic graders."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskKind(str, Enum):
    """Supported benchmark task families."""

    TESTS_GO_GREEN = "tests_go_green"
    PLANTED_DEFECT = "planted_defect"


@dataclass(frozen=True)
class BenchmarkTask:
    """A benchmark task with deterministic grading metadata."""

    task_id: str
    title: str
    kind: TaskKind
    prompt: str
    repo_path: str
    validation_command: str | None = None
    expected_findings: tuple[str, ...] = ()
    expected_categories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportedFinding:
    """A finding emitted by an agent during a review-efficacy task."""

    finding_id: str
    category: str
    text: str = ""


@dataclass(frozen=True)
class GradingInput:
    """Deterministic evidence available to a task grader."""

    validation_exit_code: int | None = None
    reported_findings: tuple[ReportedFinding, ...] = ()
    transcript_text: str = ""


@dataclass(frozen=True)
class GradeResult:
    """Outcome of deterministic task grading."""

    passed: bool
    defect_caught: bool | None = None
    matched_findings: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""


BUILTIN_TASKS: tuple[BenchmarkTask, ...] = (
    BenchmarkTask(
        task_id="sample-router-tests",
        title="Fix sample router tests",
        kind=TaskKind.TESTS_GO_GREEN,
        prompt="Make the sample router tests pass without changing their intent.",
        repo_path="tests/fixtures/sample_repo",
        validation_command="pytest -q tests/test_router.py",
        tags=("tests-go-green", "graph-optional"),
    ),
    BenchmarkTask(
        task_id="sample-router-planted-defect",
        title="Find planted router normalization defect",
        kind=TaskKind.PLANTED_DEFECT,
        prompt=(
            "Review the sample router for symbol normalization defects and report "
            "the issue with evidence."
        ),
        repo_path="tests/fixtures/sample_repo",
        expected_findings=("router-normalization-case-loss",),
        expected_categories=("normalization",),
        tags=("review-efficacy", "planted-defect"),
    ),
)


def list_tasks() -> tuple[BenchmarkTask, ...]:
    """Return built-in benchmark tasks."""

    return BUILTIN_TASKS


def select_tasks(slice_spec: str) -> tuple[BenchmarkTask, ...]:
    """Return built-in tasks selected by Python slice syntax."""

    tasks = list(BUILTIN_TASKS)
    if not slice_spec:
        return tuple(tasks)
    try:
        parts = [int(part) if part else None for part in slice_spec.split(":")]
        if len(parts) > 3:
            raise ValueError
        return tuple(tasks[slice(*parts)])
    except ValueError as exc:
        raise ValueError(f"Invalid task slice '{slice_spec}'. Use Python slice syntax.") from exc


def grade_task(task: BenchmarkTask, evidence: GradingInput) -> GradeResult:
    """Grade a benchmark task from deterministic evidence."""

    if task.kind == TaskKind.TESTS_GO_GREEN:
        return _grade_tests_go_green(evidence)
    if task.kind == TaskKind.PLANTED_DEFECT:
        return _grade_planted_defect(task, evidence)
    raise ValueError(f"Unsupported benchmark task kind: {task.kind}")


def _grade_tests_go_green(evidence: GradingInput) -> GradeResult:
    if evidence.validation_exit_code == 0:
        return GradeResult(passed=True, reason="validation command passed")
    return GradeResult(
        passed=False,
        reason=(
            "validation command did not pass"
            if evidence.validation_exit_code is not None
            else "validation command was not run"
        ),
    )


def _grade_planted_defect(task: BenchmarkTask, evidence: GradingInput) -> GradeResult:
    expected_ids = set(task.expected_findings)
    expected_categories = set(task.expected_categories)
    matched: set[str] = set()

    for finding in evidence.reported_findings:
        if finding.finding_id in expected_ids:
            matched.add(finding.finding_id)
        if finding.category in expected_categories:
            matched.add(finding.category)

    lowered_transcript = evidence.transcript_text.lower()
    for expected in expected_ids | expected_categories:
        if expected.lower() in lowered_transcript:
            matched.add(expected)

    caught = bool(matched)
    return GradeResult(
        passed=caught,
        defect_caught=caught,
        matched_findings=tuple(sorted(matched)),
        reason="planted defect caught" if caught else "expected planted defect was not reported",
    )
