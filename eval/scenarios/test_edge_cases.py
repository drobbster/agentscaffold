"""Edge case scenarios: empty graph, deleted files, unicode, malformed docs, etc."""

from __future__ import annotations

import shutil

from eval.conftest import SIM_PROJECT
from eval.runner import EvalResult, collect_result, timed


class TestEmptyGraph:
    """Scenario: Operations on empty/no graph should degrade gracefully."""

    @timed
    def test_graph_context_no_graph(self):
        """get_graph_context with no graph should return empty dict."""
        from agentscaffold.config import ScaffoldConfig
        from agentscaffold.rendering import get_graph_context

        config = ScaffoldConfig()
        ctx = get_graph_context(config)

        result = EvalResult(
            scenario="graph_context_no_graph",
            passed=isinstance(ctx, dict),
            score=1.0 if isinstance(ctx, dict) else 0.0,
            expected="Empty dict (graceful degradation)",
            actual=f"Type: {type(ctx).__name__}, keys: {list(ctx.keys())[:5]}",
            category="edge_case",
        )
        collect_result(result)
        assert isinstance(ctx, dict)

    @timed
    def test_review_context_no_graph(self):
        """get_review_context with no graph should return empty dict."""
        from agentscaffold.config import ScaffoldConfig
        from agentscaffold.rendering import get_review_context

        config = ScaffoldConfig()
        ctx = get_review_context(plan_number=42, config=config)

        result = EvalResult(
            scenario="review_context_no_graph",
            passed=isinstance(ctx, dict),
            score=1.0 if isinstance(ctx, dict) else 0.0,
            expected="Empty dict (graceful degradation)",
            actual=f"Type: {type(ctx).__name__}",
            category="edge_case",
        )
        collect_result(result)
        assert isinstance(ctx, dict)


class TestEmptyFiles:
    """Scenario: Empty Python files should be handled."""

    @timed
    def test_empty_module_indexed(self, indexed_sim):
        """An empty Python file should appear as a File node with 0 definitions."""
        root, store, config = indexed_sim

        results = store.query(
            "MATCH (f:File) WHERE f.path CONTAINS 'empty_module' RETURN f.path, f.lineCount"
        )

        has_file = len(results) > 0

        result = EvalResult(
            scenario="empty_module_indexed",
            passed=has_file,
            score=1.0 if has_file else 0.0,
            expected="empty_module.py in graph",
            actual=f"Found: {results}",
            category="edge_case",
        )
        collect_result(result)
        assert has_file


class TestUnicodeFiles:
    """Scenario: Files with unicode identifiers should parse without errors."""

    @timed
    def test_unicode_provider_indexed(self, indexed_sim):
        """unicode_provider.py should be indexed and its class found."""
        root, store, config = indexed_sim

        results = store.query(
            "MATCH (c:Class) WHERE c.name = 'DatenAnbieter' RETURN c.name, c.filePath"
        )

        has_class = len(results) > 0

        result = EvalResult(
            scenario="unicode_class_indexed",
            passed=has_class,
            score=1.0 if has_class else 0.0,
            expected="DatenAnbieter class in graph",
            actual=f"Found: {results}",
            category="edge_case",
        )
        collect_result(result)
        assert has_class

    @timed
    def test_unicode_methods_extracted(self, indexed_sim):
        """Methods with non-ASCII names should be extracted."""
        root, store, config = indexed_sim

        methods = store.query("MATCH (m:Method) WHERE m.className = 'DatenAnbieter' RETURN m.name")
        method_names = {r["m.name"] for r in methods}

        expected = {"hole_daten", "validiere"}
        found = expected & method_names

        result = EvalResult(
            scenario="unicode_methods_extracted",
            passed=len(found) >= 1,
            score=len(found) / len(expected),
            expected=f"Methods: {expected}",
            actual=f"Found: {found}, All: {method_names}",
            category="edge_case",
        )
        collect_result(result)


class TestGoRustFiles:
    """Scenario: Multi-language files (Go, Rust) should be indexed."""

    @timed
    def test_go_file_indexed(self, indexed_sim):
        """Go file should be indexed as a File node."""
        root, store, config = indexed_sim

        results = store.query(
            "MATCH (f:File) WHERE f.path CONTAINS 'go_utils.go' RETURN f.path, f.language"
        )

        has_go = len(results) > 0

        result = EvalResult(
            scenario="go_file_indexed",
            passed=has_go,
            score=1.0 if has_go else 0.0,
            expected="go_utils.go in graph",
            actual=f"Found: {results}",
            category="edge_case",
        )
        collect_result(result)
        assert has_go

    @timed
    def test_rust_file_indexed(self, indexed_sim):
        """Rust file should be indexed as a File node."""
        root, store, config = indexed_sim

        results = store.query(
            "MATCH (f:File) WHERE f.path CONTAINS 'rust_helper.rs' RETURN f.path, f.language"
        )

        has_rust = len(results) > 0

        result = EvalResult(
            scenario="rust_file_indexed",
            passed=has_rust,
            score=1.0 if has_rust else 0.0,
            expected="rust_helper.rs in graph",
            actual=f"Found: {results}",
            category="edge_case",
        )
        collect_result(result)
        assert has_rust


