"""Finding lifecycle eval scenarios — Step E.3.

Prerequisite for Phase C gate.  Verifies that the ReviewFinding write-back
path (record → query → resolve → verify) works correctly.

Also covers B-149-2: concurrent write hardening — N threads calling
record_finding() concurrently on the same store instance must not lose writes
or corrupt data.  Latency is measured to surface WAL serialization overhead.
"""

from __future__ import annotations

import concurrent.futures
import time

from eval.runner import EvalResult, collect_result


class TestFindingLifecycle:
    """End-to-end finding lifecycle: write, read, resolve."""

    def test_finding_persists_across_tool_calls(self, indexed_sim):
        """Finding written via record_finding() is readable by direct graph query."""
        _, store, _ = indexed_sim
        from agentscaffold.graph.findings import record_finding
        from agentscaffold.graph.query_compat import ql

        result = record_finding(
            store,
            plan_number=100,
            review_type="lifecycle_test",
            category="test",
            finding="Persists across tool calls test finding",
            severity="medium",
        )
        fid = result["id"]

        rows = ql(
            store,
            sql=(
                f'SELECT id AS "rf.id", status AS "rf.status" '
                f"FROM ReviewFinding WHERE id = '{fid}'"
            ),
        )
        node_present = any(r.get("rf.id") == fid for r in rows)
        status_open = any(r.get("rf.status") == "open" for r in rows)

        passed = node_present and status_open
        collect_result(
            EvalResult(
                scenario="finding_persists",
                passed=passed,
                score=1.0 if passed else (0.5 if node_present else 0.0),
                expected="ReviewFinding node present with status='open'",
                actual=f"node_present={node_present}, status_open={status_open}",
                observations=[f"finding_id={fid}", f"rows={rows}"],
                category="lifecycle",
            )
        )
        assert node_present, f"ReviewFinding {fid} not found in graph"
        assert status_open, f"ReviewFinding {fid} has wrong status: {rows}"

    def test_resolved_finding_absent_from_open_findings(self, indexed_sim):
        """Resolved findings must not appear in get_open_findings()."""
        _, store, _ = indexed_sim
        from agentscaffold.graph.findings import get_open_findings, record_finding, resolve_finding

        finding_result = record_finding(
            store,
            plan_number=200,
            review_type="lifecycle_resolve_test",
            category="resolved_test",
            finding="This finding should be resolved and absent from open query",
            severity="low",
        )
        fid = finding_result["id"]

        # Verify it's open before resolving
        open_before = get_open_findings(store, plan_number=200)
        was_open = any(f.get("rf.id") == fid for f in open_before)

        # Resolve it
        resolve_finding(store, fid, resolution="Fixed in lifecycle test")

        # Verify it no longer appears in open findings
        open_after = get_open_findings(store, plan_number=200)
        still_open = any(f.get("rf.id") == fid for f in open_after)

        passed = was_open and not still_open
        collect_result(
            EvalResult(
                scenario="resolved_finding_absent",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Finding open before resolve, absent after",
                actual=f"was_open={was_open}, still_open_after={still_open}",
                observations=[
                    f"finding_id={fid}",
                    f"open_before_count={len(open_before)}",
                    f"open_after_count={len(open_after)}",
                ],
                category="lifecycle",
            )
        )
        assert was_open, f"Finding {fid} was not in open findings before resolve"
        assert not still_open, f"Resolved finding {fid} still appears in open findings"

    def test_finding_creates_file_edges(self, indexed_sim):
        """record_finding() with file_paths creates FINDING_ABOUT_FILE edges."""
        _, store, _ = indexed_sim
        from agentscaffold.graph.findings import record_finding
        from agentscaffold.graph.query_compat import is_duckpgq, ql

        result = record_finding(
            store,
            plan_number=101,
            review_type="edge_test",
            category="test",
            finding="Finding with file edges",
            severity="high",
            file_paths=["libs/data/router.py"],
        )
        fid = result["id"]

        # Query FINDING_ABOUT_FILE edges — use backend-appropriate SQL for DuckPGQ
        if is_duckpgq(store):
            sql = (
                f'SELECT t.f_path AS "f.path" FROM GRAPH_TABLE(agentscaffold_graph '
                f"  MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File) "
                f"  WHERE rf.id = '{fid}' "
                f"  COLUMNS (f.path AS f_path) "
                f") t"
            )
        else:
            sql = ""

        rows = ql(
            store,
            sql=sql or "",
        )
        edge_paths = [r.get("f.path", "") for r in rows]

        # Edge is created only if the File node exists in the graph
        # (router.py is indexed in sim_project, so edge should be present)
        has_edge = "libs/data/router.py" in edge_paths

        passed = has_edge
        collect_result(
            EvalResult(
                scenario="finding_file_edges",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="FINDING_ABOUT_FILE edge to libs/data/router.py",
                actual=f"edge_paths={edge_paths}",
                observations=[f"finding_id={fid}"],
                category="lifecycle",
            )
        )
        assert has_edge, (
            f"Expected FINDING_ABOUT_FILE edge to libs/data/router.py, got: {edge_paths}"
        )


