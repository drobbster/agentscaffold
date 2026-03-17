"""ReviewFinding write-back logic.

Provides ``record_finding()`` and ``resolve_finding()`` that work on the
DuckPGQ GraphBackend.

Performance target: <200ms per write.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


_SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low")


def _finding_id(plan_number: int, review_type: str, category: str, finding: str) -> str:
    """Derive a deterministic ID from the finding content."""
    key = f"finding::{plan_number}::{review_type}::{category}::{finding[:64]}"
    return "rf::" + hashlib.sha1(key.encode()).hexdigest()[:12]  # noqa: S324


def record_finding(
    store: GraphBackend,
    *,
    plan_number: int,
    review_type: str,
    category: str,
    finding: str,
    severity: str = "medium",
    file_paths: list[str] | None = None,
    function_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Record a review finding in the knowledge graph.

    Creates a ReviewFinding node and connects it to relevant files and
    functions via FINDING_ABOUT_FILE and FINDING_ABOUT_FUNC edges.

    Args:
        store: Open GraphBackend instance.
        plan_number: The plan this finding relates to.
        review_type: Review type label (e.g. "quant_architect", "security").
        category: Finding category (e.g. "correctness", "performance").
        finding: Human-readable finding description.
        severity: "low", "medium", "high", or "critical".
        file_paths: Paths of files related to this finding.
        function_ids: IDs of functions related to this finding.

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()
    finding_id = _finding_id(plan_number, review_type, category, finding)
    now = datetime.now(timezone.utc).isoformat()

    props: dict[str, Any] = {
        "id": finding_id,
        "reviewType": review_type,
        "planNumber": plan_number,
        "severity": severity,
        "category": category,
        "finding": finding,
        "resolution": "",
        "status": "open",
    }

    store.create_node("ReviewFinding", props)

    # Link to files
    for fp in file_paths or []:
        rows = store.query(f"SELECT id FROM File WHERE path = '{_esc(fp)}'")
        file_id = rows[0]["id"] if rows else None

        if file_id:
            store.create_edge("FINDING_ABOUT_FILE", "ReviewFinding", finding_id, "File", file_id)

    # Link to functions
    for fn_id in function_ids or []:
        store.create_edge("FINDING_ABOUT_FUNC", "ReviewFinding", finding_id, "Function", fn_id)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "id": finding_id,
        "status": "open",
        "plan_number": plan_number,
        "review_type": review_type,
        "category": category,
        "severity": severity,
        "elapsed_ms": elapsed_ms,
        "created_at": now,
    }


def resolve_finding(
    store: GraphBackend,
    finding_id: str,
    *,
    resolution: str,
) -> dict[str, Any]:
    """Mark a ReviewFinding as resolved.

    Args:
        store: Open GraphBackend instance.
        finding_id: The ID of the finding to resolve.
        resolution: Human-readable resolution description.

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()

    store.execute(
        f"UPDATE ReviewFinding SET status = 'resolved', resolution = '{_esc(resolution)}'"
        f" WHERE id = '{_esc(finding_id)}'"
    )

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "id": finding_id,
        "status": "resolved",
        "resolution": resolution,
        "elapsed_ms": elapsed_ms,
    }


def get_open_findings(
    store: GraphBackend,
    *,
    plan_number: int | None = None,
    file_path: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return open ReviewFindings, optionally filtered by plan or file.

    Args:
        store: Open GraphBackend instance.
        plan_number: Filter by plan number.
        file_path: Filter by related file path.
        limit: Maximum number of findings to return.

    Returns:
        List of finding dicts, sorted by severity then creation order.
    """
    from agentscaffold.graph.query_compat import ql  # noqa: PLC0415

    if file_path:
        rows = store.query(
            f'SELECT t.rf_id AS "rf.id", t.rf_reviewType AS "rf.reviewType",'
            f' t.rf_planNumber AS "rf.planNumber", t.rf_severity AS "rf.severity",'
            f' t.rf_category AS "rf.category", t.rf_finding AS "rf.finding"'
            f" FROM GRAPH_TABLE(agentscaffold_graph"
            f"   MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File)"
            f"   WHERE rf.status = 'open' AND f.path = '{_esc(file_path)}'"
            f"   COLUMNS (rf.id AS rf_id, rf.reviewType AS rf_reviewType,"
            f"            rf.planNumber AS rf_planNumber, rf.severity AS rf_severity,"
            f"            rf.category AS rf_category, rf.finding AS rf_finding)"
            f" ) t LIMIT {limit}"
        )
    else:
        plan_filter = f" AND planNumber = {plan_number}" if plan_number is not None else ""
        rows = ql(
            store,
            sql=(
                f'SELECT id AS "rf.id", reviewType AS "rf.reviewType",'
                f' planNumber AS "rf.planNumber", severity AS "rf.severity",'
                f' category AS "rf.category", finding AS "rf.finding"'
                f" FROM ReviewFinding WHERE status = 'open'{plan_filter} LIMIT {limit}"
            ),
        )

    # Sort by severity
    def _sev_key(row: dict) -> int:
        sev = (row.get("rf.severity") or "medium").lower()
        try:
            return _SEVERITY_ORDER.index(sev)
        except ValueError:
            return len(_SEVERITY_ORDER)

    return sorted(rows, key=_sev_key)


def _esc(s: str) -> str:
    """Minimal SQL string escaping (single-quote doubling)."""
    return s.replace("'", "''")
