"""DuckPGQ consistency scenarios.

Verifies that DuckPGQ produces deterministic, correct results across
two independent indexing runs of the same sim project.
"""

from __future__ import annotations

from eval.runner import EvalResult, collect_result


def _node_counts(store) -> dict[str, int]:
    """Return {node_label: count} for File, Function, and Class."""
    from agentscaffold.graph.query_compat import ql_scalar

    return {
        "File": ql_scalar(
            store,
            cypher="MATCH (f:File) RETURN count(f)",
            sql="SELECT count(*) FROM File",
        )
        or 0,
        "Function": ql_scalar(
            store,
            cypher="MATCH (fn:Function) RETURN count(fn)",
            sql="SELECT count(*) FROM Function",
        )
        or 0,
        "Class": ql_scalar(
            store,
            cypher="MATCH (c:Class) RETURN count(c)",
            sql="SELECT count(*) FROM Class",
        )
        or 0,
    }


class TestDuckPGQConsistency:
    """Verifies DuckPGQ produces consistent, correct results across independent index runs."""

    def test_node_count_consistency(self, indexed_sim, indexed_sim_duckdb):
        """File, Function, Class node counts must be identical across two independent runs."""
        _, store_a, _ = indexed_sim
        _, store_b, _ = indexed_sim_duckdb

        counts_a = _node_counts(store_a)
        counts_b = _node_counts(store_b)

        mismatches = {
            label: (counts_a[label], counts_b[label])
            for label in counts_a
            if counts_a[label] != counts_b[label]
        }

        passed = len(mismatches) == 0
        collect_result(
            EvalResult(
                scenario="duckpgq_node_count_consistency",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Identical node counts across two independent indexing runs",
                actual=(
                    f"Run A: {counts_a}, Run B: {counts_b}"
                    + (f", Mismatches: {mismatches}" if mismatches else "")
                ),
                category="consistency",
            )
        )
        assert not mismatches, f"Node count divergence across runs: {mismatches}"

    def test_query_result_consistency(self, indexed_sim, indexed_sim_duckdb):
        """5 canonical queries should return identical result sets across two independent runs."""
        _, store_a, _ = indexed_sim
        _, store_b, _ = indexed_sim_duckdb

        from agentscaffold.graph.query_compat import ql

        canonical_queries = [
            (
                "MATCH (f:File) WHERE f.language = 'python' RETURN f.path ORDER BY f.path LIMIT 5",
                (
                    'SELECT path AS "f.path" FROM File'
                    " WHERE language = 'python' ORDER BY path LIMIT 5"
                ),
                "f.path",
            ),
            (
                "MATCH (fn:Function) RETURN fn.name ORDER BY fn.name LIMIT 5",
                'SELECT name AS "fn.name" FROM Function ORDER BY name LIMIT 5',
                "fn.name",
            ),
            (
                "MATCH (c:Class) RETURN c.name ORDER BY c.name LIMIT 5",
                'SELECT name AS "c.name" FROM Class ORDER BY name LIMIT 5',
                "c.name",
            ),
            (
                "MATCH (p:Plan) RETURN p.number ORDER BY p.number LIMIT 5",
                'SELECT number AS "p.number" FROM Plan ORDER BY number LIMIT 5',
                "p.number",
            ),
            (
                "MATCH (c:Contract) RETURN c.name ORDER BY c.name LIMIT 5",
                'SELECT name AS "c.name" FROM Contract ORDER BY name LIMIT 5',
                "c.name",
            ),
        ]

        divergences: list[str] = []
        for cypher, sql, key in canonical_queries:
            rows_a = ql(store_a, cypher=cypher, sql=sql)
            rows_b = ql(store_b, cypher=cypher, sql=sql)
            vals_a = sorted(str(r.get(key, "")) for r in rows_a)
            vals_b = sorted(str(r.get(key, "")) for r in rows_b)
            if vals_a != vals_b:
                divergences.append(f"Query diverged on '{cypher[:50]}...': A={vals_a}, B={vals_b}")

        passed = len(divergences) == 0
        collect_result(
            EvalResult(
                scenario="duckpgq_query_consistency",
                passed=passed,
                score=1.0 - len(divergences) / len(canonical_queries),
                expected="All 5 canonical queries return identical result sets",
                actual=(
                    f"{len(canonical_queries) - len(divergences)}/{len(canonical_queries)} match"
                ),
                observations=divergences[:5],
                category="consistency",
            )
        )
        assert not divergences, "Query result divergences:\n" + "\n".join(divergences)

    def test_search_consistency(self, indexed_sim, indexed_sim_duckdb):
        """Router file search should return identical results across two independent runs."""
        _, store_a, _ = indexed_sim
        _, store_b, _ = indexed_sim_duckdb

        from agentscaffold.graph.query_compat import ql

        cypher = (
            "MATCH (f:File) WHERE f.path CONTAINS 'router' RETURN f.path ORDER BY f.path LIMIT 5"
        )
        sql = "SELECT path AS \"f.path\" FROM File WHERE path LIKE '%router%' ORDER BY path LIMIT 5"

        rows_a = ql(store_a, cypher=cypher, sql=sql)
        rows_b = ql(store_b, cypher=cypher, sql=sql)

        paths_a = sorted(r.get("f.path", "") for r in rows_a)
        paths_b = sorted(r.get("f.path", "") for r in rows_b)

        passed = paths_a == paths_b
        collect_result(
            EvalResult(
                scenario="duckpgq_search_consistency",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Identical top-5 paths for router search across runs",
                actual=f"Run A: {paths_a}, Run B: {paths_b}",
                category="consistency",
            )
        )
        assert passed, f"Search result divergence: A={paths_a}, B={paths_b}"

    def test_finding_write_read(self, indexed_sim):
        """record_finding() + get_open_findings() round-trip on DuckPGQ."""
        _, store, _ = indexed_sim

        from agentscaffold.graph.findings import get_open_findings, record_finding

        result = record_finding(
            store,
            plan_number=9999,
            review_type="consistency_test",
            category="test",
            finding="DuckPGQ consistency test finding",
            severity="low",
        )

        findings = get_open_findings(store, plan_number=9999)

        ok = len(findings) > 0 and result.get("id") in {f.get("rf.id") for f in findings}

        collect_result(
            EvalResult(
                scenario="duckpgq_finding_write_read",
                passed=ok,
                score=1.0 if ok else 0.0,
                expected="Finding written and readable on DuckPGQ",
                actual=f"ok={ok}, findings_count={len(findings)}",
                observations=[
                    f"Finding ID: {result.get('id')}",
                    f"Open findings for plan 9999: {len(findings)}",
                ],
                category="consistency",
            )
        )
        assert ok, f"DuckPGQ finding round-trip failed: {findings}"

    def test_incremental_changeset_detection(self, tmp_path):
        """DuckPGQ incremental indexing should detect a newly added file."""
        import shutil

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline
        from eval.conftest import SIM_PROJECT

        root = tmp_path / "consistency_check"
        shutil.copytree(SIM_PROJECT, root)
        db_path = root / ".scaffold" / "graph_consistency.duckdb"
        config = ScaffoldConfig()
        config.graph = GraphConfig(
            db_path=str(db_path),
            backend="duckpgq",
        )
        run_pipeline(root, config)

        new_file = root / "libs" / "consistency_check.py"
        new_file.write_text("def consistency_check(): pass\n")
        summary = run_pipeline(root, config, incremental=True)
        added = summary.get("changeset", {}).get("added", [])

        new_detected = {p for p in added if "consistency_check" in p}
        passed = bool(new_detected)

        collect_result(
            EvalResult(
                scenario="duckpgq_incremental_changeset",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="DuckPGQ detects consistency_check.py as added",
                actual=f"DuckPGQ added: {new_detected}",
                category="consistency",
            )
        )
        assert new_detected, f"DuckPGQ did not detect new file in changeset: {added}"
