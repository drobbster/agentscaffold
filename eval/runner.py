"""Core evaluation utilities and result types."""

from __future__ import annotations

import functools
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalResult:
    """Result from a single evaluation scenario."""

    scenario: str
    passed: bool
    score: float  # 0.0-1.0
    expected: str
    actual: str
    observations: list[str] = field(default_factory=list)
    category: str = "unknown"
    elapsed_ms: float = 0.0


@dataclass
class BenchmarkResult:
    """Result from an A/B benchmark comparison."""

    scenario_name: str
    with_graph_count: int
    without_graph_count: int
    delta: int
    observations: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


@dataclass
class EfficiencyResult:
    """Result from an efficiency comparison between graph and baseline agent."""

    task: str
    description: str
    # Baseline agent metrics (what the agent would do without agentscaffold)
    baseline_tool_calls: int
    baseline_tokens: int
    # Graph-enriched agent metrics
    graph_tool_calls: int
    graph_tokens: int
    # Derived
    token_reduction_pct: float = 0.0
    call_reduction_pct: float = 0.0
    compression_ratio: float = 0.0
    observations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.baseline_tokens > 0:
            self.token_reduction_pct = round(
                (1 - self.graph_tokens / self.baseline_tokens) * 100, 1
            )
            self.compression_ratio = round(self.baseline_tokens / max(self.graph_tokens, 1), 1)
        if self.baseline_tool_calls > 0:
            self.call_reduction_pct = round(
                (1 - self.graph_tool_calls / self.baseline_tool_calls) * 100, 1
            )


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4 (standard GPT approximation for code)."""
    return max(len(text) // 4, 1)


# Global results collector for the report generator
_results: list[EvalResult] = []
_benchmarks: list[BenchmarkResult] = []
_efficiency: list[EfficiencyResult] = []


def collect_result(result: EvalResult) -> None:
    """Add a result to the global collector."""
    _results.append(result)


def collect_benchmark(result: BenchmarkResult) -> None:
    """Add a benchmark result to the global collector."""
    _benchmarks.append(result)


def collect_efficiency(result: EfficiencyResult) -> None:
    """Add an efficiency result to the global collector."""
    _efficiency.append(result)


def get_all_results() -> list[EvalResult]:
    return list(_results)


def get_all_benchmarks() -> list[BenchmarkResult]:
    return list(_benchmarks)


def get_all_efficiency() -> list[EfficiencyResult]:
    return list(_efficiency)


def clear_results() -> None:
    _results.clear()
    _benchmarks.clear()
    _efficiency.clear()


def timed(func):
    """Decorator that times function execution and stores elapsed_ms."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        t0 = time.monotonic()
        result = func(*args, **kwargs)
        elapsed = (time.monotonic() - t0) * 1000
        # If the function returns an EvalResult or BenchmarkResult, set elapsed_ms
        if isinstance(result, EvalResult | BenchmarkResult):
            result.elapsed_ms = round(elapsed, 1)
        return result

    return wrapper


# Jinja2 residue patterns that should never appear in rendered output
_JINJA_RESIDUE = re.compile(r"\{\{|\}\}|\{%|%\}")
_TRACEBACK_PATTERN = re.compile(r"Traceback \(most recent call last\)")
_NONE_LITERAL = re.compile(r"\bNone\b")


def check_template_wellformedness(rendered: str) -> list[str]:
    """Check rendered template output for common issues.

    Returns list of issues found (empty = clean).
    """
    issues = []

    if _JINJA_RESIDUE.search(rendered):
        matches = _JINJA_RESIDUE.findall(rendered)
        issues.append(f"Jinja2 residue found: {matches[:3]}")

    if _TRACEBACK_PATTERN.search(rendered):
        issues.append("Python traceback detected in output")

    return issues
