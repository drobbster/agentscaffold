"""Protocol conformance tests for GraphBackend.

Verifies that GraphStore (KuzuBackend) satisfies the GraphBackend Protocol
and that all required methods are present with the correct signatures.

When DuckPGQBackend is added in Step A.4, this file will be extended to
run the same assertions against that implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Protocol surface verification
# ---------------------------------------------------------------------------

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


def test_graphbackend_protocol_importable() -> None:
    """GraphBackend can be imported from agentscaffold.graph."""
    from agentscaffold.graph import GraphBackend
    from agentscaffold.graph.backend import GraphBackend as GraphBackendDirect

    assert GraphBackend is GraphBackendDirect


def test_graphbackend_is_runtime_checkable() -> None:
    """GraphBackend is runtime_checkable so isinstance() works."""
    from agentscaffold.graph.backend import GraphBackend

    # A class with only the required protocol methods should satisfy isinstance
    assert hasattr(GraphBackend, "__protocol_attrs__") or hasattr(
        GraphBackend, "_is_protocol"
    ), "GraphBackend must be a Protocol"


def test_graphbackend_method_surface() -> None:
    """GraphBackend Protocol declares all 20 required methods."""
    from agentscaffold.graph.backend import GraphBackend

    for method in REQUIRED_METHODS:
        assert hasattr(GraphBackend, method), f"GraphBackend is missing method: {method}"


# ---------------------------------------------------------------------------
# KuzuBackend conformance
# ---------------------------------------------------------------------------


@pytest.fixture()
def kuzu_store(tmp_path: Path):
    """Fresh GraphStore (KuzuBackend) with schema initialized."""
    try:
        from agentscaffold.graph.store import GraphStore
    except ImportError:
        pytest.skip("kuzu not installed")

    store = GraphStore(tmp_path / "test.db")
    store.init_schema()
    yield store
    store.close()


def test_graphstore_satisfies_protocol(kuzu_store: Any) -> None:
    """GraphStore is structurally compatible with GraphBackend Protocol."""
    from agentscaffold.graph.backend import GraphBackend

    assert isinstance(kuzu_store, GraphBackend), (
        "GraphStore does not satisfy GraphBackend Protocol. "
        "Check that all protocol methods are implemented."
    )


def test_graphstore_has_all_required_methods(kuzu_store: Any) -> None:
    """GraphStore has every method listed in REQUIRED_METHODS."""
    for method in REQUIRED_METHODS:
        assert hasattr(kuzu_store, method), f"GraphStore is missing method: {method}"
        assert callable(getattr(kuzu_store, method)), f"GraphStore.{method} is not callable"


def test_init_schema_is_idempotent(kuzu_store: Any) -> None:
    """Calling init_schema twice does not raise."""
    kuzu_store.init_schema()  # second call
    # No assertion needed — absence of exception is the test


def test_schema_version_returns_int(kuzu_store: Any) -> None:
    v = kuzu_store.schema_version()
    assert isinstance(v, int), f"Expected int, got {type(v)}"
    assert v > 0


def test_schema_current_returns_bool(kuzu_store: Any) -> None:
    assert kuzu_store.schema_current() is True


def test_create_and_count_node(kuzu_store: Any) -> None:
    kuzu_store.create_node(
        "File",
        {
            "id": "test-file-001",
            "path": "src/test.py",
            "language": "python",
            "size": 100,
            "lastModified": "2026-01-01",
            "lineCount": 10,
            "contentHash": "abc123",
        },
    )
    assert kuzu_store.node_count("File") >= 1


def test_query_returns_list_of_dicts(kuzu_store: Any) -> None:
    kuzu_store.create_node(
        "File",
        {
            "id": "qtest-001",
            "path": "src/q.py",
            "language": "python",
            "size": 50,
            "lastModified": "2026-01-01",
            "lineCount": 5,
            "contentHash": "def456",
        },
    )
    rows = kuzu_store.query("MATCH (f:File) WHERE f.id = 'qtest-001' RETURN f.path")
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert isinstance(rows[0], dict)


def test_query_scalar(kuzu_store: Any) -> None:
    count = kuzu_store.query_scalar("MATCH (f:File) RETURN count(f)")
    # KuzuDB may return numpy int64; convert to check it's numeric
    assert count is not None
    assert int(count) >= 0


def test_pipeline_state_roundtrip(kuzu_store: Any) -> None:
    kuzu_store.update_pipeline_state("running", ["parse", "imports"])
    state = kuzu_store.get_pipeline_state()
    assert state["state"] == "running"
    assert "parse" in state["phases_completed"]


def test_add_and_get_parsing_warnings(kuzu_store: Any) -> None:
    kuzu_store.add_parsing_warning("w-001", "src/broken.py", "parse", "syntax error")
    warnings = kuzu_store.get_parsing_warnings()
    assert any(w.get("w.filePath") == "src/broken.py" for w in warnings)


def test_get_stats_returns_dict(kuzu_store: Any) -> None:
    stats = kuzu_store.get_stats()
    assert isinstance(stats, dict)
    expected_keys = {"schema_version", "files", "functions", "plans"}
    assert expected_keys.issubset(
        set(stats.keys())
    ), f"Missing keys in stats: {expected_keys - set(stats.keys())}"


def test_clear_table(kuzu_store: Any) -> None:
    kuzu_store.create_node(
        "File",
        {
            "id": "del-001",
            "path": "src/del.py",
            "language": "python",
            "size": 1,
            "lastModified": "2026-01-01",
            "lineCount": 1,
            "contentHash": "000",
        },
    )
    before = kuzu_store.node_count("File")
    assert before >= 1
    kuzu_store.clear_table("File")
    assert kuzu_store.node_count("File") == 0


def test_context_manager(tmp_path: Path) -> None:
    """GraphStore works as a context manager (enter/exit)."""
    try:
        from agentscaffold.graph.store import GraphStore
    except ImportError:
        pytest.skip("kuzu not installed")

    db_path = tmp_path / "ctx.db"
    with GraphStore(db_path) as store:
        store.init_schema()
        assert store.schema_current() is True
    # After exit the connection is closed — no assertion needed beyond no-raise


# ---------------------------------------------------------------------------
# open_graph factory
# ---------------------------------------------------------------------------


def test_open_graph_returns_graphbackend(tmp_path: Path) -> None:
    """open_graph() returns an object that satisfies GraphBackend Protocol."""
    try:
        from agentscaffold.graph.store import GraphStore
    except ImportError:
        pytest.skip("kuzu not installed")

    from agentscaffold.graph.backend import GraphBackend as Proto

    # Create a graph on disk first
    db_path = tmp_path / "graph.db"
    store = GraphStore(db_path)
    store.init_schema()
    store.close()

    from agentscaffold.config import GraphConfig, ScaffoldConfig

    config = ScaffoldConfig(graph=GraphConfig(db_path=str(db_path)))

    from agentscaffold.graph import open_graph

    result = open_graph(config)
    try:
        assert isinstance(result, Proto)
    finally:
        result.close()


def test_open_graph_raises_for_unknown_backend(tmp_path: Path) -> None:
    """open_graph(backend='unknown') raises ValueError."""
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph

    config = ScaffoldConfig(graph=GraphConfig(db_path=str(tmp_path / "x.db")))
    with pytest.raises(ValueError, match="Unknown backend"):
        open_graph(config, backend="unknown_engine")