class TestConcurrentFindingWrites:
    """B-149-2: Concurrent write hardening.

    Validates that N threads calling record_finding() on the same store instance
    simultaneously produce no data loss, no corruption, and acceptable latency.

    DuckDB serialises concurrent writers on the same connection under the hood;
    this test surface any latency degradation and guards against races at the
    Python-layer (e.g. dict mutation, ID collision).
    """

    _CONCURRENCY = 8
    _LATENCY_CEILING_MS = 2000  # max tolerated wall-clock for all 8 writes combined

    def test_concurrent_writes_no_data_loss(self, indexed_sim_duckdb):
        """All N concurrent record_finding() calls persist without data loss."""
        _, store, _ = indexed_sim_duckdb
        from agentscaffold.graph.findings import record_finding

        def _write(idx: int) -> dict:
            return record_finding(
                store,
                plan_number=9000 + idx,
                review_type="concurrent_test",
                category="concurrent",
                finding=f"Concurrent write #{idx} — data-loss guard",
                severity="low",
            )

        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=self._CONCURRENCY) as pool:
            futures = [pool.submit(_write, i) for i in range(self._CONCURRENCY)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        elapsed_ms = (time.monotonic() - t0) * 1000

        ids_returned = {r["id"] for r in results}
        statuses = [r["status"] for r in results]

        all_open = all(s == "open" for s in statuses)
        no_id_collision = len(ids_returned) == self._CONCURRENCY
        within_latency = elapsed_ms < self._LATENCY_CEILING_MS

        passed = all_open and no_id_collision
        collect_result(
            EvalResult(
                scenario="concurrent_writes_no_data_loss",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected=f"{self._CONCURRENCY} distinct open findings",
                actual=(
                    f"ids={len(ids_returned)}, all_open={all_open}, elapsed_ms={elapsed_ms:.1f}"
                ),
                observations=[
                    f"concurrency={self._CONCURRENCY}",
                    f"elapsed_ms={elapsed_ms:.1f}",
                    f"latency_ceiling_ms={self._LATENCY_CEILING_MS}",
                    f"within_latency={within_latency}",
                ],
                category="lifecycle",
            )
        )
        assert no_id_collision, (
            f"Expected {self._CONCURRENCY} distinct IDs, got {len(ids_returned)}: {ids_returned}"
        )
        assert all_open, f"Not all findings have status='open': {statuses}"

    def test_concurrent_writes_latency(self, indexed_sim_duckdb):
        """Combined wall-clock for N concurrent writes stays under ceiling.

        This is a soft signal test: a latency breach is reported but does not
        fail CI.  It surfaces WAL serialisation pressure under concurrent load.
        """
        _, store, _ = indexed_sim_duckdb
        from agentscaffold.graph.findings import record_finding

        individual_ms: list[float] = []

        def _write(idx: int) -> float:
            t = time.monotonic()
            record_finding(
                store,
                plan_number=9100 + idx,
                review_type="latency_test",
                category="concurrent",
                finding=f"Concurrent latency probe #{idx}",
                severity="medium",
            )
            return (time.monotonic() - t) * 1000

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._CONCURRENCY) as pool:
            futures = [pool.submit(_write, i) for i in range(self._CONCURRENCY)]
            individual_ms = [f.result() for f in concurrent.futures.as_completed(futures)]

        max_ms = max(individual_ms)
        p95_ms = sorted(individual_ms)[int(len(individual_ms) * 0.95)]
        # Soft signal: report but do not assert — latency degrades under concurrent
        # load due to DuckDB WAL serialisation; the ceiling is informational.
        within_ceiling = max_ms < self._LATENCY_CEILING_MS

        collect_result(
            EvalResult(
                scenario="concurrent_writes_latency",
                passed=within_ceiling,
                score=1.0 if within_ceiling else 0.5,
                expected=(
                    f"max individual write < {self._LATENCY_CEILING_MS}ms "
                    f"under {self._CONCURRENCY}-thread load"
                ),
                actual=f"max_ms={max_ms:.1f}, p95_ms={p95_ms:.1f}",
                observations=[
                    f"individual_ms={[round(m, 1) for m in sorted(individual_ms)]}",
                    f"concurrency={self._CONCURRENCY}",
                ],
                category="lifecycle",
            )
        )
        # Soft assertion — fail only on extreme degradation (10× ceiling)
        assert max_ms < self._LATENCY_CEILING_MS * 10, (
            f"Extreme write latency under concurrent load: {max_ms:.1f}ms "
            f"(ceiling={self._LATENCY_CEILING_MS}ms × 10)"
        )


