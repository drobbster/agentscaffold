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


def _sync_governance(store: GraphBackend) -> None:
    """Re-serialize governance to the git-backed artifact if write-through is on."""
    from agentscaffold.graph.governance_store import sync_if_enabled  # noqa: PLC0415

    sync_if_enabled(store)


def _finding_id(
    plan_number: int,
    review_type: str,
    category: str,
    finding: str,
    project: str | None = None,
) -> str:
    """Derive a deterministic, project-scoped ID from the finding content.

    Plan numbers are NOT unique across projects in a multi-project workspace, so
    the project is folded into the hash key to prevent cross-project finding-ID
    collisions. A falsy *project* reproduces the original (unscoped) ID for
    single-project back-compat.
    """
    prefix = f"{project}::" if project else ""
    key = f"{prefix}finding::{plan_number}::{review_type}::{category}::{finding[:64]}"
    return "rf::" + hashlib.sha1(key.encode()).hexdigest()[:12]  # noqa: S324


def is_malformed_finding(finding: str) -> bool:
    """True when a finding body is a mid-sentence fragment rather than an assertion.

    Defence in depth behind the Plan 250 anchoring fix. Anchoring stops the known
    producer of fragments, but the store outlives any one parser version and a
    consuming repo can call this path directly, so the write side checks the shape
    of what it is asked to persist.

    The signature of the defect is a body that starts mid-sentence: a closing
    bracket or punctuation left behind when the capture began mid-line, or a
    dangling conjunction. Deliberately narrow -- it rejects shapes no human would
    write, not merely unusual ones, because a false reject silently loses a real
    finding.

    A leading backtick needs care rather than a flat reject: findings that open
    with an inline code span (```` `_FINDING_RE` is unanchored ````) are ordinary
    and legitimate. What gives the fragment away is the *whitespace* after that
    backtick -- an opening code span is followed by the code, never by a space,
    so a leading backtick-then-space is the closing half of a span whose opening
    half was left behind on the line the capture started in the middle of.

    Counting backticks for balance instead looks appealing and is wrong: a
    fragment that happens to carry another backtick pair (a trailing fence, say)
    balances out and slips through. Observed on ``rf::8ecd53cc08b9``.
    """
    body = finding.strip()
    if not body:
        return True
    if body[0] in ")]},.;:!?":
        return True
    if body[0] == "`" and (len(body) == 1 or body[1].isspace()):
        return True
    return body.startswith("and ") or body.startswith("or ") or body.startswith("but ")


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
    project: str | None = None,
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
        project: Owning project in a multi-project workspace; stamps the
            ``project`` column and scopes the deterministic ID and File lookups.
            None (single-project) keeps the original unscoped behavior.

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()
    finding_id = _finding_id(plan_number, review_type, category, finding, project)
    now = datetime.now(timezone.utc).isoformat()
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""

    props: dict[str, Any] = {
        "id": finding_id,
        "reviewType": review_type,
        "planNumber": plan_number,
        "severity": severity,
        "category": category,
        "finding": finding,
        "resolution": "",
        "status": "open",
        "project": project or "",
    }

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.create_node("ReviewFinding", props)

        # Link to files (scoped to the owning project: file paths are not unique
        # across projects in a multi-project workspace).
        for fp in file_paths or []:
            rows = store.query(f"SELECT id FROM File WHERE path = '{_esc(fp)}'{proj_filter}")
            file_id = rows[0]["id"] if rows else None

            if file_id:
                store.create_edge(
                    "FINDING_ABOUT_FILE", "ReviewFinding", finding_id, "File", file_id
                )

        # Link to functions
        for fn_id in function_ids or []:
            store.create_edge("FINDING_ABOUT_FUNC", "ReviewFinding", finding_id, "Function", fn_id)

        _sync_governance(store)

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


def _returning_id(rows: list[dict[str, Any]]) -> str | None:
    """Id from UPDATE ... RETURNING, or None.

    DuckDB UPDATE without RETURNING yields ``[{Count: 0}]`` -- a non-empty list.
    Only a row with an ``id`` key counts as a hit.
    """
    for row in rows:
        rid = row.get("id")
        if rid:
            return str(rid)
    return None


