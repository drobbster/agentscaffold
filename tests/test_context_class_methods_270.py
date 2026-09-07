"""Plan 270: class context surfaces HAS_METHOD rows."""

from __future__ import annotations

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.mcp.server import _tool_context


def _class_with_methods() -> DuckPGQBackend:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    store.create_node(
        "Class",
        {
            "id": "class::src/pipe.py:Pipe",
            "name": "Pipe",
            "filePath": "src/pipe.py",
            "startLine": 1,
            "endLine": 20,
            "isExported": True,
        },
    )
    store.create_node(
        "Method",
        {
            "id": "method::src/pipe.py:Pipe.run",
            "name": "run",
            "className": "Pipe",
            "filePath": "src/pipe.py",
            "startLine": 4,
            "endLine": 8,
            "isExported": True,
            "signature": "run(self)",
        },
    )
    store.create_node(
        "Method",
        {
            "id": "method::src/pipe.py:Pipe.close",
            "name": "close",
            "className": "Pipe",
            "filePath": "src/pipe.py",
            "startLine": 10,
            "endLine": 12,
            "isExported": True,
            "signature": "close(self)",
        },
    )
    store.create_edge(
        "HAS_METHOD", "Class", "class::src/pipe.py:Pipe", "Method", "method::src/pipe.py:Pipe.run"
    )
    store.create_edge(
        "HAS_METHOD",
        "Class",
        "class::src/pipe.py:Pipe",
        "Method",
        "method::src/pipe.py:Pipe.close",
    )
    return store


def test_class_context_lists_methods() -> None:
    store = _class_with_methods()
    try:
        result = _tool_context(store, {"symbol": "Pipe"}, {})
        names = {row["name"] for row in result["methods"]}
        assert names == {"run", "close"}
        assert result["method_count"] == 2
        assert result["construction_sites"] == []
        assert "### Methods (2)" in result["markdown"]
        assert "Callees (0)" not in result["markdown"]
    finally:
        store.close()


def test_class_with_no_methods_keeps_subclasses() -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    store.create_node(
        "Class",
        {
            "id": "class::src/a.py:Alpha",
            "name": "Alpha",
            "filePath": "src/a.py",
            "startLine": 1,
            "endLine": 4,
            "isExported": True,
        },
    )
    store.create_node(
        "Class",
        {
            "id": "class::src/b.py:Beta",
            "name": "Beta",
            "filePath": "src/b.py",
            "startLine": 1,
            "endLine": 4,
            "isExported": True,
        },
    )
    store.create_edge(
        "EXTENDS",
        "Class",
        "class::src/b.py:Beta",
        "Class",
        "class::src/a.py:Alpha",
        {"resolved": True, "baseName": "Alpha"},
    )
    try:
        result = _tool_context(store, {"symbol": "Alpha"}, {})
        assert result["methods"] == []
        assert {row["name"] for row in result["subclasses"]} == {"Beta"}
        assert "Subclasses" in result["markdown"]
        assert "### Methods (0)" in result["markdown"]
    finally:
        store.close()
