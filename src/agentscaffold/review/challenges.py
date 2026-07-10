"""Graph-evidence adversarial challenge generator.

Produces concrete, data-backed challenges for devil's advocate reviews.
Each challenge is tagged with a category and grounded in graph facts,
not LLM speculation. The LLM then reasons over these challenges.

Categories: DEPENDENCY, HISTORY, LEARNING, LAYER, CONTRACT, PATTERN,
CONSUMER, PERFORMANCE
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentscaffold.graph.query_compat import ql, sql_escape
from agentscaffold.review.filters import is_source_code_file
from agentscaffold.review.queries import (
    get_contracts_for_file,
    get_file_importers,
    get_file_layer,
    get_function_callers,
    get_learnings_for_file,
    get_plan_by_number,
    get_plan_impacted_files,
    get_plans_impacting_file,
    get_transitive_consumers,
)

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


@dataclass
class Challenge:
    """A single adversarial challenge backed by graph evidence."""

    category: str
    text: str
    severity: str = "medium"
    evidence: dict[str, Any] = field(default_factory=dict)


def generate_challenges(store: GraphBackend, plan_number: int) -> list[Challenge]:
    """Generate adversarial challenges for a plan from graph data.

    Returns a list of Challenge objects, each grounded in evidence.
    """
    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return []

    impacted_files = get_plan_impacted_files(store, plan_number)
    challenges: list[Challenge] = []

    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        flang = frow.get("f.language", "")
        _check_dependency_blast(store, fpath, challenges)
        _check_history(store, fpath, plan_number, challenges, language=flang)
        _check_learnings(store, fpath, challenges)
        _check_layer(store, fpath, impacted_files, challenges)
        _check_contracts(store, fpath, challenges)

    # Plan-level checks (not per-file)
    _check_patterns(store, plan_number, impacted_files, challenges)
    _check_consumer_coverage(store, plan_number, impacted_files, challenges)

    return challenges


# ---------------------------------------------------------------------------
# Per-file challenge generators
# ---------------------------------------------------------------------------


def _check_dependency_blast(store: GraphBackend, file_path: str, out: list[Challenge]) -> None:
    """Generate DEPENDENCY challenges based on consumer count."""
    importers = get_file_importers(store, file_path)
    callers = get_function_callers(store, file_path)
    transitive = get_transitive_consumers(store, file_path)

    direct_count = len(importers)
    transitive_count = len(transitive)
    caller_count = len(callers)

    if direct_count >= 5:
        out.append(
            Challenge(
                category="DEPENDENCY",
                severity="high" if direct_count >= 10 else "medium",
                text=(
                    f"{file_path} has {direct_count} direct importers and "
                    f"{transitive_count} transitive consumers. "
                    "A signature change creates a cascade. "
                    "Has the plan addressed backward compatibility for all consumers?"
                ),
                evidence={
                    "file": file_path,
                    "direct_importers": direct_count,
                    "transitive_consumers": transitive_count,
                    "callers": caller_count,
                },
            )
        )

    if caller_count >= 10:
        out.append(
            Challenge(
                category="DEPENDENCY",
                severity="high",
                text=(
                    f"Functions in {file_path} are called from {caller_count} external "
                    "call sites. Performance changes here are amplified across the codebase."
                ),
                evidence={"file": file_path, "caller_count": caller_count},
            )
        )


def _check_history(
    store: GraphBackend,
    file_path: str,
    current_plan: int,
    out: list[Challenge],
    *,
    language: str = "",
) -> None:
    """Generate HISTORY challenges based on modification frequency.

    Only applies to parsed source files. Append-only governance/docs artifacts
    (workflow_state.md, contract registries, studies) are modified by nearly
    every plan by design, so flagging them as "architecturally unstable" is a
    false positive.
    """
    if not is_source_code_file(file_path, language):
        return

    prior_plans = get_plans_impacting_file(store, file_path)
    other_plans = [p for p in prior_plans if p.get("p.number") != current_plan]

    if len(other_plans) >= 3:
        plan_nums = [str(p.get("p.number", "?")) for p in other_plans[:5]]
        out.append(
            Challenge(
                category="HISTORY",
                severity="medium",
                text=(
                    f"Plans {', '.join(plan_nums)} have also modified {file_path}. "
                    f"This file has been touched by {len(other_plans)} plans. "
                    "High modification frequency may signal architectural instability. "
                    "Should this plan include a stability assessment first?"
                ),
                evidence={
                    "file": file_path,
                    "prior_plan_count": len(other_plans),
                    "prior_plans": plan_nums,
                },
            )
        )


def _check_learnings(
    store: GraphBackend, file_path: str, out: list[Challenge], *, max_per_file: int = 5
) -> None:
    """Generate LEARNING challenges from related learnings.

    Learnings are linked to files by plan co-occurrence (``LEARNING_RELATES_TO_FILE``),
    not semantic relevance, so a high-churn file can accumulate many unrelated
    learnings. Cap and rank them: not-yet-incorporated learnings first (they are
    the ones an author most needs reminding of), then most-recent plan. This
    keeps the signal focused until embedding-based relevance is available.
    """
    learnings = [lr for lr in get_learnings_for_file(store, file_path) if lr.get("lr.description")]

    def _rank(lr: dict[str, Any]) -> tuple[int, int]:
        status = str(lr.get("lr.status", "")).strip().lower()
        # incorporated learnings are lower priority than pending/unmarked ones
        incorporated = 1 if status.startswith("incorporated") else 0
        try:
            plan_rank = -int(lr.get("lr.planNumber") or 0)
        except (TypeError, ValueError):
            plan_rank = 0
        return (incorporated, plan_rank)

    ranked = sorted(learnings, key=_rank)
    total = len(ranked)

    for idx, lr in enumerate(ranked[:max_per_file]):
        description = lr.get("lr.description", "")
        learning_id = lr.get("lr.learningId", "")
        plan_num = lr.get("lr.planNumber", "?")

        if description:
            suffix = ""
            if idx == 0 and total > max_per_file:
                suffix = (
                    f" (showing top {max_per_file} of {total} learnings linked to this file; "
                    "linkage is by plan co-occurrence, not semantic relevance)"
                )
            out.append(
                Challenge(
                    category="LEARNING",
                    severity="medium",
                    text=(
                        f"{learning_id} (from Plan {plan_num}) states: "
                        f'"{description}" '
                        f"This plan modifies {file_path}. "
                        f"Has this learning been accounted for?{suffix}"
                    ),
                    evidence={
                        "file": file_path,
                        "learning_id": learning_id,
                        "plan_number": plan_num,
                        "total_linked_learnings": total,
                        "shown": min(max_per_file, total),
                    },
                )
            )


def _check_layer(
    store: GraphBackend,
    file_path: str,
    impacted_files: list[dict[str, Any]],
    out: list[Challenge],
) -> None:
    """Generate LAYER challenges for cross-layer impacts."""
    layer = get_file_layer(store, file_path)
    if not layer:
        return

    file_layer_num = layer.get("l.number")
    importers = get_file_importers(store, file_path)

    cross_layer_importers: list[dict[str, Any]] = []
    for imp in importers:
        imp_path = imp.get("a.path", "")
        imp_layer = get_file_layer(store, imp_path)
        if imp_layer and imp_layer.get("l.number") != file_layer_num:
            cross_layer_importers.append(
                {
                    "path": imp_path,
                    "layer": imp_layer.get("l.number"),
                }
            )

    # Check if cross-layer consumers are in the plan's impact map
    impacted_paths = {f.get("f.path", "") for f in impacted_files}
    unlisted = [c for c in cross_layer_importers if c["path"] not in impacted_paths]

    if unlisted:
        layer_name = layer.get("l.name", "?")
        out.append(
            Challenge(
                category="LAYER",
                severity="high" if len(unlisted) >= 3 else "medium",
                text=(
                    f"This plan modifies Layer {file_layer_num} ({layer_name}) "
                    f"but {len(unlisted)} cross-layer consumers are NOT in the "
                    f"File Impact Map: {', '.join(c['path'] for c in unlisted[:5])}. "
                    "Is this an oversight or a conscious scope decision?"
                ),
                evidence={
                    "file": file_path,
                    "file_layer": file_layer_num,
                    "unlisted_consumers": unlisted[:10],
                },
            )
        )


def _check_contracts(store: GraphBackend, file_path: str, out: list[Challenge]) -> None:
    """Generate CONTRACT challenges for files under contract."""
    contracts = get_contracts_for_file(store, file_path)

    for c in contracts:
        name = c.get("c.name", "?")
        version = c.get("c.version", "?")
        out.append(
            Challenge(
                category="CONTRACT",
                severity="medium",
                text=(
                    f"{file_path} is covered by contract '{name}' v{version}. "
                    "If any public signature changes, a major version bump is required "
                    "with consumer notification. Has the plan accounted for this?"
                ),
                evidence={
                    "file": file_path,
                    "contract": name,
                    "version": version,
                },
            )
        )


# ---------------------------------------------------------------------------
# Plan-level challenge generators
# ---------------------------------------------------------------------------


def _check_patterns(
    store: GraphBackend,
    plan_number: int,
    impacted_files: list[dict[str, Any]],
    out: list[Challenge],
) -> None:
    """Generate PATTERN challenges from recurring review findings."""
    # Look for past findings on the same files
    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        file_id = f"file::{fpath}"
        escaped = sql_escape(file_id)
        findings = ql(
            store,
            sql=(
                'SELECT t.rf_category AS "rf.category",'
                ' t.rf_finding AS "rf.finding",'
                ' t.rf_planNumber AS "rf.planNumber"'
                " FROM GRAPH_TABLE(agentscaffold_graph"
                " MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File)"
                f" WHERE f.id = '{escaped}'"
                " COLUMNS (rf.category AS rf_category,"
                " rf.finding AS rf_finding,"
                " rf.planNumber AS rf_planNumber)) t"
            ),
        )

        if len(findings) >= 2:
            categories = [f.get("rf.category", "?") for f in findings]
            out.append(
                Challenge(
                    category="PATTERN",
                    severity="medium",
                    text=(
                        f"{fpath} has {len(findings)} prior review findings "
                        f"(categories: {', '.join(set(categories))}). "
                        "This may indicate a recurring issue area. "
                        "Verify that this plan addresses the underlying patterns."
                    ),
                    evidence={"file": fpath, "finding_count": len(findings)},
                )
            )


def _check_consumer_coverage(
    store: GraphBackend,
    plan_number: int,
    impacted_files: list[dict[str, Any]],
    out: list[Challenge],
) -> None:
    """Generate CONSUMER challenges for files that import plan targets but
    are not listed in the impact map."""
    impacted_paths = {f.get("f.path", "") for f in impacted_files}
    unlisted_consumers: dict[str, list[str]] = {}

    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        importers = get_file_importers(store, fpath)
        for imp in importers:
            imp_path = imp.get("a.path", "")
            if imp_path and imp_path not in impacted_paths:
                unlisted_consumers.setdefault(imp_path, []).append(fpath)

    if unlisted_consumers:
        total = len(unlisted_consumers)
        sample = list(unlisted_consumers.items())[:5]
        detail = "; ".join(f"{path} (imports {', '.join(targets)})" for path, targets in sample)
        shown_note = f" (showing {len(sample)} of {total})" if total > len(sample) else ""
        out.append(
            Challenge(
                category="CONSUMER",
                severity="high" if total >= 5 else "medium",
                text=(
                    f"{total} files import plan targets but are NOT in "
                    f"the File Impact Map{shown_note}: {detail}. "
                    "These may need test updates or explicit scoping justification."
                ),
                evidence={
                    "unlisted_count": total,
                    "shown": len(sample),
                    "sample": dict(sample),
                },
            )
        )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_challenges_markdown(challenges: list[Challenge]) -> str:
    """Render challenges as markdown for injection into review prompts."""
    if not challenges:
        return "No graph-generated challenges (graph may lack governance data).\n"

    lines: list[str] = []
    lines.append("## Graph-Generated Adversarial Challenges")
    lines.append("")

    for c in challenges:
        severity_marker = {"high": "!!", "medium": "!", "low": ""}.get(c.severity, "")
        lines.append(f"[{c.category}]{severity_marker} {c.text}")
        lines.append("")

    return "\n".join(lines)
