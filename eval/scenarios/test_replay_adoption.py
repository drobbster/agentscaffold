"""Replay-based adoption scenarios using conversation/tool-call traces."""

from __future__ import annotations

from pathlib import Path

from eval.replay.metrics import compute_replay_metrics
from eval.replay.parser import parse_replay_jsonl
from eval.runner import EvalResult, ReplayResult, collect_replay, collect_result


class TestReplayAdoption:
    """Validate parser + observed-behavior metrics from replay traces."""

    def test_replay_parser_handles_invalid_lines(self):
        trace_path = (
            Path(__file__).parent.parent / "replay" / "fixtures" / "mixed_behavior_trace.jsonl"
        )
        turns, warnings = parse_replay_jsonl(trace_path)

        # 10 valid JSON lines + 1 malformed line in fixture
        assert len(turns) == 10
        assert len(warnings) >= 1

        collect_result(
            EvalResult(
                scenario="replay_parser_robustness",
                passed=len(turns) == 10 and len(warnings) >= 1,
                score=1.0 if (len(turns) == 10 and len(warnings) >= 1) else 0.0,
                expected="10 valid turns parsed with warnings for malformed line(s)",
                actual=f"turns={len(turns)}, warnings={len(warnings)}",
                observations=warnings[:5],
                category="replay",
            )
        )

    def test_replay_metrics_report_behavioral_risks(self):
        trace_path = (
            Path(__file__).parent.parent / "replay" / "fixtures" / "mixed_behavior_trace.jsonl"
        )
        turns, warnings = parse_replay_jsonl(trace_path)
        metrics = compute_replay_metrics("mixed_behavior_trace", turns)

        collect_replay(
            ReplayResult(
                suite=metrics.suite,
                total_turns=metrics.total_turns,
                intent_eligible_turns=metrics.intent_eligible_turns,
                tool_first_adherence_pct=metrics.tool_first_adherence_pct,
                bypass_rate_pct=metrics.bypass_rate_pct,
                fallback_validity_pct=metrics.fallback_validity_pct,
                quality_noninferior_pct=metrics.quality_noninferior_pct,
                notes=warnings + metrics.notes,
            )
        )

        passed = (
            metrics.tool_first_adherence_pct >= 60
            and metrics.bypass_rate_pct <= 40
            and metrics.fallback_validity_pct >= 60
        )
        collect_result(
            EvalResult(
                scenario="replay_behavioral_metrics",
                passed=passed,
                score=(
                    metrics.tool_first_adherence_pct
                    + (100 - metrics.bypass_rate_pct)
                    + metrics.fallback_validity_pct
                )
                / 300,
                expected="Adherence >= 60%, bypass <= 40%, fallback validity >= 60%",
                actual=(
                    f"adherence={metrics.tool_first_adherence_pct}%, "
                    f"bypass={metrics.bypass_rate_pct}%, "
                    f"fallback_validity={metrics.fallback_validity_pct}%, "
                    f"quality_noninferior={metrics.quality_noninferior_pct}%"
                ),
                observations=metrics.notes[:10],
                category="replay",
            )
        )

        assert metrics.intent_eligible_turns > 0
