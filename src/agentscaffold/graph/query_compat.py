"""Backend-agnostic query helpers for AgentScaffold.

Provides ``ql()``, ``ql_scalar()``, and ``ql_execute()`` that execute SQL
queries against the DuckPGQ backend.

The ``cypher`` parameter is accepted but ignored — it exists only to avoid
breaking call sites during the transition from the removed KuzuDB backend.
A future cleanup pass will remove the cypher parameters entirely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


def is_duckpgq(store: Any) -> bool:
    """Return True. Only the DuckPGQ backend is supported."""
    return True


def ql(
    store: GraphBackend,
    cypher: str = "",
    sql: str = "",
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute a SQL query and return a list of dicts.

    Args:
        store: A GraphBackend instance.
        cypher: Ignored (legacy parameter).
        sql: DuckDB SQL query string.
        params: Optional parameter dict forwarded to the backend's query().

    Returns:
        List of row dicts.
    """
    return store.query(sql, params)


def ql_scalar(
    store: GraphBackend,
    cypher: str = "",
    sql: str = "",
    params: dict[str, Any] | None = None,
) -> Any:
    """Execute a SQL scalar query and return a single value.

    Returns None if the query yields no rows.
    """
    return store.query_scalar(sql, params)


def ql_execute(
    store: GraphBackend,
    cypher: str = "",
    sql: str = "",
    params: dict[str, Any] | None = None,
) -> Any:
    """Execute a SQL write statement (CREATE/UPDATE/DELETE)."""
    return store.execute(sql, params)