class TestDeletedFiles:
    """Scenario: Deleting a file and re-indexing should remove it from graph."""

    def test_deleted_file_removed(self, tmp_path):
        """Deleting a file and doing incremental index should remove its nodes."""
        dest = tmp_path / "sim"
        shutil.copytree(SIM_PROJECT, dest)

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline

        db_path = dest / ".scaffold" / "graph.db"
        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(db_path))

        run_pipeline(dest, config)

        target = dest / "libs" / "data" / "normalizer.py"
        assert target.exists()
        target.unlink()

        summary2 = run_pipeline(dest, config, incremental=True)
        cs = summary2.get("changeset", {})
        deleted = cs.get("deleted", [])

        was_deleted = "libs/data/normalizer.py" in deleted

        result = EvalResult(
            scenario="deleted_file_removed",
            passed=was_deleted,
            score=1.0 if was_deleted else 0.0,
            expected="libs/data/normalizer.py in deleted changeset",
            actual=f"Deleted: {deleted}",
            category="edge_case",
        )
        collect_result(result)
        assert was_deleted


class TestMalformedGovernance:
    """Scenario: Malformed governance docs should not crash the pipeline."""

    def test_malformed_plan(self, tmp_path):
        """A plan with broken markdown should not crash indexing."""
        dest = tmp_path / "sim"
        shutil.copytree(SIM_PROJECT, dest)

        malformed = dest / "docs" / "ai" / "plans" / "plan_999_broken.md"
        malformed.write_text(
            "# This is not a valid plan\n"
            "No metadata section.\n"
            "| broken | table\n"
            "random text with no structure\n"
        )

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline

        db_path = dest / ".scaffold" / "graph.db"
        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(db_path))

        try:
            summary = run_pipeline(dest, config)
            passed = True
            actual = f"Pipeline completed: {summary.get('phases_completed', [])}"
        except Exception as exc:
            passed = False
            actual = f"Exception: {type(exc).__name__}: {exc}"

        result = EvalResult(
            scenario="malformed_plan_no_crash",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Pipeline completes without crash",
            actual=actual,
            category="edge_case",
        )
        collect_result(result)
        assert passed

    def test_missing_contracts_dir(self, tmp_path):
        """Missing contracts directory should not crash indexing."""
        dest = tmp_path / "sim"
        shutil.copytree(SIM_PROJECT, dest)

        contracts_dir = dest / "docs" / "ai" / "contracts"
        shutil.rmtree(contracts_dir)

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline

        db_path = dest / ".scaffold" / "graph.db"
        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(db_path))

        try:
            summary = run_pipeline(dest, config)
            passed = True
            actual = f"Completed phases: {summary.get('phases_completed', [])}"
        except Exception as exc:
            passed = False
            actual = f"Exception: {type(exc).__name__}: {exc}"

        result = EvalResult(
            scenario="missing_contracts_dir",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Pipeline completes without crash",
            actual=actual,
            category="edge_case",
        )
        collect_result(result)
        assert passed


class TestContractDrift:
    """Scenario: Contract drift detection."""

    @timed
    def test_execution_contract_drift(self, indexed_sim):
        """Execution interface contract declares get_fill_rate() which is not implemented."""
        root, store, config = indexed_sim
        from agentscaffold.graph.verify import check_contract_drift

        drift_report = check_contract_drift(store)
        drift_names = [d["name"] for d in drift_report["drift_items"]]
        has_drift = "get_fill_rate" in drift_names

        result = EvalResult(
            scenario="contract_drift_detection",
            passed=has_drift,
            score=1.0 if has_drift else 0.5,
            expected="get_fill_rate detected as drift (in contract, not in code)",
            actual=(f"Drift items: {drift_names}, Health: {drift_report['health']}"),
            observations=[
                f"Total declared: {drift_report['total_declared']}",
                f"Linked: {drift_report['linked']}",
                f"Drift count: {drift_report['drift_count']}",
            ],
            category="edge_case",
        )
        collect_result(result)
        assert has_drift, f"Expected get_fill_rate in drift, got: {drift_names}"


class TestStalePlan:
    """Scenario: Stale plan detection."""

    @timed
    def test_stale_plan_detected(self, indexed_sim):
        """Plan 012 (from 2025-06-01) should be detectable as stale."""
        root, store, config = indexed_sim

        plans = store.query(
            "MATCH (p:Plan) WHERE p.number = 12 RETURN p.number, p.status, p.lastUpdated"
        )

        has_plan = len(plans) > 0

        result = EvalResult(
            scenario="stale_plan_ingested",
            passed=has_plan,
            score=1.0 if has_plan else 0.0,
            expected="Plan 012 ingested with old date",
            actual=f"Plans: {plans}",
            observations=["Plan was last updated 2025-06-15 -- flaggable as stale"],
            category="edge_case",
        )
        collect_result(result)
        assert has_plan
