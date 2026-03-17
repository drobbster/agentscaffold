"""Backend-agnostic query dispatch for AgentScaffold — Step A.7.

Provides ``ql()``, ``ql_scalar()``, and ``ql_execute()`` helpers that route
to the correct query dialect (Cypher for KuzuDB, SQL for DuckPGQ) based on
the runtime backend type.

Usage in consumer modules::

    from agentscaffold.graph.query_compat import ql, ql_scalar, is_duckpgq

    rows = ql(
        store,
        cypher="MATCH (f:File) WHERE f.path = 'src/a.py' RETURN f.id",
        sql="SELECT id FROM File WHERE path = 'src/a.py'",
    )

Translation rules (see dev_docs/spike-duckpgq-query-validation.md for details):

  KuzuDB Cypher pattern          →  DuckPGQ / SQL equivalent
  -------------------------------------------------------------
  MATCH ... RETURN a.x           →  GRAPH_TABLE + COLUMNS (a.x AS ax) +
                                     outer SELECT t.ax AS "a.x"
  [:REL*1..N]                    →  -[e:REL]->{1,N}
  Multiple MATCH clauses         →  Single chained path pattern
  count(n) AS alias + ORDER BY   →  Wrap GRAPH_TABLE in subquery, GROUP BY outside
  HAVING on single-table scan    →  Pure SQL GROUP BY ... HAVING (no GRAPH_TABLE)
  a.prop CONTAINS 'x'            →  CONTAINS(a.prop, 'x')  (DuckDB string fn)
  Single-node scan (no edges)    →  Direct SQL SELECT FROM Table (no GRAPH_TABLE)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


def is_duckpgq(store: Any) -> bool:
    """Return True if *store* is a DuckPGQBackend instance.

    Uses class-name check to avoid importing DuckPGQBackend (which requires
    duckdb) in modules that also support Kuzu-only environments.
    Unwraps proxy/wrapper objects (e.g. _NoCloseStore) that delegate via _store.
    """
    underlying = getattr(store, "_store", store)
    return type(underlying).__name__ == "DuckPGQBackend"


def ql(
    store: GraphBackend,
    cypher: str,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute the dialect-appropriate query and return a list of dicts.

    Args:
        store: Any GraphBackend instance.
        cypher: KuzuDB Cypher query string (used when backend is Kuzu).
        sql: DuckDB SQL query string, may include GRAPH_TABLE (used for DuckPGQ).
        params: Optional parameter dict forwarded to the backend's query().

    Returns:
        List of row dicts.  Column names match the RETURN / SELECT column
        names of the executed query.
    """
    if is_duckpgq(store):
        return store.query(sql, params)
    return store.query(cypher, params)


def ql_scalar(
    store: GraphBackend,
    cypher: str,
    sql: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """Execute the dialect-appropriate scalar query and return a single value.

    Returns None if the query yields no rows.
    """
    if is_duckpgq(store):
        return store.query_scalar(sql, params)
    return store.query_scalar(cypher, params)


def ql_execute(
    store: GraphBackend,
    cypher: str,
    sql: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """Execute the dialect-appropriate write statement.

    Use this for CREATE / UPDATE / DELETE / SET operations that return no
    meaningful result.
    """
    if is_duckpgq(store):
        return store.execute(sql, params)
    return store.execute(cypher, params)
