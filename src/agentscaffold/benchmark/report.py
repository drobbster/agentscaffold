"""Comparison and report rendering for AgentScaffold Benchmark."""

from __future__ import annotations

from dataclasses import dataclass

from agentscaffold.benchmark.metrics import ArmAggregate, BenchmarkSummary, aggregate_arm


@dataclass(frozen=True)
class BenchmarkComparison:
    """Aggregated comparison for a saved benchmark summary."""

    summary: BenchmarkSummary
    aggregates: tuple[ArmAggregate, ...]

    def by_arm(self) -> dict[str, ArmAggregate]:
        """Return aggregates keyed by arm name."""

        return {item.arm: item for item in self.aggregates}


def compare_summary(summary: BenchmarkSummary) -> BenchmarkComparison:
    """Aggregate a benchmark summary by arm."""

    arms = sorted({item.arm for item in summary.results})
    aggregates = tuple(
        aggregate_arm(arm, tuple(item for item in summary.results if item.arm == arm))
        for arm in arms
    )
    return BenchmarkComparison(summary=summary, aggregates=aggregates)


def render_markdown(comparison: BenchmarkComparison) -> str:
    """Render a markdown report for a benchmark comparison."""

    summary = comparison.summary
    lines = [
        "# AgentScaffold Benchmark Report",
        "",
        f"- Run ID: `{summary.run_id}`",
        f"- Model: `{summary.model}` (`{summary.model_id}`)",
        f"- Pricing source: `{summary.pricing_source}`",
        "",
        "## Arm Summary",
        "",
        "| Arm | Runs | Pass Rate | Defect Caught Rate | Total Cost | "
        "API Calls | Scaffold Tool Calls | Avg Wall Time |",
        "|-----|------|-----------|--------------------|------------|"
        "-----------|---------------------|---------------|",
    ]
    for item in comparison.aggregates:
        lines.append(
            f"| {item.arm} | {item.total_runs} | {_pct(item.pass_rate)} | "
            f"{_optional_pct(item.defect_caught_rate)} | "
            f"{_optional_money(item.total_cost_usd)} | {item.total_api_calls} | "
            f"{item.scaffold_tool_calls} | "
            f"{_optional_seconds(item.avg_wall_time_seconds)} |"
        )
    lines.extend(_render_delta_lines(comparison))
    lines.extend(_render_seed_variance_lines(comparison))
    return "\n".join(lines) + "\n"


def _render_delta_lines(comparison: BenchmarkComparison) -> list[str]:
    by_arm = comparison.by_arm()
    baseline = by_arm.get("baseline")
    equipped = by_arm.get("equipped")
    if baseline is None or equipped is None:
        return []

    lines = ["", "## Equipped vs Baseline", ""]
    lines.append(f"- Pass-rate delta: `{_signed_pct(equipped.pass_rate - baseline.pass_rate)}`")
    if baseline.defect_caught_rate is not None and equipped.defect_caught_rate is not None:
        lines.append(
            "- Defect-caught delta: "
            f"`{_signed_pct(equipped.defect_caught_rate - baseline.defect_caught_rate)}`"
        )
    if baseline.total_cost_usd is not None and equipped.total_cost_usd is not None:
        lines.append(
            f"- Cost delta: `{_signed_money(equipped.total_cost_usd - baseline.total_cost_usd)}`"
        )
    call_delta = equipped.total_api_calls - baseline.total_api_calls
    lines.append(f"- API-call delta: `{call_delta:+d}`")
    return lines


def _render_seed_variance_lines(comparison: BenchmarkComparison) -> list[str]:
    seeds = sorted({item.seed for item in comparison.summary.results})
    if len(seeds) <= 1:
        return []

    lines = ["", "## Seed Variance", ""]
    for arm in sorted({item.arm for item in comparison.summary.results}):
        rates: list[float] = []
        for seed in seeds:
            rows = [
                item for item in comparison.summary.results if item.arm == arm and item.seed == seed
            ]
            if rows:
                rates.append(sum(1 for item in rows if item.passed) / len(rows))
        if rates:
            lines.append(f"- `{arm}` pass-rate range: `{_pct(min(rates))}` to `{_pct(max(rates))}`")
    return lines


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _signed_pct(value: float) -> str:
    return f"{value * 100:+.1f}pp"


def _optional_pct(value: float | None) -> str:
    return "n/a" if value is None else _pct(value)


def _optional_money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def _signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):.4f}"


def _optional_seconds(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f}s"
