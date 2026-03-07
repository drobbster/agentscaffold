"""Report generator: aggregates evaluation results into a scored markdown report."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from eval.runner import (
    get_all_adoption,
    get_all_benchmarks,
    get_all_efficiency,
    get_all_replay,
    get_all_results,
)


def generate_report(output_path: Path | None = None) -> str:
    """Generate a markdown evaluation report from collected results."""
    results = get_all_results()
    benchmarks = get_all_benchmarks()
    efficiency = get_all_efficiency()
    adoption = get_all_adoption()
    replay = get_all_replay()

    if not results:
        return "# Evaluation Report\n\nNo results collected.\n"

    by_category = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    avg_score = sum(r.score for r in results) / total if total else 0.0
    total_time = sum(r.elapsed_ms for r in results)

    lines = [
        "# AgentScaffold Evaluation Report",
        "",
        f"**Generated**: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Scenarios | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Pass Rate | {passed / total * 100:.1f}% |",
        f"| Average Score | {avg_score:.2f} |",
        f"| Total Time | {total_time:.0f}ms |",
        "",
    ]

    category_order = [
        "lifecycle",
        "review",
        "edge_case",
        "mcp",
        "cli",
        "benchmark",
        "efficiency",
        "adoption",
        "replay",
        "readability",
        "conversation_replay",
        "unknown",
    ]

    for cat in category_order:
        cat_results = by_category.get(cat, [])
        if not cat_results:
            continue

        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_total = len(cat_results)
        cat_score = sum(r.score for r in cat_results) / cat_total

        lines.append(f"## {cat.replace('_', ' ').title()} ({cat_passed}/{cat_total})")
        lines.append("")
        lines.append(f"Average score: {cat_score:.2f}")
        lines.append("")
        lines.append("| Scenario | Passed | Score | Time (ms) |")
        lines.append("|----------|--------|-------|-----------|")

        for r in cat_results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"| {r.scenario} | {status} | {r.score:.2f} | {r.elapsed_ms:.0f} |")

        lines.append("")

        # Detail section for failures
        failures = [r for r in cat_results if not r.passed]
        if failures:
            lines.append("### Failures")
            lines.append("")
            for r in failures:
                lines.append(f"**{r.scenario}**")
                lines.append(f"- Expected: {r.expected}")
                lines.append(f"- Actual: {r.actual}")
                if r.observations:
                    for obs in r.observations:
                        lines.append(f"- {obs}")
                lines.append("")

    # Benchmarks section
    if benchmarks:
        lines.append("## A/B Benchmarks")
        lines.append("")
        lines.append("| Scenario | With Graph | Without Graph | Delta |")
        lines.append("|----------|-----------|--------------|-------|")

        for b in benchmarks:
            lines.append(
                f"| {b.scenario_name} | {b.with_graph_count} | "
                f"{b.without_graph_count} | {b.delta:+d} |"
            )

        lines.append("")

        for b in benchmarks:
            if b.observations:
                lines.append(f"**{b.scenario_name}**:")
                for obs in b.observations:
                    lines.append(f"- {obs}")
                lines.append("")

    # Efficiency section
    if efficiency:
        lines.append("## Efficiency Gains (Graph vs Baseline Agent)")
        lines.append("")
        lines.append(
            "Compares tokens consumed and tool calls required: an agent using "
            "agentscaffold's graph vs. a baseline agent that manually reads "
            "files, greps for symbols, and traces dependencies."
        )
        lines.append("")
        lines.append(
            "| Task | Baseline Tokens | Graph Tokens | Token Reduction | "
            "Baseline Calls | Graph Calls | Call Reduction | Compression |"
        )
        lines.append(
            "|------|----------------|-------------|----------------|"
            "---------------|------------|---------------|-------------|"
        )
        for e in efficiency:
            lines.append(
                f"| {e.task} | {e.baseline_tokens:,} | {e.graph_tokens:,} | "
                f"{e.token_reduction_pct:.0f}% | "
                f"{e.baseline_tool_calls} | {e.graph_tool_calls} | "
                f"{e.call_reduction_pct:.0f}% | {e.compression_ratio:.1f}x |"
            )
        lines.append("")

        # Aggregate summary
        total_baseline_tokens = sum(e.baseline_tokens for e in efficiency)
        total_graph_tokens = sum(e.graph_tokens for e in efficiency)
        total_baseline_calls = sum(e.baseline_tool_calls for e in efficiency)
        total_graph_calls = sum(e.graph_tool_calls for e in efficiency)
        avg_token_reduction = sum(e.token_reduction_pct for e in efficiency) / len(efficiency)
        avg_call_reduction = sum(e.call_reduction_pct for e in efficiency) / len(efficiency)
        overall_compression = total_baseline_tokens / max(total_graph_tokens, 1)

        lines.append("**Aggregate:**")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Avg Token Reduction | {avg_token_reduction:.0f}% |")
        lines.append(f"| Avg Call Reduction | {avg_call_reduction:.0f}% |")
        lines.append(f"| Overall Compression | {overall_compression:.1f}x |")
        lines.append(f"| Total Baseline Tokens | {total_baseline_tokens:,} |")
        lines.append(f"| Total Graph Tokens | {total_graph_tokens:,} |")
        lines.append(f"| Total Baseline Calls | {total_baseline_calls} |")
        lines.append(f"| Total Graph Calls | {total_graph_calls} |")
        lines.append("")

        for e in efficiency:
            if e.observations:
                lines.append(f"**{e.task}** -- {e.description}:")
                for obs in e.observations:
                    lines.append(f"- {obs}")
                lines.append("")

    # Adoption section (behavioral adherence proxy)
    if adoption:
        lines.append("## Tool-First Adoption (Behavioral Proxy)")
        lines.append("")
        lines.append(
            "Measures how often prompts map to `TOOL_INTENTS` using heuristic intent matching "
            "(normalization + synonyms). This remains a proxy for rule adherence; it is not a "
            "live-LLM compliance test."
        )
        lines.append("")
        lines.append("| Suite | Matched | Total | Adherence |")
        lines.append("|-------|---------|-------|-----------|")
        for a in adoption:
            lines.append(
                f"| {a.suite} | {a.matched_prompts} | {a.total_prompts} | {a.adherence_pct:.1f}% |"
            )
        lines.append("")

        # Risk-adjusted efficiency using adoption adherence
        if efficiency:
            avg_adherence = sum(a.adherence_pct for a in adoption) / len(adoption)
            conservative_adherence = min(a.adherence_pct for a in adoption)
            avg_token_reduction = sum(e.token_reduction_pct for e in efficiency) / len(efficiency)
            avg_call_reduction = sum(e.call_reduction_pct for e in efficiency) / len(efficiency)

            lines.append("### Adoption-Adjusted Efficiency")
            lines.append("")
            lines.append(
                "Adjusts efficiency gains by adherence rate to reduce optimism in headline numbers."
            )
            lines.append("")
            lines.append("| Metric | Raw | Adjusted (Avg Adherence) | Adjusted (Conservative) |")
            lines.append("|--------|-----|--------------------------|--------------------------|")
            lines.append(
                f"| Token Reduction | {avg_token_reduction:.1f}% | "
                f"{(avg_token_reduction * avg_adherence / 100):.1f}% | "
                f"{(avg_token_reduction * conservative_adherence / 100):.1f}% |"
            )
            lines.append(
                f"| Call Reduction | {avg_call_reduction:.1f}% | "
                f"{(avg_call_reduction * avg_adherence / 100):.1f}% | "
                f"{(avg_call_reduction * conservative_adherence / 100):.1f}% |"
            )
            lines.append("")

        for a in adoption:
            if a.notes:
                lines.append(f"**{a.suite} misses**:")
                for note in a.notes:
                    lines.append(f"- {note}")
                lines.append("")

    # Replay section (observed behavior)
    if replay:
        lines.append("## Replay Adoption (Observed Behavior)")
        lines.append("")
        lines.append(
            "Derived from replay traces containing user prompts and actual tool-call sequences. "
            "These metrics estimate real MCP-first adherence rather than phrase-only matching."
        )
        lines.append("")
        lines.append(
            "| Suite | Turns | Intent-Eligible | Tool-First Adherence | Bypass Rate | "
            "Fallback Validity | Quality Non-Inferior |"
        )
        lines.append(
            "|-------|-------|-----------------|----------------------|-------------|"
            "-------------------|----------------------|"
        )
        for r in replay:
            lines.append(
                f"| {r.suite} | {r.total_turns} | {r.intent_eligible_turns} | "
                f"{r.tool_first_adherence_pct:.1f}% | {r.bypass_rate_pct:.1f}% | "
                f"{r.fallback_validity_pct:.1f}% | {r.quality_noninferior_pct:.1f}% |"
            )
        lines.append("")

        if efficiency:
            avg_token_reduction = sum(e.token_reduction_pct for e in efficiency) / len(efficiency)
            avg_call_reduction = sum(e.call_reduction_pct for e in efficiency) / len(efficiency)
            avg_observed_adherence = sum(r.tool_first_adherence_pct for r in replay) / len(replay)
            avg_quality_noninferior = sum(r.quality_noninferior_pct for r in replay) / len(replay)

            behavioral_token = avg_token_reduction * avg_observed_adherence / 100
            behavioral_call = avg_call_reduction * avg_observed_adherence / 100
            quality_adjusted_token = behavioral_token * avg_quality_noninferior / 100
            quality_adjusted_call = behavioral_call * avg_quality_noninferior / 100

            lines.append("### Behavioral and Quality-Adjusted Efficiency")
            lines.append("")
            lines.append(
                "Uses replay-observed adherence to compute behavioral efficiency, then applies "
                "quality non-inferiority as a second-stage adjustment."
            )
            lines.append("")
            lines.append("| Metric View | Token Reduction | Call Reduction |")
            lines.append("|-------------|-----------------|----------------|")
            lines.append(
                f"| Capability (raw) | {avg_token_reduction:.1f}% | {avg_call_reduction:.1f}% |"
            )
            lines.append(
                "| Behavioral (replay-adjusted) | "
                f"{behavioral_token:.1f}% | {behavioral_call:.1f}% |"
            )
            lines.append(
                f"| Quality-adjusted behavioral | "
                f"{quality_adjusted_token:.1f}% | {quality_adjusted_call:.1f}% |"
            )
            lines.append("")

        for r in replay:
            if r.notes:
                lines.append(f"**{r.suite} notes**:")
                for note in r.notes:
                    lines.append(f"- {note}")
                lines.append("")

    # Timing section
    if any(r.elapsed_ms > 0 for r in results):
        lines.append("## Performance")
        lines.append("")
        sorted_by_time = sorted(results, key=lambda r: r.elapsed_ms, reverse=True)
        lines.append("Slowest scenarios:")
        lines.append("")
        lines.append("| Scenario | Time (ms) | Category |")
        lines.append("|----------|-----------|----------|")
        for r in sorted_by_time[:10]:
            if r.elapsed_ms > 0:
                lines.append(f"| {r.scenario} | {r.elapsed_ms:.0f} | {r.category} |")
        lines.append("")

    report = "\n".join(lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)

    return report
