"""Benchmark arm definitions."""

from __future__ import annotations

from dataclasses import dataclass

BENCHMARK_ARM_NAMES = ("baseline", "equipped")
SCAFFOLD_TOOL_MARKERS = (
    "scaffold ",
    "scaffold_",
    "mcp",
)


@dataclass(frozen=True)
class BenchmarkArm:
    """One side of a benchmark comparison."""

    name: str
    description: str
    scaffold_enabled: bool
    setup_commands: tuple[str, ...] = ()
    tracked_tool_markers: tuple[str, ...] = ()
    prompt_guidance: str = ""


BASELINE_ARM = BenchmarkArm(
    name="baseline",
    description="Plain shell/tools control arm with no AgentScaffold setup.",
    scaffold_enabled=False,
    prompt_guidance=(
        "Use normal repository inspection and editing tools. Do not use AgentScaffold "
        "commands or MCP tools."
    ),
)

EQUIPPED_ARM = BenchmarkArm(
    name="equipped",
    description="AgentScaffold-equipped arm with project rules, index, and MCP tooling.",
    scaffold_enabled=True,
    setup_commands=(
        "scaffold init --non-interactive",
        "scaffold index",
    ),
    tracked_tool_markers=SCAFFOLD_TOOL_MARKERS,
    prompt_guidance=(
        "Use AgentScaffold guidance and graph/MCP tools before broad file reads. "
        "Prefer targeted graph-backed orientation, impact analysis, and review evidence."
    ),
)

BUILTIN_ARMS: dict[str, BenchmarkArm] = {
    BASELINE_ARM.name: BASELINE_ARM,
    EQUIPPED_ARM.name: EQUIPPED_ARM,
}


def get_arm(name: str) -> BenchmarkArm:
    """Return a built-in arm definition."""

    try:
        return BUILTIN_ARMS[name]
    except KeyError as exc:
        available = ", ".join(sorted(BUILTIN_ARMS))
        raise ValueError(f"Unknown benchmark arm '{name}'. Available arms: {available}") from exc


def list_arms() -> tuple[BenchmarkArm, ...]:
    """Return built-in benchmark arms in stable comparison order."""

    return (BASELINE_ARM, EQUIPPED_ARM)


def count_scaffold_tool_calls(commands: tuple[str, ...], arm: BenchmarkArm) -> int:
    """Count AgentScaffold-related tool calls in executed command text."""

    if not arm.tracked_tool_markers:
        return 0
    return sum(
        1 for command in commands if any(marker in command for marker in arm.tracked_tool_markers)
    )