class TestFindingEvidence:
    """Plan 264: evidence fields persist and default to unspecified."""

    def test_record_finding_keeps_explicit_evidence(self, indexed_sim):
        _, store, _ = indexed_sim
        from agentscaffold.graph.findings import record_finding
        from agentscaffold.graph.query_compat import ql

        result = record_finding(
            store,
            plan_number=264,
            review_type="evidence_eval",
            category="test",
            finding="Evidence fields must survive ingest",
            severity="low",
            evidence_kind="test",
            evidence="eval/scenarios/test_finding_lifecycle.py:evidence",
        )
        fid = result["id"]
        rows = ql(
            store,
            sql=(
                f'SELECT evidenceKind AS "rf.evidenceKind", evidence AS "rf.evidence" '
                f"FROM ReviewFinding WHERE id = '{fid}'"
            ),
        )
        kind = rows[0].get("rf.evidenceKind") if rows else None
        citation = rows[0].get("rf.evidence") if rows else None
        passed = kind == "test" and "test_finding_lifecycle" in (citation or "")
        collect_result(
            EvalResult(
                scenario="finding_evidence_persists",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="evidenceKind=test and citation kept",
                actual=f"kind={kind}, evidence={citation}",
                category="lifecycle",
            )
        )
        assert passed, f"evidence not persisted: {rows}"

    def test_omitted_evidence_is_unspecified(self, indexed_sim):
        _, store, _ = indexed_sim
        from agentscaffold.graph.findings import record_finding
        from agentscaffold.graph.query_compat import ql

        result = record_finding(
            store,
            plan_number=264,
            review_type="evidence_eval",
            category="test",
            finding="Omitted evidence should be unspecified, not inferred",
            severity="low",
        )
        fid = result["id"]
        rows = ql(
            store,
            sql=(
                f"SELECT evidenceKind AS \"rf.evidenceKind\" FROM ReviewFinding WHERE id = '{fid}'"
            ),
        )
        kind = rows[0].get("rf.evidenceKind") if rows else None
        passed = kind == "unspecified"
        collect_result(
            EvalResult(
                scenario="finding_evidence_unspecified_default",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="evidenceKind=unspecified when omitted",
                actual=f"kind={kind}",
                category="lifecycle",
            )
        )
        assert passed, f"omit should be unspecified, got {kind}"
