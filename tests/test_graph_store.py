"""Tests for graph/store.py -- KuzuDB adapter."""

from __future__ import annotations

import pytest

try:
    import kuzu  # noqa: F401

    HAS_KUZU = True
except ImportError:
    HAS_KUZU = False

pytestmark = pytest.mark.skipif(not HAS_KUZU, reason="kuzu not installed")


def test_init_schema(graph_store):
    """Schema tables are created successfully."""
    version = graph_store.schema_version()
    assert version is not None
    assert version >= 1


def test_schema_current(graph_store):
    """Schema version matches code version."""
    assert graph_store.schema_current()


def test_create_and_query_node(graph_store):
    """CRUD: create a node and query it back."""
    graph_store.create_node(
        "File",
        {
            "id": "file::test.py",
            "path": "test.py",
            "language": "python",
            "size": 100,
            "lastModified": "12345",
            "lineCount": 10,
            "contentHash": "abc123",
        },
    )
    count = graph_store.node_count("File")
    assert count == 1

    rows = graph_store.query("MATCH (f:File) RETURN f.path")
    assert len(rows) == 1
    assert rows[0]["f.path"] == "test.py"


def test_query_scalar(graph_store):
    """query_scalar returns a single value."""
    graph_store.create_node(
        "File",
        {
            "id": "file::a.py",
            "path": "a.py",
            "language": "python",
            "size": 50,
            "lastModified": "0",
            "lineCount": 5,
            "contentHash": "x",
        },
    )
    result = graph_store.query_scalar("MATCH (f:File) RETURN count(f)")
    assert result == 1


def test_create_edge(graph_store):
    """Create an edge between two nodes."""
    graph_store.create_node("Folder", {"id": "folder::", "path": ".", "name": "root", "depth": 0})
    graph_store.create_node(
        "File",
        {
            "id": "file::a.py",
            "path": "a.py",
            "language": "python",
            "size": 50,
            "lastModified": "0",
            "lineCount": 5,
            "contentHash": "x",
        },
    )
    graph_store.create_edge("CONTAINS", "Folder", "folder::", "File", "file::a.py")
    count = graph_store.edge_count("CONTAINS")
    assert count == 1


def test_pipeline_state(graph_store):
    """Pipeline state tracking works."""
    graph_store.update_pipeline_state("partial", ["structure", "parsing"])
    state = graph_store.get_pipeline_state()
    assert state["state"] == "partial"
    assert "structure" in state["phases_completed"]
    assert "parsing" in state["phases_completed"]


def test_parsing_warnings(graph_store):
    """Parsing warnings are persisted and retrievable."""
    graph_store.add_parsing_warning("pw::1", "bad.py", "parsing", "Syntax error", "error")
    warnings = graph_store.get_parsing_warnings()
    assert len(warnings) == 1
    assert warnings[0]["w.filePath"] == "bad.py"


def test_get_stats(graph_store):
    """Stats returns all expected keys."""
    stats = graph_store.get_stats()
    assert "files" in stats
    assert "functions" in stats
    assert "schema_version" in stats
    assert stats["files"] == 0
