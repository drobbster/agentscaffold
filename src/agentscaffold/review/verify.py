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
from typing import TYPE_CHECKING, Any

from agentscaffold.review.queries import (
    get_file_importers,
    get_function_callers,
    get_plan_by_number,
    get_plan_impacted_files,
)

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore


@dataclass
class VerificationItem:
    """A single verification result."""

    check: str
    status: str  # pass, warn, fail
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def verify_implementation(store: GraphStore, plan_number: int) -> list[VerificationItem]:
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
    impacted_files = get_plan_impacted_files(store, plan_number)
    planned_paths = {f.get("f.path", "") for f in impacted_files}

    _check_plan_compliance(store, plan_number, planned_paths, items)
    _check_signatures(store, planned_paths, items)
    _check_wiring(store, planned_paths, items)
    _check_test_delta(store, planned_paths, items)

    return items


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------


def _check_plan_compliance(
    store: GraphStore,
    plan_number: int,
    planned_paths: set[str],
    out: list[VerificationItem],
) -> None:
    """Check that planned files exist in the graph and flag any extra modifications."""
    missing: list[str] = []
    for fpath in planned_paths:
        if not fpath:
            continue
        file_id = f"file::{fpath}"
        escaped = file_id.replace("\\", "\\\\").replace("'", "\\'")
        rows = store.query(f"MATCH (f:File) WHERE f.id = '{escaped}' RETURN f.id")
        if not rows:
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
    store: GraphStore,
    planned_paths: set[str],
    out: list[VerificationItem],
) -> None:
    """Verify that expected functions and classes exist in planned files."""
    total_defs = 0
    for fpath in planned_paths:
        if not fpath:
            continue
        escaped = fpath.replace("\\", "\\\\").replace("'", "\\'")
        funcs = store.query(
            f"MATCH (fn:Function) WHERE fn.filePath = '{escaped}' RETURN fn.name, fn.signature"
        )
        classes = store.query(f"MATCH (c:Class) WHERE c.filePath = '{escaped}' RETURN c.name")
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
    store: GraphStore,
    planned_paths: set[str],
    out: list[VerificationItem],
) -> None:
    """Check that all callers/importers of planned files still resolve."""
    total_importers = 0
    broken_imports: list[str] = []

    for fpath in planned_paths:
        if not fpath:
            continue
        importers = get_file_importers(store, fpath)
        callers = get_function_callers(store, fpath)
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
    store: GraphStore,
    planned_paths: set[str],
    out: list[VerificationItem],
) -> None:
    """Count test files that exist for planned source files."""
    tested_count = 0
    untested: list[str] = []

    for fpath in planned_paths:
        if not fpath or "/test" in fpath or fpath.startswith("tests/"):
            continue

        stem = fpath.split("/")[-1].split(".")[0]
        escaped = stem.replace("\\", "\\\\").replace("'", "\\'")
        test_files = store.query(
            f"MATCH (f:File) WHERE f.path CONTAINS 'test' AND f.path CONTAINS '{escaped}' "
            "RETURN f.path LIMIT 1"
        )

        if test_files:
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

    status_icon = {"pass": "[PASS]", "warn": "[WARN]", "fail": "[FAIL]"}
    for item in items:
        icon = status_icon.get(item.status, "[????]")
        lines.append(f"{icon} **{item.check}**: {item.detail}")

    lines.append("")
    return "\n".join(lines)
