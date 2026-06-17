"""Benchmark result and metric schemas."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Per-arm live benchmark metrics."""

    cost_usd: float | None = None
    api_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    wall_time_seconds: float | None = None
    scaffold_tool_calls: int = 0
    pricing_source: str = "unknown"

    @property
    def total_tokens(self) -> int | None:
        """Return total tokens when both input and output counts are known."""

        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


def metrics_from_trajectory(
    trajectory: dict[str, Any],
    *,
    pricing_source: str,
    scaffold_tool_calls: int = 0,
    wall_time_seconds: float | None = None,
) -> BenchmarkMetrics:
    """Extract benchmark metrics from a mini-swe-agent-style trajectory."""

    info = trajectory.get("info", {})
    model_stats = info.get("model_stats", {})
    return BenchmarkMetrics(
        cost_usd=_optional_float(
            model_stats.get("instance_cost", model_stats.get("cost", trajectory.get("cost")))
        ),
        api_calls=int(model_stats.get("api_calls", trajectory.get("n_calls", 0)) or 0),
        input_tokens=_optional_int(
            model_stats.get("input_tokens", model_stats.get("prompt_tokens"))
        ),
        output_tokens=_optional_int(
            model_stats.get("output_tokens", model_stats.get("completion_tokens"))
        ),
        wall_time_seconds=wall_time_seconds,
        scaffold_tool_calls=scaffold_tool_calls,
        pricing_source=pricing_source,
    )


@dataclass(frozen=True)
class ArmResult:
    """Result for one arm on one task/seed."""

    task_id: str
    arm: str
    seed: int
    passed: bool
    defect_caught: bool | None = None
    metrics: BenchmarkMetrics = field(default_factory=BenchmarkMetrics)
    exit_status: str = "completed"
    error: str | None = None


@dataclass(frozen=True)
class BenchmarkSummary:
    """Serialized benchmark run summary."""

    run_id: str
    model: str
    model_id: str
    pricing_source: str
    results: tuple[ArmResult, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkSummary:
        """Deserialize from a JSON-compatible dictionary."""

        results = tuple(
            ArmResult(
                task_id=item["task_id"],
                arm=item["arm"],
                seed=int(item.get("seed", 1)),
                passed=bool(item.get("passed", False)),
                defect_caught=item.get("defect_caught"),
                metrics=BenchmarkMetrics(**item.get("metrics", {})),
                exit_status=item.get("exit_status", "completed"),
                error=item.get("error"),
            )
            for item in data.get("results", [])
        )
        return cls(
            run_id=data["run_id"],
            model=data["model"],
            model_id=data["model_id"],
            pricing_source=data.get("pricing_source", "unknown"),
            results=results,
        )


@dataclass(frozen=True)
class ArmAggregate:
    """Aggregated metrics for one benchmark arm."""

    arm: str
    total_runs: int
    pass_rate: float
    defect_caught_rate: float | None
    total_cost_usd: float | None
    avg_cost_usd: float | None
    total_api_calls: int
    avg_api_calls: float
    avg_wall_time_seconds: float | None
    scaffold_tool_calls: int


def aggregate_arm(arm: str, results: tuple[ArmResult, ...]) -> ArmAggregate:
    """Aggregate result rows for a single arm."""

    total = len(results)
    passed = sum(1 for item in results if item.passed)
    defect_rows = [item for item in results if item.defect_caught is not None]
    defect_caught = sum(1 for item in defect_rows if item.defect_caught)
    known_costs = [item.metrics.cost_usd for item in results if item.metrics.cost_usd is not None]
    known_wall_times = [
        item.metrics.wall_time_seconds
        for item in results
        if item.metrics.wall_time_seconds is not None
    ]
    total_calls = sum(item.metrics.api_calls for item in results)
    total_tool_calls = sum(item.metrics.scaffold_tool_calls for item in results)
    total_cost = sum(known_costs) if len(known_costs) == total and total > 0 else None
    return ArmAggregate(
        arm=arm,
        total_runs=total,
        pass_rate=passed / total if total else 0.0,
        defect_caught_rate=(defect_caught / len(defect_rows)) if defect_rows else None,
        total_cost_usd=total_cost,
        avg_cost_usd=(total_cost / total) if total_cost is not None and total else None,
        total_api_calls=total_calls,
        avg_api_calls=total_calls / total if total else 0.0,
        avg_wall_time_seconds=(
            sum(known_wall_times) / len(known_wall_times) if known_wall_times else None
        ),
        scaffold_tool_calls=total_tool_calls,
    )


def write_summary(summary: BenchmarkSummary, path: Path) -> None:
    """Write a benchmark summary JSON file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), indent=2))


def load_summary(path: Path) -> BenchmarkSummary:
    """Load a benchmark summary from a file or result directory."""

    summary_path = path / "summary.json" if path.is_dir() else path
    if not summary_path.exists():
        raise FileNotFoundError(f"Benchmark summary not found: {summary_path}")
    return BenchmarkSummary.from_dict(json.loads(summary_path.read_text()))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
