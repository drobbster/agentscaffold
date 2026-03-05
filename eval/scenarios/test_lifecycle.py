"""Lifecycle scenarios: full index pipeline, plan lifecycle gates, incremental, sessions."""

from __future__ import annotations

import shutil

from eval.conftest import SIM_PROJECT
from eval.runner import EvalResult, collect_result, timed


class TestFullIndexLifecycle:
    """Scenario: Index the full simulation project and verify all phases complete."""

    @timed
    def test_full_index_completes(self, indexed_sim):
        """Full pipeline index should complete all expected phases."""
        root, store, config = indexed_sim

        state = store.get_pipeline_state()
        phases = state.get("phases_completed", [])
        expected = {"structure", "parsing", "resolution", "governance"}

        missing = expected - set(phases)
        result = EvalResult(
            scenario="full_index_lifecycle",
            passed=len(missing) == 0,
            score=1.0 - len(missing) / len(expected),
            expected=f"Phases: {sorted(expected)}",
            actual=f"Phases: {sorted(phases)}",
            observations=[f"Missing: {sorted(missing)}"] if missing else [],
            category="lifecycle",
        )
        collect_result(result)
        assert not missing, f"Missing phases: {missing}"

    @timed
    def test_files_indexed(self, indexed_sim):
        """All Python source files should be indexed."""
        root, store, config = indexed_sim

        files = store.query("MATCH (f:File) WHERE f.language = 'python' RETURN f.path")
        file_paths = {r["f.path"] for r in files}

        expected_files = [
            "libs/data/router.py",
            "libs/strategy/momentum.py",
            "libs/risk/manager.py",
            "libs/execution/engine.py",
            "services/api/routes.py",
        ]
        found = [f for f in expected_files if f in file_paths]
        missing = [f for f in expected_files if f not in file_paths]

        result = EvalResult(
            scenario="files_indexed",
            passed=len(missing) == 0,
            score=len(found) / len(expected_files),
            expected=f"{len(expected_files)} key files indexed",
            actual=f"{len(found)} found, {len(missing)} missing: {missing}",
            category="lifecycle",
        )
        collect_result(result)
        assert not missing, f"Key files not indexed: {missing}"

    @timed
    def test_definitions_extracted(self, indexed_sim):
        """Key classes and functions should be extracted."""
        root, store, config = indexed_sim

        functions = store.query("MATCH (fn:Function) RETURN fn.name")
        fn_names = {r["fn.name"] for r in functions}

        classes = store.query("MATCH (c:Class) RETURN c.name")
        class_names = {r["c.name"] for r in classes}

        expected_classes = ["DataRouter", "MomentumStrategy", "RiskManager", "ExecutionEngine"]
        expected_fns = ["normalize_ohlcv", "validate_ohlcv", "run_daily_ingest"]

        missing_classes = [c for c in expected_classes if c not in class_names]
        missing_fns = [f for f in expected_fns if f not in fn_names]

        all_expected = len(expected_classes) + len(expected_fns)
        all_found = all_expected - len(missing_classes) - len(missing_fns)

        result = EvalResult(
            scenario="definitions_extracted",
            passed=not missing_classes and not missing_fns,
            score=all_found / all_expected if all_expected else 1.0,
            expected=f"Classes: {expected_classes}, Funcs: {expected_fns}",
            actual=f"Missing classes: {missing_classes}, Missing funcs: {missing_fns}",
            category="lifecycle",
        )
        collect_result(result)
        assert not missing_classes, f"Missing classes: {missing_classes}"
        assert not missing_fns, f"Missing functions: {missing_fns}"

    @timed
    def test_governance_ingested(self, indexed_sim):
        """Plans, contracts, and learnings should be ingested."""
        root, store, config = indexed_sim

        plans = store.query("MATCH (p:Plan) RETURN p.number, p.title, p.status")
        contracts = store.query("MATCH (c:Contract) RETURN c.name, c.version")
        learnings = store.query("MATCH (l:Learning) RETURN l.id")

        observations = [
            f"Plans: {len(plans)}",
            f"Contracts: {len(contracts)}",
            f"Learnings: {len(learnings)}",
        ]

        has_plans = len(plans) >= 4
        has_contracts = len(contracts) >= 2

        total = 2
        passed_count = sum([has_plans, has_contracts])

        result = EvalResult(
            scenario="governance_ingested",
            passed=passed_count == total,
            score=passed_count / total,
            expected=">=4 plans, >=2 contracts",
            actual=f"{len(plans)} plans, {len(contracts)} contracts, {len(learnings)} learnings",
            observations=observations,
            category="lifecycle",
        )
        collect_result(result)
        assert has_plans, f"Expected >=4 plans, got {len(plans)}"
        assert has_contracts, f"Expected >=2 contracts, got {len(contracts)}"

    @timed
    def test_import_resolution(self, indexed_sim):
        """Imports between files should be resolved."""
        root, store, config = indexed_sim

        edges = store.query("MATCH (a:File)-[:IMPORTS]->(b:File) RETURN a.path, b.path")

        has_edges = len(edges) >= 5

        # Check that at least some cross-module imports are resolved
        importing_files = {e["a.path"] for e in edges}
        imported_files = {e["b.path"] for e in edges}

        observations = [
            f"Total import edges: {len(edges)}",
            f"Importing files: {len(importing_files)}",
            f"Imported files: {len(imported_files)}",
        ]

        result = EvalResult(
            scenario="import_resolution",
            passed=has_edges,
            score=min(len(edges) / 10, 1.0),
            expected=">=5 import edges across modules",
            actual=f"{len(edges)} edges from {len(importing_files)} files",
            observations=observations,
            category="lifecycle",
        )
        collect_result(result)
        assert has_edges, f"Expected >=5 import edges, got {len(edges)}"


