"""Graph-derived gap analysis for expansion reviews.

Surfaces files, integration points, and patterns the plan may have missed.
Four analysis types:
  1. Consumer audit -- files importing plan targets not in impact map
  2. Integration points -- cross-module boundary crossings
  3. Similar plan patterns -- past plans with analogous scope
  4. Test coverage gaps -- missing test files for impacted modules
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentscaffold.review.queries import (
    get_file_importers,
    get_file_layer,
    get_plan_by_number,
    get_plan_impacted_files,
    get_plans_impacting_file,
)

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore


@dataclass
class GapFinding:
    """A single gap identified by graph analysis."""

    category: str
    text: str
    severity: str = "medium"
    evidence: dict[str, Any] = field(default_factory=dict)


def generate_gaps(store: GraphStore, plan_number: int) -> list[GapFinding]:
    """Generate gap findings for an expansion review.

    Returns a list of GapFinding objects, each with evidence.
    """
    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return []

    impacted_files = get_plan_impacted_files(store, plan_number)
    gaps: list[GapFinding] = []

    impacted_paths = {f.get("f.path", "") for f in impacted_files}

    _consumer_audit(store, impacted_files, impacted_paths, gaps)
    _integration_points(store, impacted_files, gaps)
    _similar_plan_patterns(store, plan_number, impacted_paths, gaps)
    _test_coverage_gaps(store, impacted_files, gaps)

    return gaps


# ---------------------------------------------------------------------------
# Gap analysis generators
# ---------------------------------------------------------------------------


def _consumer_audit(
    store: GraphStore,
    impacted_files: list[dict[str, Any]],
    impacted_paths: set[str],
    out: list[GapFinding],
) -> None:
    """Find files that import plan targets but are not in the impact map."""
    unlisted: dict[str, list[str]] = {}

    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        importers = get_file_importers(store, fpath)
        for imp in importers:
            imp_path = imp.get("a.path", "")
            if imp_path and imp_path not in impacted_paths:
                unlisted.setdefault(imp_path, []).append(fpath)

    if unlisted:
        out.append(
            GapFinding(
                category="CONSUMER_AUDIT",
                severity="high" if len(unlisted) >= 5 else "medium",
                text=(
                    f"{len(unlisted)} files import changed modules but are NOT in "
                    "the File Impact Map. These may need updates or explicit scoping."
                ),
                evidence={
                    "unlisted_count": len(unlisted),
                    "files": {k: v for k, v in list(unlisted.items())[:10]},
                },
            )
        )


def _integration_points(
    store: GraphStore,
    impacted_files: list[dict[str, Any]],
    out: list[GapFinding],
) -> None:
    """Identify cross-module boundary crossings."""
    boundaries: list[dict[str, Any]] = []

    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        src_layer = get_file_layer(store, fpath)
        if not src_layer:
            continue

        src_num = src_layer.get("l.number")
        importers = get_file_importers(store, fpath)

        for imp in importers:
            imp_path = imp.get("a.path", "")
            imp_layer = get_file_layer(store, imp_path)
            if imp_layer and imp_layer.get("l.number") != src_num:
                boundaries.append(
                    {
                        "from_file": imp_path,
                        "from_layer": imp_layer.get("l.number"),
                        "to_file": fpath,
                        "to_layer": src_num,
                    }
                )

    if boundaries:
        layer_pairs: dict[str, int] = {}
        for b in boundaries:
            key = f"L{b['from_layer']} -> L{b['to_layer']}"
            layer_pairs[key] = layer_pairs.get(key, 0) + 1

        detail = ", ".join(f"{k} ({v} edges)" for k, v in sorted(layer_pairs.items()))
        out.append(
            GapFinding(
                category="INTEGRATION_POINTS",
                severity="medium",
                text=(
                    f"Cross-layer boundaries this plan crosses: {detail}. "
                    "Verify integration tests cover each boundary."
                ),
                evidence={
                    "boundary_count": len(boundaries),
                    "layer_pairs": layer_pairs,
                },
            )
        )


def _similar_plan_patterns(
    store: GraphStore,
    plan_number: int,
    impacted_paths: set[str],
    out: list[GapFinding],
) -> None:
    """Find past plans that modified similar sets of files."""
    overlap_plans: dict[int, int] = {}

    for fpath in impacted_paths:
        if not fpath:
            continue
        prior = get_plans_impacting_file(store, fpath)
        for p in prior:
            pnum = p.get("p.number")
            if pnum and pnum != plan_number:
                overlap_plans[pnum] = overlap_plans.get(pnum, 0) + 1

    # Plans with significant file overlap (>= 2 shared files)
    similar = {k: v for k, v in overlap_plans.items() if v >= 2}

    if similar:
        top = sorted(similar.items(), key=lambda x: x[1], reverse=True)[:5]
        detail = ", ".join(f"Plan {num} ({count} shared files)" for num, count in top)
        out.append(
            GapFinding(
                category="SIMILAR_PATTERN",
                severity="medium",
                text=(
                    f"Plans with overlapping file scope: {detail}. "
                    "Review their retrospectives for recurring issues and missed wiring."
                ),
                evidence={
                    "similar_plans": dict(top),
                },
            )
        )


def _test_coverage_gaps(
    store: GraphStore,
    impacted_files: list[dict[str, Any]],
    out: list[GapFinding],
) -> None:
    """Check if test files exist for impacted source files."""
    missing_tests: list[str] = []

    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath or "/test" in fpath or fpath.startswith("tests/"):
            continue

        # Check if any test file references the source
        escaped = fpath.replace("\\", "\\\\").replace("'", "\\'")
        file_stem = escaped.split("/")[-1].split(".")[0]
        test_refs = store.query(
            "MATCH (f:File) "
            f"WHERE f.path CONTAINS 'test' AND f.path CONTAINS '{file_stem}' "
            "RETURN f.path LIMIT 3"
        )

        if not test_refs:
            missing_tests.append(fpath)

    if missing_tests:
        out.append(
            GapFinding(
                category="TEST_COVERAGE",
                severity="high" if len(missing_tests) >= 3 else "medium",
                text=(
                    f"No test files found referencing {len(missing_tests)} impacted files: "
                    f"{', '.join(missing_tests[:5])}. "
                    "Verify test coverage exists or is planned."
                ),
                evidence={"missing_test_files": missing_tests[:10]},
            )
        )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_gaps_markdown(gaps: list[GapFinding]) -> str:
    """Render gap findings as markdown."""
    if not gaps:
        return "No graph-generated gap findings.\n"

    lines: list[str] = []
    lines.append("## Graph-Generated Gap Analysis")
    lines.append("")

    for g in gaps:
        severity_marker = {"high": "!!", "medium": "!", "low": ""}.get(g.severity, "")
        lines.append(f"[{g.category}]{severity_marker} {g.text}")
        lines.append("")

    return "\n".join(lines)
