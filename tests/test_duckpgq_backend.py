"""Protocol conformance + functional tests for DuckPGQBackend — Step A.6."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentscaffold.graph.backend import GraphBackend

# Skip entire module if duckdb is not installed.
duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402

REQUIRED_METHODS = [
    "init_schema",
    "schema_version",
    "schema_current",
    "execute",
    "query",
    "query_scalar",
    "create_node",
    "create_edge",
    "node_count",
    "edge_count",
    "clear_table",
    "clear_all",
    "update_pipeline_state",
    "get_pipeline_state",
    "add_parsing_warning",
    "get_parsing_warnings",
    "get_stats",
    "close",
    "__enter__",
    "__exit__",
]


@pytest.fixture()
def store():
    """In-memory DuckPGQBackend with schema initialized."""
    s = DuckPGQBackend(":memory:")
    s.init_schema()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Protocol surface
# ---------------------------------------------------------------------------


def test_duckpgq_backend_has_all_required_methods(store: Any) -> None:
    for method in REQUIRED_METHODS:
        assert hasattr(store, method), f"DuckPGQBackend missing method: {method}"
        assert callable(getattr(store, method)), f"DuckPGQBackend.{method} not callable"


def test_duckpgq_backend_satisfies_protocol(store: Any) -> None:
    assert isinstance(store, GraphBackend), "DuckPGQBackend does not satisfy GraphBackend Protocol."


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------


def test_init_schema_idempotent(store: Any) -> None:
    """Calling init_schema twice must not raise."""
    store.init_schema()


def test_schema_version_returns_int(store: Any) -> None:
    v = store.schema_version()
    assert isinstance(v, int), f"Expected int, got {type(v)}"
    assert v > 0


def test_schema_current_returns_true(store: Any) -> None:
    assert store.schema_current() is True


# ---------------------------------------------------------------------------
# CRUD: nodes
# ---------------------------------------------------------------------------

_FILE_PROPS = {
    "id": "test-file-001",
    "path": "src/test.py",
    "language": "python",
    "size": 100,
    "lastModified": "2026-01-01",
    "lineCount": 10,
    "contentHash": "abc123",
}


def test_create_node_and_count(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    assert store.node_count("File") >= 1


def test_create_node_duplicate_ignored(store: Any) -> None:
    """Creating the same node twice (same id) must not raise."""
    store.create_node("File", _FILE_PROPS)
    store.create_node("File", _FILE_PROPS)
    assert store.node_count("File") == 1


def test_node_count_empty_table(store: Any) -> None:
    assert store.node_count("Plan") == 0


# ---------------------------------------------------------------------------
# CRUD: edges
# ---------------------------------------------------------------------------


def test_create_edge_and_count(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    store.create_node(
        "File",
        {**_FILE_PROPS, "id": "test-file-002", "path": "src/b.py"},
    )
    store.create_edge("IMPORTS", "File", "test-file-001", "File", "test-file-002")
    assert store.edge_count("IMPORTS") >= 1


def test_create_edge_with_props(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    store.create_node(
        "File",
        {**_FILE_PROPS, "id": "test-file-003", "path": "src/c.py"},
    )
    store.create_edge(
        "IMPORTS",
        "File",
        "test-file-001",
        "File",
        "test-file-003",
        {"importedNames": "util"},
    )
    assert store.edge_count("IMPORTS") >= 1


def test_edge_count_empty(store: Any) -> None:
    assert store.edge_count("CALLS") == 0


# ---------------------------------------------------------------------------
# Query interface
# ---------------------------------------------------------------------------


def test_query_returns_list_of_dicts(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    rows = store.query("SELECT id, path FROM File WHERE id = 'test-file-001'")
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert isinstance(rows[0], dict)
    assert rows[0]["id"] == "test-file-001"


def test_query_returns_empty_list_for_no_match(store: Any) -> None:
    rows = store.query("SELECT id FROM File WHERE id = 'nonexistent'")
    assert rows == []


def test_query_scalar_returns_count(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    count = store.query_scalar("SELECT COUNT(*) FROM File")
    assert count is not None
    assert int(count) >= 1


def test_query_scalar_returns_none_for_empty(store: Any) -> None:
    val = store.query_scalar("SELECT id FROM File WHERE id = 'nonexistent'")
    assert val is None


def test_execute_returns_result(store: Any) -> None:
    result = store.execute("SELECT 1 AS x")
    assert result is not None


# ---------------------------------------------------------------------------
# Graph traversal via GRAPH_TABLE
# ---------------------------------------------------------------------------


def test_graph_table_query_via_execute(store: Any) -> None:
    """GRAPH_TABLE traversal works on an initialized DuckPGQBackend."""
    store.create_node("File", _FILE_PROPS)
    store.create_node(
        "Plan",
        {
            "id": "p:1",
            "number": 1,
            "title": "Test Plan",
            "status": "COMPLETE",
            "planType": "feature",
            "filePath": "",
            "createdDate": "2026-01-01",
            "lastUpdated": "2026-01-01",
        },
    )
    store.create_edge(
        "PLAN_IMPACTS", "Plan", "p:1", "File", "test-file-001", {"changeType": "MODIFY"}
    )
    rows = store.query(
        """
        SELECT t.f_path, t.change_type
        FROM GRAPH_TABLE(agentscaffold_graph
            MATCH (p:Plan)-[e:PLAN_IMPACTS]->(f:File)
            COLUMNS (f.path AS f_path, e.changeType AS change_type)
        ) t
        """
    )
    assert len(rows) == 1
    assert rows[0]["f_path"] == "src/test.py"
    assert rows[0]["change_type"] == "MODIFY"


# ---------------------------------------------------------------------------
# clear_table / clear_all
# ---------------------------------------------------------------------------


def test_clear_table(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    assert store.node_count("File") >= 1
    store.clear_table("File")
    assert store.node_count("File") == 0


def test_clear_table_cascades_to_edges(store: Any) -> None:
    """clear_table deletes referencing edge rows as well."""
    store.create_node("File", _FILE_PROPS)
    store.create_node(
        "File",
        {**_FILE_PROPS, "id": "test-file-002", "path": "src/b.py"},
    )
    store.create_edge("IMPORTS", "File", "test-file-001", "File", "test-file-002")
    assert store.edge_count("IMPORTS") == 1
    store.clear_table("File")
    assert store.edge_count("IMPORTS") == 0


def test_clear_all(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    store.clear_all()
    # After clear_all, schema is recreated so node_count should work and be 0
    assert store.node_count("File") == 0
    assert store.schema_current() is True


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------


def test_pipeline_state_roundtrip(store: Any) -> None:
    store.update_pipeline_state("running", ["parse", "imports"])
    state = store.get_pipeline_state()
    assert state["state"] == "running"
    assert "parse" in state["phases_completed"]
    assert "imports" in state["phases_completed"]


def test_pipeline_state_initial(store: Any) -> None:
    state = store.get_pipeline_state()
    assert isinstance(state, dict)
    assert "state" in state
    assert "phases_completed" in state


# ---------------------------------------------------------------------------
# Parsing warnings
# ---------------------------------------------------------------------------


def test_add_and_get_parsing_warnings(store: Any) -> None:
    store.add_parsing_warning("w-001", "src/broken.py", "parse", "syntax error")
    warnings = store.get_parsing_warnings()
    assert len(warnings) >= 1
    # DuckPGQBackend uses plain SQL column names (no "w." prefix)
    paths = [w.get("filePath") for w in warnings]
    assert "src/broken.py" in paths


def test_get_parsing_warnings_empty(store: Any) -> None:
    warnings = store.get_parsing_warnings()
    assert warnings == []


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_get_stats_returns_dict(store: Any) -> None:
    stats = store.get_stats()
    assert isinstance(stats, dict)
    expected = {"schema_version", "files", "functions", "plans"}
    assert expected.issubset(set(stats.keys()))


def test_get_stats_counts_nodes(store: Any) -> None:
    store.create_node("File", _FILE_PROPS)
    stats = store.get_stats()
    assert stats["files"] == 1


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager(tmp_path: Path) -> None:
    db_path = tmp_path / "ctx.db"
    with DuckPGQBackend(str(db_path)) as s:
        s.init_schema()
        assert s.schema_current() is True
    # After __exit__, connection is closed — absence of exception is the test


# ---------------------------------------------------------------------------
# open_graph factory — duckpgq path
# ---------------------------------------------------------------------------


def test_open_graph_duckpgq_returns_graphbackend(tmp_path: Path) -> None:
    """open_graph(backend='duckpgq') returns a DuckPGQBackend."""
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph

    db_path = tmp_path / "graph.db"
    config = ScaffoldConfig(graph=GraphConfig(db_path=str(db_path), backend="duckpgq"))
    store = open_graph(config, backend="duckpgq")
    try:
        assert isinstance(store, DuckPGQBackend)
        assert isinstance(store, GraphBackend)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Connection robustness (Plan 218)
# ---------------------------------------------------------------------------


def test_is_lock_error_classifies_lock_messages() -> None:
    from agentscaffold.graph.duckpgq_backend import _is_lock_error

    assert _is_lock_error(Exception("Could not set lock on file foo.db")) is True
    assert _is_lock_error(Exception("Conflicting lock is held in another process")) is True
    assert _is_lock_error(Exception("some unrelated parse error")) is False


def test_connect_retries_then_raises_graph_lock_error(monkeypatch) -> None:
    """A persistent lock error is retried then surfaced as GraphLockError."""
    import agentscaffold.graph.duckpgq_backend as backend_mod
    from agentscaffold.graph.duckpgq_backend import GraphLockError

    calls = {"n": 0}

    def _always_locked(_db_str):
        calls["n"] += 1
        raise RuntimeError("Could not set lock on file graph.duckdb")

    monkeypatch.setattr(backend_mod.duckdb, "connect", _always_locked)
    monkeypatch.setattr(backend_mod.time, "sleep", lambda _s: None)

    with pytest.raises(GraphLockError) as exc_info:
        backend_mod._connect("graph.duckdb", retries=3, backoff=0.0)

    assert calls["n"] == 3
    assert "another process" in str(exc_info.value)


def test_connect_does_not_retry_non_lock_errors(monkeypatch) -> None:
    import agentscaffold.graph.duckpgq_backend as backend_mod

    calls = {"n": 0}

    def _other_error(_db_str):
        calls["n"] += 1
        raise RuntimeError("disk is on fire")

    monkeypatch.setattr(backend_mod.duckdb, "connect", _other_error)

    with pytest.raises(RuntimeError, match="disk is on fire"):
        backend_mod._connect("graph.duckdb", retries=4, backoff=0.0)
    assert calls["n"] == 1


def test_connect_succeeds_for_fresh_path(tmp_path: Path) -> None:
    """The retry wrapper opens a normal file DB on the first attempt."""
    import agentscaffold.graph.duckpgq_backend as backend_mod

    db_path = tmp_path / "fresh.duckdb"
    conn = backend_mod._connect(str(db_path))
    try:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_graph_lock_error_is_exported() -> None:
    """GraphLockError is part of the graph package public API."""
    from agentscaffold.graph import GraphLockError as ExportedLockError
    from agentscaffold.graph.duckpgq_backend import GraphLockError

    assert ExportedLockError is GraphLockError
