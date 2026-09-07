"""Plan 270: scaffold_query names graph edge tables, not pg_views."""

from __future__ import annotations

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.mcp.server import _query_error_message


def test_from_edges_error_names_relationship_tables() -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    try:
        store.query("SELECT COUNT(*) FROM edges")
        raise AssertionError("expected FROM edges to fail")
    except Exception as exc:
        msg = _query_error_message("SELECT COUNT(*) FROM edges", exc)
        assert "CALLS" in msg
        assert "EXTENDS" in msg
        assert "IMPORTS" in msg
        assert "pg_views" not in msg.lower() or "CALLS" in msg
    finally:
        store.close()