def _id_candidates(raw_id: str, project: str | None) -> list[str]:
    """Exact-id forms to try: as given, plus Plan 225 qualified/unqualified."""
    raw_id = raw_id.strip()
    if not raw_id:
        return []
    out = [raw_id]
    if not project:
        return out
    from agentscaffold.graph.scoping import qualify_id, unqualify_id  # noqa: PLC0415

    prefix = f"{project}::"
    if not raw_id.startswith(prefix):
        qualified = qualify_id(project, raw_id)
        if qualified not in out:
            out.append(qualified)
    _head, rest = unqualify_id(raw_id, known_projects={project})
    if rest and rest not in out:
        out.append(rest)
    return out


def resolve_finding(
    store: GraphBackend,
    finding_id: str,
    *,
    resolution: str,
    project: str | None = None,
) -> dict[str, Any]:
    """Mark a ReviewFinding as resolved.

    A miss returns ``status="not_found"`` and does not fabricate success.
    ``finding_id`` may be the canonical ``rf::`` hash or its project-qualified
    form. There is no human-id / title lookup (finding bodies are free text).

    Args:
        store: Open GraphBackend instance.
        finding_id: The ID of the finding to resolve.
        resolution: Human-readable resolution description.
        project: When set, only resolves the finding if it belongs to this
            project (defense-in-depth against cross-project resolves).

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()
    caller_id = (finding_id or "").strip()
    candidates = _id_candidates(caller_id, project)

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        canonical_id = None
        if candidates:
            placeholders = ", ".join(["?"] * len(candidates))
            params: dict[str, Any] = {f"id{i}": v for i, v in enumerate(candidates)}
            sql = f"SELECT id FROM ReviewFinding WHERE id IN ({placeholders})"
            if project:
                sql += " AND project = ?"
                params["project"] = project
            hits = store.query(sql, params)
            hit_ids = list(dict.fromkeys(str(r["id"]) for r in hits if r.get("id")))
            if len(hit_ids) == 1:
                canonical_id = hit_ids[0]
            elif len(hit_ids) > 1:
                elapsed_ms = (time.monotonic() - t0) * 1000
                return {
                    "id": caller_id,
                    "status": "ambiguous",
                    "candidates": [{"id": i} for i in hit_ids],
                    "elapsed_ms": elapsed_ms,
                }

        if canonical_id is None:
            elapsed_ms = (time.monotonic() - t0) * 1000
            return {"id": caller_id, "status": "not_found", "elapsed_ms": elapsed_ms}

        upd: dict[str, Any] = {"resolution": resolution, "id": canonical_id}
        upd_sql = "UPDATE ReviewFinding SET status = 'resolved', resolution = ? WHERE id = ?"
        if project:
            upd_sql += " AND project = ?"
            upd["project"] = project
        upd_sql += " RETURNING id"
        rows = store.query(upd_sql, upd)
        matched = _returning_id(rows)
        if matched is None:
            elapsed_ms = (time.monotonic() - t0) * 1000
            return {"id": caller_id, "status": "not_found", "elapsed_ms": elapsed_ms}

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "id": matched,
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
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Return open ReviewFindings, optionally filtered by plan or file.

    Args:
        store: Open GraphBackend instance.
        plan_number: Filter by plan number.
        file_path: Filter by related file path.
        limit: Maximum number of findings to return.
        project: When set, only return findings stamped with this project
            (multi-project scoping). None returns findings regardless of project.

    Returns:
        List of finding dicts, sorted by severity then creation order.
    """
    from agentscaffold.graph.query_compat import ql  # noqa: PLC0415

    if file_path:
        rf_proj_filter = f" AND rf.project = '{_esc(project)}'" if project else ""
        rows = store.query(
            f'SELECT t.rf_id AS "rf.id", t.rf_reviewType AS "rf.reviewType",'
            f' t.rf_planNumber AS "rf.planNumber", t.rf_severity AS "rf.severity",'
            f' t.rf_category AS "rf.category", t.rf_finding AS "rf.finding"'
            f" FROM GRAPH_TABLE(agentscaffold_graph"
            f"   MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File)"
            f"   WHERE rf.status = 'open' AND f.path = '{_esc(file_path)}'{rf_proj_filter}"
            f"   COLUMNS (rf.id AS rf_id, rf.reviewType AS rf_reviewType,"
            f"            rf.planNumber AS rf_planNumber, rf.severity AS rf_severity,"
            f"            rf.category AS rf_category, rf.finding AS rf_finding)"
            f" ) t LIMIT {limit}"
        )
    else:
        plan_filter = f" AND planNumber = {plan_number}" if plan_number is not None else ""
        proj_filter = f" AND project = '{_esc(project)}'" if project else ""
        rows = ql(
            store,
            sql=(
                f'SELECT id AS "rf.id", reviewType AS "rf.reviewType",'
                f' planNumber AS "rf.planNumber", severity AS "rf.severity",'
                f' category AS "rf.category", finding AS "rf.finding"'
                f" FROM ReviewFinding WHERE status = 'open'{plan_filter}{proj_filter} LIMIT {limit}"
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


def record_findings_batch(
    store: GraphBackend,
    *,
    plan_number: int,
    review_type: str,
    findings: list[dict[str, Any]],
    project: str | None = None,
) -> dict[str, Any]:
    """Record multiple ReviewFinding nodes in a single transaction.

    Each item in ``findings`` must have ``category`` and ``finding`` keys.
    Optional keys per item: ``severity``, ``file_paths``, ``function_ids``.

    Args:
        store: Open GraphBackend instance.
        plan_number: The plan this batch of findings relates to.
        review_type: Review type label (e.g. "quant_architect").
        findings: List of finding dicts.
        project: Owning project in a multi-project workspace; stamps the
            ``project`` column and scopes the deterministic IDs and File lookups.

    Returns:
        Dict with ``ids``, ``count``, and ``elapsed_ms``.
    """
    t0 = time.monotonic()
    if not findings:
        return {"ids": [], "count": 0, "elapsed_ms": 0.0}

    ids: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.execute("BEGIN TRANSACTION")
        try:
            for item in findings:
                category = item.get("category", "general")
                finding_text = item.get("finding", "")
                severity = item.get("severity", "medium")
                finding_id = _finding_id(plan_number, review_type, category, finding_text, project)

                props: dict[str, Any] = {
                    "id": finding_id,
                    "reviewType": review_type,
                    "planNumber": plan_number,
                    "severity": severity,
                    "category": category,
                    "finding": finding_text,
                    "resolution": "",
                    "status": "open",
                    "project": project or "",
                }
                store.create_node("ReviewFinding", props)

                for fp in item.get("file_paths") or []:
                    rows = store.query(
                        f"SELECT id FROM File WHERE path = '{_esc(fp)}'{proj_filter}"
                    )
                    file_id = rows[0]["id"] if rows else None
                    if file_id:
                        store.create_edge(
                            "FINDING_ABOUT_FILE", "ReviewFinding", finding_id, "File", file_id
                        )

                for fn_id in item.get("function_ids") or []:
                    store.create_edge(
                        "FINDING_ABOUT_FUNC", "ReviewFinding", finding_id, "Function", fn_id
                    )

                ids.append(finding_id)

            store.execute("COMMIT")
        except Exception:
            store.execute("ROLLBACK")
            raise

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "ids": ids,
        "count": len(ids),
        "plan_number": plan_number,
        "review_type": review_type,
        "elapsed_ms": elapsed_ms,
        "created_at": now,
    }


_FINDING_EDGE_TABLES: tuple[str, ...] = (
    "FINDING_ABOUT_FILE",
    "FINDING_ABOUT_FUNC",
    "FINDING_LED_TO",
    "FINDING_ADDRESSED_BY",
)


def delete_finding(store: GraphBackend, finding_id: str) -> None:
    """Delete a ReviewFinding and its outgoing edges.

    Used by selective pruning. Removes the finding's edges first (src = id),
    then the node itself. Edge tables that do not exist are ignored.
    """
    fid = _esc(finding_id)
    for edge_table in _FINDING_EDGE_TABLES:
        try:
            store.execute(f"DELETE FROM {edge_table} WHERE src = '{fid}'")
        except Exception:  # noqa: BLE001 - edge table may be absent
            pass
    store.execute(f"DELETE FROM ReviewFinding WHERE id = '{fid}'")


def _esc(s: str) -> str:
    """Minimal SQL string escaping (single-quote doubling)."""
    return s.replace("'", "''")
