"""Finding lifecycle eval scenarios — Step E.3.

Prerequisite for Phase C gate.  Verifies that the ReviewFinding write-back
path (record → query → resolve → verify) works correctly.
"""

from __future__ import annotations

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
            cypher=(f"MATCH (rf:ReviewFinding) WHERE rf.id = '{fid}' RETURN rf.id, rf.status"),
            sql=f'SELECT id AS "rf.id", status AS "rf.status" '
            f"FROM ReviewFinding WHERE id = '{fid}'",
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
                f'SELECT f.path AS "f.path" FROM GRAPH_TABLE(agentscaffold_graph '
                f"  MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File) "
                f"  WHERE rf.id = '{fid}' "
                f"  COLUMNS (f.path) "
                f") t"
            )
        else:
            sql = None  # unused for kuzu

        rows = ql(
            store,
            cypher=(
                f"MATCH (rf:ReviewFinding)-[:FINDING_ABOUT_FILE]->(f:File) "
                f"WHERE rf.id = '{fid}' RETURN f.path"
            ),
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
        assert (
            has_edge
        ), f"Expected FINDING_ABOUT_FILE edge to libs/data/router.py, got: {edge_paths}"
