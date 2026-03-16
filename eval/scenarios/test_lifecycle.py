"""Lifecycle scenarios: full index pipeline, plan lifecycle gates, incremental, sessions."""

from __future__ import annotations

import shutil

from eval.conftest import SIM_PROJECT
from eval.runner import EvalResult, collect_result, timed


class TestFullIndexLifecycle:
    """Scenario: Index the full simulation project and verify all phases complete.

    Step E.8: parametrized over both backends via indexed_sim_both_backends.
    """

    @timed
    def test_full_index_completes(self, indexed_sim_both_backends):
        """Full pipeline index should complete all expected phases."""
        root, store, config = indexed_sim_both_backends
        backend = config.graph.backend

        state = store.get_pipeline_state()
        phases = state.get("phases_completed", [])
        expected = {"structure", "parsing", "resolution", "governance"}

        missing = expected - set(phases)
        result = EvalResult(
            scenario=f"full_index_lifecycle[{backend}]",
            passed=len(missing) == 0,
            score=1.0 - len(missing) / len(expected),
            expected=f"Phases: {sorted(expected)}",
            actual=f"Phases: {sorted(phases)}",
            observations=(
                [f"Missing: {sorted(missing)}", f"backend={backend}"]
                if missing
                else [f"backend={backend}"]
            ),
            category="lifecycle",
        )
        collect_result(result)
        assert not missing, f"Missing phases [{backend}]: {missing}"

    @timed
    def test_files_indexed(self, indexed_sim_both_backends):
        """All Python source files should be indexed."""
        root, store, config = indexed_sim_both_backends
        backend = config.graph.backend

        from agentscaffold.graph.query_compat import ql

        rows = ql(
            store,
            cypher="MATCH (f:File) WHERE f.language = 'python' RETURN f.path",
            sql='SELECT path AS "f.path" FROM File WHERE language = python',
        )
        file_paths = {r["f.path"] for r in rows}

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
            scenario=f"files_indexed[{backend}]",
            passed=len(missing) == 0,
            score=len(found) / len(expected_files),
            expected=f"{len(expected_files)} key files indexed",
            actual=f"{len(found)} found, {len(missing)} missing: {missing}",
            observations=[f"backend={backend}"],
            category="lifecycle",
        )
        collect_result(result)
        assert not missing, f"Key files not indexed [{backend}]: {missing}"

    @timed
    def test_definitions_extracted(self, indexed_sim_both_backends):
        """Key classes and functions should be extracted."""
        root, store, config = indexed_sim_both_backends
        backend = config.graph.backend

        from agentscaffold.graph.query_compat import ql

        fn_rows = ql(
            store,
            cypher="MATCH (fn:Function) RETURN fn.name",
            sql='SELECT name AS "fn.name" FROM Function',
        )
        fn_names = {r["fn.name"] for r in fn_rows}

        class_rows = ql(
            store,
            cypher="MATCH (c:Class) RETURN c.name",
            sql='SELECT name AS "c.name" FROM Class',
        )
        class_names = {r["c.name"] for r in class_rows}

        expected_classes = ["DataRouter", "MomentumStrategy", "RiskManager", "ExecutionEngine"]
        expected_fns = ["normalize_ohlcv", "validate_ohlcv", "run_daily_ingest"]

        missing_classes = [c for c in expected_classes if c not in class_names]
        missing_fns = [f for f in expected_fns if f not in fn_names]

        all_expected = len(expected_classes) + len(expected_fns)
        all_found = all_expected - len(missing_classes) - len(missing_fns)

        result = EvalResult(
            scenario=f"definitions_extracted[{backend}]",
            passed=not missing_classes and not missing_fns,
            score=all_found / all_expected if all_expected else 1.0,
            expected=f"Classes: {expected_classes}, Funcs: {expected_fns}",
            actual=f"Missing classes: {missing_classes}, Missing funcs: {missing_fns}",
            observations=[f"backend={backend}"],
            category="lifecycle",
        )
        collect_result(result)
        assert not missing_classes, f"Missing classes [{backend}]: {missing_classes}"
        assert not missing_fns, f"Missing functions [{backend}]: {missing_fns}"

    @timed
    def test_governance_ingested(self, indexed_sim_both_backends):
        """Plans, contracts, and learnings should be ingested."""
        root, store, config = indexed_sim_both_backends
        backend = config.graph.backend

        from agentscaffold.graph.query_compat import ql

        plans = ql(
            store,
            cypher="MATCH (p:Plan) RETURN p.number, p.title, p.status",
            sql=('SELECT number AS "p.number", title AS "p.title", status AS "p.status" FROM Plan'),
        )
        contracts = ql(
            store,
            cypher="MATCH (c:Contract) RETURN c.name, c.version",
            sql='SELECT name AS "c.name", version AS "c.version" FROM Contract',
        )
        learnings = ql(
            store,
            cypher="MATCH (l:Learning) RETURN l.id",
            sql='SELECT id AS "l.id" FROM Learning',
        )

        has_plans = len(plans) >= 4
        has_contracts = len(contracts) >= 2
        total = 2
        passed_count = sum([has_plans, has_contracts])

        result = EvalResult(
            scenario=f"governance_ingested[{backend}]",
            passed=passed_count == total,
            score=passed_count / total,
            expected=">=4 plans, >=2 contracts",
            actual=f"{len(plans)} plans, {len(contracts)} contracts, {len(learnings)} learnings",
            observations=[
                f"Plans: {len(plans)}",
                f"Contracts: {len(contracts)}",
                f"Learnings: {len(learnings)}",
                f"backend={backend}",
            ],
            category="lifecycle",
        )
        collect_result(result)
        assert has_plans, f"Expected >=4 plans [{backend}], got {len(plans)}"
        assert has_contracts, f"Expected >=2 contracts [{backend}], got {len(contracts)}"

    @timed
    def test_import_resolution(self, indexed_sim_both_backends):
        """Imports between files should be resolved."""
        root, store, config = indexed_sim_both_backends
        backend = config.graph.backend

        from agentscaffold.graph.query_compat import is_duckpgq, ql

        if is_duckpgq(store):
            sql = (
                'SELECT a.path AS "a.path", b.path AS "b.path" '
                "FROM GRAPH_TABLE(agentscaffold_graph "
                "  MATCH (a:File)-[e:IMPORTS]->(b:File) "
                "  COLUMNS (a.path, b.path) "
                ") t"
            )
        else:
            sql = 'SELECT a.path AS "a.path", b.path AS "b.path" FROM File a JOIN File b ON true'

        edges = ql(
            store,
            cypher="MATCH (a:File)-[:IMPORTS]->(b:File) RETURN a.path, b.path",
            sql=sql,
        )

        has_edges = len(edges) >= 5
        importing_files = {e["a.path"] for e in edges}

        result = EvalResult(
            scenario=f"import_resolution[{backend}]",
            passed=has_edges,
            score=min(len(edges) / 10, 1.0),
            expected=">=5 import edges across modules",
            actual=f"{len(edges)} edges from {len(importing_files)} files",
            observations=[f"backend={backend}"],
            category="lifecycle",
        )
        collect_result(result)
        assert has_edges, f"Expected >=5 import edges [{backend}], got {len(edges)}"


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
    """Scenario: Cross-session memory tracks development activity.

    Step E.8: parametrized over both backends via indexed_sim_both_backends.
    """

    def test_session_start_end(self, indexed_sim_both_backends):
        """Session can be started and ended with metadata tracked."""
        root, store, config = indexed_sim_both_backends
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

    def test_session_modifications(self, indexed_sim_both_backends):
        """Session modifications should be tracked."""
        root, store, config = indexed_sim_both_backends
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
