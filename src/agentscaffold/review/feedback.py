"""Retrospective enrichment via graph-derived pattern detection.

Enriches post-execution retrospectives with:
  1. Module volatility -- modification frequency signals
  2. Learning patterns -- recurring themes across learnings
  3. Complexity delta -- consumer/import count changes
  4. Auto-linked learnings -- suggest related code for new learnings
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentscaffold.review.queries import (
    get_file_importers,
    get_function_callers,
    get_hot_files,
    get_plan_by_number,
    get_plan_impacted_files,
    get_plans_impacting_file,
)

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore


@dataclass
class RetroInsight:
    """A single retrospective enrichment insight."""

    category: str
    text: str
    evidence: dict[str, Any] = field(default_factory=dict)


def generate_retro_enrichment(store: GraphStore, plan_number: int) -> list[RetroInsight]:
    """Generate retrospective enrichment for the given plan.

    Should be called during or after the retrospective.
    """
    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return []

    impacted_files = get_plan_impacted_files(store, plan_number)
    insights: list[RetroInsight] = []

    _volatility_analysis(store, plan_number, impacted_files, insights)
    _learning_patterns(store, plan_number, insights)
    _complexity_profile(store, impacted_files, insights)
    _hot_file_check(store, impacted_files, insights)

    return insights


# ---------------------------------------------------------------------------
# Insight generators
# ---------------------------------------------------------------------------


def _volatility_analysis(
    store: GraphStore,
    plan_number: int,
    impacted_files: list[dict[str, Any]],
    out: list[RetroInsight],
) -> None:
    """Flag files with high modification frequency."""
    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        prior_plans = get_plans_impacting_file(store, fpath)
        other_plans = [p for p in prior_plans if p.get("p.number") != plan_number]

        if len(other_plans) >= 3:
            plan_nums = [str(p.get("p.number", "?")) for p in other_plans]
            out.append(
                RetroInsight(
                    category="VOLATILITY",
                    text=(
                        f"{fpath} has been modified by {len(other_plans) + 1} plans "
                        f"(including this one): Plans {', '.join(plan_nums[:5])}. "
                        "Consider an architectural review or stability freeze."
                    ),
                    evidence={
                        "file": fpath,
                        "plan_count": len(other_plans) + 1,
                        "plans": plan_nums,
                    },
                )
            )


def _learning_patterns(
    store: GraphStore,
    plan_number: int,
    out: list[RetroInsight],
) -> None:
    """Detect recurring themes in learnings related to this plan's files."""
    impacted_files = get_plan_impacted_files(store, plan_number)

    all_learnings: list[dict[str, Any]] = []
    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue
        file_id = f"file::{fpath}"
        escaped = file_id.replace("\\", "\\\\").replace("'", "\\'")
        learnings = store.query(
            "MATCH (lr:Learning)-[:LEARNING_RELATES_TO_FILE]->(f:File) "
            f"WHERE f.id = '{escaped}' "
            "RETURN lr.learningId, lr.description, lr.planNumber"
        )
        all_learnings.extend(learnings)

    if len(all_learnings) >= 3:
        out.append(
            RetroInsight(
                category="LEARNING_PATTERN",
                text=(
                    f"{len(all_learnings)} learnings are linked to files modified by "
                    "this plan. Review for recurring themes that might warrant a rule "
                    "update in AGENTS.md or a template enhancement."
                ),
                evidence={
                    "learning_count": len(all_learnings),
                    "sample": [lr.get("lr.description", "")[:100] for lr in all_learnings[:5]],
                },
            )
        )


def _complexity_profile(
    store: GraphStore,
    impacted_files: list[dict[str, Any]],
    out: list[RetroInsight],
) -> None:
    """Report importer/caller counts for impacted files (complexity signal)."""
    high_coupling: list[dict[str, Any]] = []

    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        importers = get_file_importers(store, fpath)
        callers = get_function_callers(store, fpath)
        total = len(importers) + len(callers)

        if total >= 10:
            high_coupling.append(
                {
                    "file": fpath,
                    "importers": len(importers),
                    "callers": len(callers),
                    "total": total,
                }
            )

    if high_coupling:
        top = sorted(high_coupling, key=lambda x: x["total"], reverse=True)
        detail = ", ".join(f"{f['file']} ({f['total']} refs)" for f in top[:3])
        out.append(
            RetroInsight(
                category="COMPLEXITY",
                text=(
                    f"{len(high_coupling)} modified files have high coupling: {detail}. "
                    "Monitor for increasing coupling over time."
                ),
                evidence={"high_coupling_files": top[:5]},
            )
        )


def _hot_file_check(
    store: GraphStore,
    impacted_files: list[dict[str, Any]],
    out: list[RetroInsight],
) -> None:
    """Check if any impacted files are in the codebase hot files list."""
    hot = get_hot_files(store, limit=20)
    hot_paths = {h.get("f.path", "") for h in hot}
    impacted_paths = {f.get("f.path", "") for f in impacted_files}

    overlap = impacted_paths & hot_paths
    if overlap:
        out.append(
            RetroInsight(
                category="HOT_FILE",
                text=(
                    f"{len(overlap)} files modified by this plan are among the "
                    f"most-frequently-modified in the codebase: {', '.join(sorted(overlap)[:3])}."
                ),
                evidence={"hot_files": sorted(overlap)},
            )
        )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_retro_markdown(insights: list[RetroInsight]) -> str:
    """Render retro insights as markdown."""
    if not insights:
        return "No graph-generated retrospective insights.\n"

    lines: list[str] = []
    lines.append("## Graph-Generated Retrospective Context")
    lines.append("")

    for ins in insights:
        lines.append(f"[{ins.category}] {ins.text}")
        lines.append("")

    return "\n".join(lines)
