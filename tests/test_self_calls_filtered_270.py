"""Plan 270: context drops self-CALLS; impact labels same-file callers."""

from __future__ import annotations

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.mcp.server import _tool_context, _tool_impact


def test_context_drops_self_caller_and_callee() -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    store.create_node(
        "Function",
        {
            "id": "fn::src/rec.py:foo",
            "name": "foo",
            "filePath": "src/rec.py",
            "startLine": 1,
            "endLine": 4,
            "isExported": True,
            "paramCount": 0,
            "signature": "foo()",
        },
    )
    store.create_edge(
        "CALLS",
        "Function",
        "fn::src/rec.py:foo",
        "Function",
        "fn::src/rec.py:foo",
        {"confidence": 0.85, "reason": "name"},
    )
    try:
        result = _tool_context(store, {"symbol": "foo"}, {})
        assert result["callers"] == []
        assert result["callees"] == []
        assert result["caller_count"] == 0
        assert result["callee_count"] == 0
    finally:
        store.close()


def test_impact_labels_same_file_caller() -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    store.create_node(
        "File",
        {"id": "file::src/mod.py", "path": "src/mod.py", "language": "python"},
    )
    store.create_node(
        "Function",
        {
            "id": "fn::src/mod.py:bar",
            "name": "bar",
            "filePath": "src/mod.py",
            "startLine": 8,
            "endLine": 10,
            "isExported": True,
            "paramCount": 0,
            "signature": "bar()",
        },
    )
    store.create_node(
        "Function",
        {
            "id": "fn::src/mod.py:foo",
            "name": "foo",
            "filePath": "src/mod.py",
            "startLine": 1,
            "endLine": 4,
            "isExported": True,
            "paramCount": 0,
            "signature": "foo()",
        },
    )
    store.create_edge(
        "DEFINES_FUNCTION", "File", "file::src/mod.py", "Function", "fn::src/mod.py:bar"
    )
    store.create_edge(
        "CALLS",
        "Function",
        "fn::src/mod.py:foo",
        "Function",
        "fn::src/mod.py:bar",
        {"confidence": 0.9, "reason": "resolved"},
    )
    try:
        result = _tool_impact(store, {"file_or_symbol": "src/mod.py"}, {})
        names = {row["name"] for row in result["callers_into_file"]}
        assert "foo" in names
        self_rows = [row for row in result["callers_into_file"] if row.get("self")]
        assert self_rows
        assert all(row["name"] == "foo" for row in self_rows)
    finally:
        store.close()
