"""Scoring functions for evaluation scenarios."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from eval.runner import EvalResult


def score_completeness(output: dict[str, Any], required_fields: list[str]) -> EvalResult:
    """Score based on presence of required fields in output."""
    present = [f for f in required_fields if f in output and output[f]]
    missing = [f for f in required_fields if f not in output or not output[f]]
    score = len(present) / len(required_fields) if required_fields else 1.0

    return EvalResult(
        scenario="completeness",
        passed=len(missing) == 0,
        score=round(score, 2),
        expected=f"All fields: {required_fields}",
        actual=f"Present: {present}, Missing: {missing}",
        observations=[f"Missing: {f}" for f in missing],
    )


def score_accuracy(output: list[dict], ground_truth: list[str], key: str = "path") -> EvalResult:
    """Score precision/recall against known ground truth paths."""
    found = {r.get(key, "") for r in output}
    truth = set(ground_truth)

    true_pos = found & truth
    precision = len(true_pos) / len(found) if found else 0.0
    recall = len(true_pos) / len(truth) if truth else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return EvalResult(
        scenario="accuracy",
        passed=recall >= 0.5,
        score=round(f1, 2),
        expected=f"Ground truth: {sorted(truth)}",
        actual=f"Found: {sorted(found)}",
        observations=[
            f"Precision: {precision:.2f}",
            f"Recall: {recall:.2f}",
            f"F1: {f1:.2f}",
        ],
    )


def score_graceful_degradation(output: Any) -> EvalResult:
    """Verify output is non-None, non-exception, and structurally valid."""
    observations = []

    if output is None:
        return EvalResult(
            scenario="graceful_degradation",
            passed=False,
            score=0.0,
            expected="Non-None output",
            actual="None",
            observations=["Output is None"],
        )

    if isinstance(output, Exception):
        return EvalResult(
            scenario="graceful_degradation",
            passed=False,
            score=0.0,
            expected="No exception",
            actual=str(output),
            observations=[f"Exception: {type(output).__name__}: {output}"],
        )

    if isinstance(output, str) and "Traceback" in output:
        observations.append("Traceback found in string output")
        return EvalResult(
            scenario="graceful_degradation",
            passed=False,
            score=0.3,
            expected="No traceback",
            actual=output[:200],
            observations=observations,
        )

    return EvalResult(
        scenario="graceful_degradation",
        passed=True,
        score=1.0,
        expected="Valid output",
        actual=str(type(output).__name__),
        observations=observations,
    )


def score_graph_enrichment(
    with_graph: str, without_graph: str, markers: list[str] | None = None
) -> EvalResult:
    """Measure the delta between graph-enriched and baseline outputs."""
    if markers is None:
        markers = [
            "Graph-Generated",
            "hot spot",
            "volatile",
            "blast radius",
            "community",
            "importer",
        ]

    enriched_count = sum(1 for m in markers if m.lower() in with_graph.lower())
    baseline_count = sum(1 for m in markers if m.lower() in without_graph.lower())
    delta = enriched_count - baseline_count

    return EvalResult(
        scenario="graph_enrichment",
        passed=delta > 0,
        score=min(delta / max(len(markers), 1), 1.0),
        expected=f"Enriched > baseline by markers: {markers}",
        actual=f"Enriched: {enriched_count}, Baseline: {baseline_count}, Delta: {delta}",
        observations=[
            f"Enriched markers: {enriched_count}/{len(markers)}",
            f"Baseline markers: {baseline_count}/{len(markers)}",
        ],
    )


# ---------------------------------------------------------------------------
# Readability scoring
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$", re.MULTILINE)
_RAW_ID_RE = re.compile(r"[a-f0-9]{40,}|file::|method::|class::|plan::|contract::|learning::")
_JINJA_RESIDUE_RE = re.compile(r"\{\{|\}\}|\{%|%\}")
_VERY_LONG_LINE = 300


@dataclass
class ReadabilityReport:
    """Detailed readability analysis of a rendered document."""

    name: str
    heading_structure_ok: bool = True
    heading_hierarchy_issues: list[str] = field(default_factory=list)
    table_wellformed: bool = True
    table_issues: list[str] = field(default_factory=list)
    raw_id_count: int = 0
    jinja_residue_count: int = 0
    very_long_lines: int = 0
    total_lines: int = 0
    empty_sections: int = 0
    score: float = 1.0
    observations: list[str] = field(default_factory=list)


def score_readability(text: str, name: str = "document") -> ReadabilityReport:
    """Analyze a rendered markdown document for readability.

    Checks:
    1. Heading hierarchy (no skipping levels, e.g. H1 -> H3)
    2. Table well-formedness (consistent columns, separator present)
    3. Raw graph IDs leaked into output (hashes, internal node IDs)
    4. Jinja2 residue
    5. Very long lines (>300 chars -- signals data dumps)
    6. Empty sections (heading followed immediately by another heading)
    """
    report = ReadabilityReport(name=name)
    lines = text.splitlines()
    report.total_lines = len(lines)

    # 1. Heading hierarchy
    headings = _HEADING_RE.findall(text)
    prev_level = 0
    for hashes, title in headings:
        level = len(hashes)
        if prev_level > 0 and level > prev_level + 1:
            report.heading_hierarchy_issues.append(
                f"H{prev_level} -> H{level} skips a level (before '{title[:40]}')"
            )
            report.heading_structure_ok = False
        prev_level = level

    # 2. Table well-formedness
    in_table = False
    table_col_count = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if _TABLE_ROW_RE.match(stripped):
            cols = stripped.count("|") - 1
            if not in_table:
                in_table = True
                table_col_count = cols
            elif not _TABLE_SEP_RE.match(stripped) and cols != table_col_count:
                report.table_issues.append(
                    f"Line {i}: expected {table_col_count} columns, got {cols}"
                )
                report.table_wellformed = False
        else:
            in_table = False

    # 3. Raw IDs
    report.raw_id_count = len(_RAW_ID_RE.findall(text))

    # 4. Jinja2 residue
    report.jinja_residue_count = len(_JINJA_RESIDUE_RE.findall(text))

    # 5. Very long lines
    report.very_long_lines = sum(1 for ln in lines if len(ln) > _VERY_LONG_LINE)

    # 6. Empty sections
    for i in range(len(lines) - 1):
        if _HEADING_RE.match(lines[i]) and _HEADING_RE.match(lines[i + 1]):
            report.empty_sections += 1

    # Compute score (each check is a fraction of 1.0)
    penalties = 0.0
    if not report.heading_structure_ok:
        penalties += 0.15
        report.observations.append(
            f"Heading hierarchy issues: {len(report.heading_hierarchy_issues)}"
        )
    if not report.table_wellformed:
        penalties += 0.10
        report.observations.append(f"Table column issues: {len(report.table_issues)}")
    if report.raw_id_count > 0:
        penalties += min(report.raw_id_count * 0.05, 0.25)
        report.observations.append(f"Raw graph IDs leaked: {report.raw_id_count}")
    if report.jinja_residue_count > 0:
        penalties += 0.20
        report.observations.append(f"Jinja2 residue: {report.jinja_residue_count}")
    if report.very_long_lines > 0:
        penalties += min(report.very_long_lines * 0.03, 0.15)
        report.observations.append(
            f"Very long lines (>{_VERY_LONG_LINE} chars): {report.very_long_lines}"
        )
    if report.empty_sections > 2:
        penalties += 0.10
        report.observations.append(f"Empty sections: {report.empty_sections}")

    report.score = round(max(1.0 - penalties, 0.0), 2)
    return report