class TestIncrementalIndex:
    """Scenario: Incremental index detects and processes changes correctly."""

    def test_incremental_no_changes(self, tmp_path):
        """Incremental index on unchanged project should be a no-op."""
        dest = tmp_path / "sim"
        shutil.copytree(SIM_PROJECT, dest)

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline

        db_path = dest / ".scaffold" / "graph.db"
        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(db_path))

        run_pipeline(dest, config)
        summary2 = run_pipeline(dest, config, incremental=True)

        cs = summary2.get("changeset", {})
        result = EvalResult(
            scenario="incremental_no_changes",
            passed=len(cs.get("added", [])) == 0 and len(cs.get("modified", [])) == 0,
            score=1.0 if not cs.get("added") and not cs.get("modified") else 0.0,
            expected="No changes detected",
            actual=f"Added: {len(cs.get('added', []))}, Modified: {len(cs.get('modified', []))}",
            category="lifecycle",
        )
        collect_result(result)
        assert not cs.get("added") and not cs.get("modified")

    def test_incremental_detects_new_file(self, tmp_path):
        """Adding a new file should be detected and indexed."""
        dest = tmp_path / "sim"
        shutil.copytree(SIM_PROJECT, dest)

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline

        db_path = dest / ".scaffold" / "graph.db"
        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(db_path))

        run_pipeline(dest, config)

        new_file = dest / "libs" / "analytics.py"
        new_file.write_text("def compute_sharpe(returns: list[float]) -> float:\n    return 0.0\n")

        summary2 = run_pipeline(dest, config, incremental=True)
        cs = summary2.get("changeset", {})
        added = cs.get("added", [])

        result = EvalResult(
            scenario="incremental_new_file",
            passed="libs/analytics.py" in added,
            score=1.0 if "libs/analytics.py" in added else 0.0,
            expected="libs/analytics.py in added",
            actual=f"Added: {added}",
            category="lifecycle",
        )
        collect_result(result)
        assert "libs/analytics.py" in added


class TestSessionLifecycle:
    """Scenario: Cross-session memory tracks development activity."""

    def test_session_start_end(self, indexed_sim):
        """Session can be started and ended with metadata tracked."""
        root, store, config = indexed_sim
        from agentscaffold.graph.sessions import end_session, get_session, start_session

        sid = start_session(store, plan_numbers=[42], summary="Testing session lifecycle")
        session = get_session(store, sid)

        assert session is not None, "Session should be retrievable"
        assert 42 in session.get("plan_numbers", [])

        end_session(store, sid, summary="Session completed successfully")
        ended = get_session(store, sid)
        assert ended.get("summary") == "Session completed successfully"

        result = EvalResult(
            scenario="session_start_end",
            passed=True,
            score=1.0,
            expected="Session created, ended with timestamps",
            actual=f"Session {sid} created and ended",
            category="lifecycle",
        )
        collect_result(result)

    def test_session_modifications(self, indexed_sim):
        """Session modifications should be tracked."""
        root, store, config = indexed_sim
        from agentscaffold.graph.sessions import (
            record_modification,
            start_session,
        )

        sid = start_session(store, plan_numbers=[68], summary="Working on execution engine")
        record_modification(store, sid, "libs/execution/engine.py")

        session_mods = store.query(
            f"MATCH (s:Session)-[:SESSION_MODIFIED]->(f:File) WHERE s.id = '{sid}' RETURN f.path"
        )
        mod_paths = [r["f.path"] for r in session_mods]

        result = EvalResult(
            scenario="session_modifications",
            passed="libs/execution/engine.py" in mod_paths,
            score=1.0 if "libs/execution/engine.py" in mod_paths else 0.0,
            expected="libs/execution/engine.py tracked",
            actual=f"Tracked files: {mod_paths}",
            category="lifecycle",
        )
        collect_result(result)
        assert "libs/execution/engine.py" in mod_paths
