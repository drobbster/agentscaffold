"""Offline tests for benchmark task grading."""

from __future__ import annotations

import pytest

from agentscaffold.benchmark.tasks import (
    GradingInput,
    ReportedFinding,
    grade_task,
    select_tasks,
)


def test_tests_go_green_task_passes_on_zero_exit() -> None:
    task = select_tasks("0:1")[0]

    result = grade_task(task, GradingInput(validation_exit_code=0))

    assert result.passed is True
    assert result.reason == "validation command passed"


def test_planted_defect_task_matches_finding_id() -> None:
    task = select_tasks("1:2")[0]

    result = grade_task(
        task,
        GradingInput(
            reported_findings=(
                ReportedFinding(
                    finding_id="router-normalization-case-loss",
                    category="normalization",
                ),
            )
        ),
    )

    assert result.passed is True
    assert result.defect_caught is True
    assert "router-normalization-case-loss" in result.matched_findings


def test_invalid_task_slice_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="Invalid task slice"):
        select_tasks("bad")
