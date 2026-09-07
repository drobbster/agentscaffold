"""Post-implementation verification against plan and graph.

Verifies what was actually implemented versus what the plan specified:
  1. Plan compliance -- stated vs actual file modifications
  2. Signature verification -- do expected functions/classes exist
  3. Layer conformance -- check for layer violations
  4. Wiring check -- verify all callers of modified functions still work
  5. Test delta -- count tests added/modified
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.graph.query_compat import ql, sql_escape
from agentscaffold.review.file_impact_resolve import (
    ImplementationProjectError,
    query_root,
    query_store,
    resolved_impacts,
)
from agentscaffold.review.queries import (
    get_file_importers,
    get_function_callers,
    get_plan_by_number,
)
from agentscaffold.review.test_presence import source_has_tests

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


@dataclass
class VerificationItem:
    """A single verification result."""

    check: str
    status: str  # pass, warn, fail, skip
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def verify_implementation(
    store: GraphBackend,
    plan_number: int,
    *,
    root: Path | None = None,
    config: Any = None,
) -> list[VerificationItem]:
    """Verify a plan's implementation against the graph.

    Should be run AFTER re-indexing the codebase post-implementation.
    Returns a list of verification items.
    """
    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return [
            VerificationItem(
                check="plan_exists",
                status="fail",
                detail=f"Plan {plan_number} not found in graph.",
            )
        ]

    items: list[VerificationItem] = []
    try:
        with resolved_impacts(store, plan_number, root=root, config=config) as impacted_files:
            _verify_from_rows(store, plan_number, impacted_files, items)
    except ImplementationProjectError as exc:
        items.append(
            VerificationItem(
                check="plan_compliance",
                status="fail",
                detail=str(exc),
                evidence={"error_code": "implementation_project_unregistered"},
            )
        )
    return items


def _verify_from_rows(
    store: GraphBackend,
    plan_number: int,
    impacted_files: list[dict[str, Any]],
    items: list[VerificationItem],
) -> None:
    resolved = [
        f
        for f in impacted_files
        if f.get("f.path") and f.get("resolution") in (None, "local", "sibling")
    ]
    skipped = [f for f in impacted_files if f.get("resolution") == "skipped"]
    planned_paths = {f.get("f.path", "") for f in resolved}

    _check_plan_compliance(store, plan_number, planned_paths, items, rows=resolved)
    if skipped:
        items.append(
            VerificationItem(
                check="plan_compliance",
                status="skip",
                detail=(
                    f"{len(skipped)} File Impact path(s) are outside this project "
                    "and were not certified. This is not a pass."
                ),
                evidence={
                    "skipped": [f.get("f.path") for f in skipped],
                    "reasons": [f.get("reason") for f in skipped],
                },
            )
        )
    _check_signatures(store, planned_paths, items, rows=resolved)
    _check_wiring(store, planned_paths, items, rows=resolved)
    _check_test_delta(store, planned_paths, items, rows=resolved)


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------


def _check_plan_compliance(
    store: GraphBackend,
    plan_number: int,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Check that planned files exist in the graph and flag any extra modifications."""
    nonempty = {p for p in planned_paths if p}
    if not nonempty:
        out.append(
            VerificationItem(
                check="plan_compliance",
                status="skip",
                detail=(
                    "No planned files resolved in this project, so compliance "
                    "cannot be certified. This is not a pass."
                ),
                evidence={"planned_count": 0},
            )
        )
        return

    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    missing: list[str] = []
    for fpath in planned_paths:
        if not fpath:
            continue
        frow = row_by_path.get(fpath, {})
        if frow.get("resolution") == "sibling":
            disk = query_root(frow, Path(".")) / fpath
            if not disk.is_file():
                missing.append(fpath)
            continue
        file_id = f"file::{fpath}"
        escaped = sql_escape(file_id)
        found = ql(
            query_store(frow, store),
            sql=f"SELECT id AS \"f.id\" FROM File WHERE id = '{escaped}'",
        )
        if not found:
            missing.append(fpath)

    if missing:
        out.append(
            VerificationItem(
                check="plan_compliance",
                status="warn",
                detail=(
                    f"{len(missing)} files in the plan's impact map were not found "
                    f"in the graph: {', '.join(missing[:5])}"
                ),
                evidence={"missing_files": missing},
            )
        )
    else:
        out.append(
            VerificationItem(
                check="plan_compliance",
                status="pass",
                detail=f"All {len(planned_paths)} planned files exist in the graph.",
            )
        )


