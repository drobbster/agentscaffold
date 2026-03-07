"""Metrics engine for replay-based tool adoption."""

from __future__ import annotations

from dataclasses import dataclass, field

from eval.replay.parser import ReplayTurn

_VALID_FALLBACK_REASONS = {
    "tool_error",
    "tool_timeout",
    "index_unavailable",
    "index_stale",
    "insufficient_output",
}

_DIRECT_READ_TOOLS = {"readfile", "read_file", "rg", "grep", "glob", "semanticsearch"}


@dataclass
class ReplayMetrics:
    """Computed replay metrics for one suite/file."""

    suite: str
    total_turns: int
    intent_eligible_turns: int
    tool_first_matches: int
    bypass_count: int
    fallback_total: int
    fallback_valid: int
    quality_pairs: int
    quality_noninferior: int
    notes: list[str] = field(default_factory=list)

    @property
    def tool_first_adherence_pct(self) -> float:
        if self.intent_eligible_turns == 0:
            return 0.0
        return round(self.tool_first_matches / self.intent_eligible_turns * 100, 1)

    @property
    def bypass_rate_pct(self) -> float:
        if self.intent_eligible_turns == 0:
            return 0.0
        return round(self.bypass_count / self.intent_eligible_turns * 100, 1)

    @property
    def fallback_validity_pct(self) -> float:
        if self.fallback_total == 0:
            return 100.0
        return round(self.fallback_valid / self.fallback_total * 100, 1)

    @property
    def quality_noninferior_pct(self) -> float:
        if self.quality_pairs == 0:
            return 100.0
        return round(self.quality_noninferior / self.quality_pairs * 100, 1)


def compute_replay_metrics(suite: str, turns: list[ReplayTurn]) -> ReplayMetrics:
    """Compute replay metrics from normalized replay turns."""
    from agentscaffold.mcp.server import route_tool_from_prompt

    intent_eligible = 0
    tool_first_matches = 0
    bypass = 0
    fallback_total = 0
    fallback_valid = 0
    quality_pairs = 0
    quality_noninferior = 0
    notes: list[str] = []

    for turn in turns:
        expected = route_tool_from_prompt(turn.user_text)
        first_tool = turn.tool_calls[0] if turn.tool_calls else None
        first_tool_norm = first_tool.lower() if isinstance(first_tool, str) else None

        if expected is not None:
            intent_eligible += 1
            if first_tool == expected:
                tool_first_matches += 1
            else:
                used_direct = first_tool_norm in _DIRECT_READ_TOOLS if first_tool_norm else False
                if used_direct or first_tool is None:
                    bypass += 1
                    notes.append(
                        "Turn "
                        f"{turn.turn_id}: expected {expected}, "
                        f"first tool {first_tool or 'none'}"
                    )

        if turn.fallback_reason:
            fallback_total += 1
            if turn.fallback_reason in _VALID_FALLBACK_REASONS:
                fallback_valid += 1
            else:
                notes.append(f"Turn {turn.turn_id}: invalid fallback reason {turn.fallback_reason}")

        if turn.baseline_ok is not None and turn.mcp_ok is not None:
            quality_pairs += 1
            if (turn.baseline_ok is False) or (turn.mcp_ok is True):
                quality_noninferior += 1

    return ReplayMetrics(
        suite=suite,
        total_turns=len(turns),
        intent_eligible_turns=intent_eligible,
        tool_first_matches=tool_first_matches,
        bypass_count=bypass,
        fallback_total=fallback_total,
        fallback_valid=fallback_valid,
        quality_pairs=quality_pairs,
        quality_noninferior=quality_noninferior,
        notes=notes[:20],
    )
