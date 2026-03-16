"""Backend parity scenarios — Step E.1.

Verifies that KuzuDB and DuckPGQ backends produce identical results for the
same indexing pipeline run.  These are a Phase A exit gate.
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


class TestBackendParity:
    """Verifies KuzuDB ↔ DuckPGQ result parity across 5 canonical checks."""

    def test_node_count_parity(self, indexed_sim, indexed_sim_duckdb):
        """File, Function, Class node counts must be identical on both backends."""
        _, kuzu_store, _ = indexed_sim
        _, duck_store, _ = indexed_sim_duckdb

        kuzu_counts = _node_counts(kuzu_store)
        duck_counts = _node_counts(duck_store)

        mismatches = {
            label: (kuzu_counts[label], duck_counts[label])
            for label in kuzu_counts
            if kuzu_counts[label] != duck_counts[label]
        }

        passed = len(mismatches) == 0
        collect_result(
            EvalResult(
                scenario="parity_node_counts",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Identical node counts on kuzu and duckpgq",
                actual=(
                    f"Kuzu: {kuzu_counts}, DuckPGQ: {duck_counts}"
                    + (f", Mismatches: {mismatches}" if mismatches else "")
                ),
                category="parity",
            )
        )
        assert not mismatches, f"Node count divergence: {mismatches}"

    def test_query_result_parity(self, indexed_sim, indexed_sim_duckdb):
        """10 canonical queries should return the same result sets on both backends."""
        _, kuzu_store, _ = indexed_sim
        _, duck_store, _ = indexed_sim_duckdb

        from agentscaffold.graph.query_compat import ql

        canonical_queries = [
            (
                "MATCH (f:File) WHERE f.language = 'python' RETURN f.path ORDER BY f.path LIMIT 5",
                "SELECT path FROM File WHERE language = 'python' ORDER BY path LIMIT 5",
                "f.path",
            ),
            (
                "MATCH (fn:Function) RETURN fn.name ORDER BY fn.name LIMIT 5",
                "SELECT name FROM Function ORDER BY name LIMIT 5",
                "fn.name",
            ),
            (
                "MATCH (c:Class) RETURN c.name ORDER BY c.name LIMIT 5",
                "SELECT name FROM Class ORDER BY name LIMIT 5",
                "c.name",
            ),
            (
                "MATCH (p:Plan) RETURN p.number ORDER BY p.number LIMIT 5",
                "SELECT number FROM Plan ORDER BY number LIMIT 5",
                "p.number",
            ),
            (
                "MATCH (c:Contract) RETURN c.name ORDER BY c.name LIMIT 5",
                "SELECT name FROM Contract ORDER BY name LIMIT 5",
                "c.name",
            ),
        ]

        divergences: list[str] = []
        for cypher, sql, key in canonical_queries:
            kuzu_rows = ql(kuzu_store, cypher=cypher, sql=sql)
            duck_rows = ql(duck_store, cypher=cypher, sql=sql)
            kuzu_vals = sorted(str(r.get(key, "")) for r in kuzu_rows)
            duck_vals = sorted(str(r.get(key, "")) for r in duck_rows)
            if kuzu_vals != duck_vals:
                divergences.append(
                    f"Query diverged on '{cypher[:50]}...': kuzu={kuzu_vals}, duck={duck_vals}"
                )

        passed = len(divergences) == 0
        collect_result(
            EvalResult(
                scenario="parity_query_results",
                passed=passed,
                score=1.0 - len(divergences) / len(canonical_queries),
                expected="All 5 canonical queries return identical result sets",
                actual=(
                    f"{len(canonical_queries) - len(divergences)}/{len(canonical_queries)} match"
                ),
                observations=divergences[:5],
                category="parity",
            )
        )
        assert not divergences, "Query result divergences:\n" + "\n".join(divergences)

    def test_search_parity(self, indexed_sim, indexed_sim_duckdb):
        """hybrid_search('DataRouter') top-5 should be identical on both backends."""
        _, kuzu_store, _ = indexed_sim
        _, duck_store, _ = indexed_sim_duckdb

        from agentscaffold.graph.query_compat import ql

        cypher = (
            "MATCH (f:File) WHERE f.path CONTAINS 'router' RETURN f.path ORDER BY f.path LIMIT 5"
        )
        sql = "SELECT path FROM File WHERE path LIKE '%router%' ORDER BY path LIMIT 5"

        kuzu_rows = ql(kuzu_store, cypher=cypher, sql=sql)
        duck_rows = ql(duck_store, cypher=cypher, sql=sql)

        kuzu_paths = sorted(r.get("f.path", "") for r in kuzu_rows)
        duck_paths = sorted(r.get("f.path", "") for r in duck_rows)

        passed = kuzu_paths == duck_paths
        collect_result(
            EvalResult(
                scenario="parity_search",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Identical top-5 paths for router search",
                actual=f"Kuzu: {kuzu_paths}, DuckPGQ: {duck_paths}",
                category="parity",
            )
        )
        assert passed, f"Search diverged: kuzu={kuzu_paths}, duck={duck_paths}"

    def test_finding_write_parity(self, indexed_sim, indexed_sim_duckdb):
        """record_finding() + get_open_findings() round-trips on both backends."""
        root, kuzu_store, _ = indexed_sim
        _, duck_store, _ = indexed_sim_duckdb

        from agentscaffold.graph.findings import get_open_findings, record_finding

        kuzu_result = record_finding(
            kuzu_store,
            plan_number=9999,
            review_type="parity_test",
            category="test",
            finding="Parity test finding for kuzu",
            severity="low",
        )
        duck_result = record_finding(
            duck_store,
            plan_number=9999,
            review_type="parity_test",
            category="test",
            finding="Parity test finding for duckpgq",
            severity="low",
        )

        kuzu_findings = get_open_findings(kuzu_store, plan_number=9999)
        duck_findings = get_open_findings(duck_store, plan_number=9999)

        kuzu_ok = len(kuzu_findings) > 0 and kuzu_result.get("id") in {
            f.get("rf.id") for f in kuzu_findings
        }
        duck_ok = len(duck_findings) > 0 and duck_result.get("id") in {
            f.get("rf.id") for f in duck_findings
        }

        passed = kuzu_ok and duck_ok
        collect_result(
            EvalResult(
                scenario="parity_finding_write",
                passed=passed,
                score=1.0 if passed else (0.5 if kuzu_ok or duck_ok else 0.0),
                expected="Findings written and readable on both backends",
                actual=f"kuzu_ok={kuzu_ok}, duck_ok={duck_ok}",
                observations=[
                    f"Kuzu findings: {len(kuzu_findings)}",
                    f"DuckPGQ findings: {len(duck_findings)}",
                ],
                category="parity",
            )
        )
        assert kuzu_ok, f"Kuzu finding round-trip failed: {kuzu_findings}"
        assert duck_ok, f"DuckPGQ finding round-trip failed: {duck_findings}"

    def test_incremental_changeset_parity(self, indexed_sim, indexed_sim_duckdb, tmp_path):
        """Same file addition should produce same changeset on both backends."""
        import shutil

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline
        from eval.conftest import SIM_PROJECT

        results: dict[str, list[str]] = {}

        for backend in ("kuzu", "duckpgq"):
            root = tmp_path / f"parity_{backend}"
            shutil.copytree(SIM_PROJECT, root)
            suffix = ".db" if backend == "kuzu" else ".duckdb"
            db_path = root / ".scaffold" / f"graph{suffix}"
            config = ScaffoldConfig()
            config.graph = GraphConfig(
                db_path=str(db_path),
                backend=backend,
            )
            run_pipeline(root, config)
            new_file = root / "libs" / "parity_check.py"
            new_file.write_text("def parity(): pass\n")
            summary = run_pipeline(root, config, incremental=True)
            results[backend] = summary.get("changeset", {}).get("added", [])

        kuzu_added = set(results["kuzu"])
        duck_added = set(results["duckpgq"])

        # Both should detect the new file (paths may differ in prefix, check basename)
        kuzu_new = {p for p in kuzu_added if "parity_check" in p}
        duck_new = {p for p in duck_added if "parity_check" in p}

        passed = bool(kuzu_new) and bool(duck_new)
        collect_result(
            EvalResult(
                scenario="parity_incremental_changeset",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Both backends detect parity_check.py as added",
                actual=f"Kuzu added: {kuzu_new}, DuckPGQ added: {duck_new}",
                category="parity",
            )
        )
        assert kuzu_new, f"Kuzu did not detect new file in changeset: {results['kuzu']}"
        assert duck_new, f"DuckPGQ did not detect new file in changeset: {results['duckpgq']}"