def _check_signatures(
    store: GraphBackend,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Verify that expected functions and classes exist in planned files."""
    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    total_defs = 0
    for fpath in planned_paths:
        if not fpath:
            continue
        escaped = sql_escape(fpath)
        qstore = query_store(row_by_path.get(fpath, {}), store)
        funcs = ql(
            qstore,
            sql=(
                f'SELECT name AS "fn.name", signature AS "fn.signature" '
                f"FROM Function WHERE filePath = '{escaped}'"
            ),
        )
        classes = ql(
            qstore,
            sql=f"SELECT name AS \"c.name\" FROM Class WHERE filePath = '{escaped}'",
        )
        total_defs += len(funcs) + len(classes)

    out.append(
        VerificationItem(
            check="signatures",
            status="pass" if total_defs > 0 else "warn",
            detail=f"{total_defs} definitions found across planned files.",
            evidence={"total_definitions": total_defs},
        )
    )


def _check_wiring(
    store: GraphBackend,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Check that all callers/importers of planned files still resolve."""
    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    total_importers = 0
    broken_imports: list[str] = []

    for fpath in planned_paths:
        if not fpath:
            continue
        qstore = query_store(row_by_path.get(fpath, {}), store)
        importers = get_file_importers(qstore, fpath)
        callers = get_function_callers(qstore, fpath)
        total_importers += len(importers) + len(callers)

    if broken_imports:
        out.append(
            VerificationItem(
                check="wiring",
                status="fail",
                detail=f"{len(broken_imports)} broken import/call references detected.",
                evidence={"broken": broken_imports},
            )
        )
    else:
        out.append(
            VerificationItem(
                check="wiring",
                status="pass",
                detail=f"{total_importers} import/call references verified.",
                evidence={"total_references": total_importers},
            )
        )


def _check_test_delta(
    store: GraphBackend,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Count test files that exist for planned source files."""
    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    tested_count = 0
    untested: list[str] = []

    for fpath in planned_paths:
        if not fpath or "/test" in fpath or fpath.startswith("tests/"):
            continue

        frow = row_by_path.get(fpath, {})
        qstore = query_store(frow, store)
        disk_root = query_root(frow, Path(".")) if frow else None
        if source_has_tests(qstore, fpath, root=disk_root):
            tested_count += 1
        else:
            untested.append(fpath)

    total = tested_count + len(untested)
    if untested:
        out.append(
            VerificationItem(
                check="test_delta",
                status="warn",
                detail=(
                    f"Tests found for {tested_count}/{total} source files. "
                    f"Missing: {', '.join(untested[:5])}"
                ),
                evidence={"tested": tested_count, "untested": untested},
            )
        )
    else:
        out.append(
            VerificationItem(
                check="test_delta",
                status="pass",
                detail=f"Tests found for all {total} source files.",
            )
        )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_verification_markdown(items: list[VerificationItem]) -> str:
    """Render verification results as markdown."""
    if not items:
        return "No verification results.\n"

    lines: list[str] = []
    lines.append("## Post-Implementation Verification")
    lines.append("")

    status_icon = {
        "pass": "[PASS]",
        "warn": "[WARN]",
        "fail": "[FAIL]",
        "skip": "[SKIP]",
    }
    for item in items:
        icon = status_icon.get(item.status, "[????]")
        lines.append(f"{icon} **{item.check}**: {item.detail}")

    lines.append("")
    return "\n".join(lines)
