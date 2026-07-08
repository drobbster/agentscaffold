# Interface Contract: GraphBackend Protocol

**Version**: 1.0
**Plan**: 149 — AgentScaffold Architecture Evolution
**Status**: Stable
**Source**: `src/agentscaffold/graph/backend.py`

---

## Overview

`GraphBackend` is a structural Python `Protocol` (PEP 544) that all AgentScaffold graph
storage implementations must satisfy. Current implementations:

| Class | Module | Backend |
|---|---|---|
| `KuzuBackend` | `agentscaffold.graph.kuzu_backend` | KuzuDB (legacy, non-default) |
| `DuckPGQBackend` | `agentscaffold.graph.duckpgq_backend` | DuckDB + DuckPGQ (default) |

Obtain an instance via the factory:

```python
from agentscaffold.graph import open_graph
from agentscaffold.config import load_config

config = load_config()
with open_graph(config) as store:
    rows = store.query("...")
```

---

## Method Contracts

### Schema Management

```python
def init_schema() -> None
```
Create all node and edge tables if they do not exist. Idempotent. Called automatically
by `open_graph()`.

```python
def schema_version() -> int | None
```
Return the integer schema version stored in the metadata table, or `None` if no
metadata exists (fresh database). Used by `run_pipeline()` to detect stale schemas.

```python
def schema_current() -> bool
```
Return `True` iff `schema_version()` matches the current code's schema version constant.
Returning `False` triggers a full re-index.

---

### Query Interface

```python
def execute(query: str, params: dict | None = None) -> Any
```
Execute a raw query and return the backend-native result (cursor or relation object).
Use only when you need the raw object (e.g. for `UPDATE`/`DELETE` in DuckPGQ).

```python
def query(query: str, params: dict | None = None) -> list[dict[str, Any]]
```
Execute a query and return results as a list of dicts. All consumers should use
`query_compat.ql()` rather than calling this directly to maintain backend portability.

```python
def query_scalar(query: str, params: dict | None = None) -> Any
```
Execute a query expected to return a single scalar value. Returns `None` if no row
is found.

---

### CRUD Helpers

```python
def create_node(table: str, props: dict[str, Any]) -> None
```
Insert a single node into the named table. `props` keys must match column names.

```python
def create_edge(
    rel_table: str,
    from_table: str, from_id: str,
    to_table: str, to_id: str,
    props: dict | None = None,
) -> None
```
Insert a directed edge from `from_id` to `to_id`. Node IDs must already exist.

```python
def node_count(table: str) -> int
def edge_count(rel_table: str) -> int
```
Return counts for testing and reporting.

```python
def clear_table(table: str) -> None
def clear_all() -> None
```
`clear_table` removes all rows from one table. `clear_all` drops and recreates the
entire schema (used for full re-index after schema version mismatch).

---

### Pipeline State

```python
def update_pipeline_state(state: str, phases_completed: list[str]) -> None
def get_pipeline_state() -> dict[str, Any]
```
Track which indexing phases have completed. `phases_completed` values are drawn from
the set `{"structure", "parsing", "resolution", "governance"}`.

```python
def add_parsing_warning(warning_id, file_path, phase, message, severity="warning") -> None
def get_parsing_warnings() -> list[dict[str, Any]]
```
Record and retrieve non-fatal parse errors encountered during indexing.

---

### Stats and Lifecycle

```python
def get_stats() -> dict[str, Any]
```
Return summary statistics: node/edge counts per table, schema version, backend name.

```python
def close() -> None
```
Close the underlying database connection. The context manager form is preferred:

```python
with open_graph(config) as store:
    ...
# store is closed here
```

---

## Portability Rules for Consumers

1. **Use `query_compat.ql(store, cypher=..., sql=...)`** for all read queries instead of
   calling `store.query()` directly. This provides dual-dialect dispatch.
2. **Never import `KuzuBackend` or `DuckPGQBackend` directly** in application code.
   Use `open_graph(config)` or `_open_store_for_pipeline()` in the pipeline.
3. **Use `query_compat.is_duckpgq(store)`** when a query cannot be expressed identically
   in both dialects (e.g., multi-hop `GRAPH_TABLE` edges).
4. **Graph variable scoping**: In DuckPGQ `GRAPH_TABLE()`, all output columns must be
   declared in the `COLUMNS(...)` clause — they are not accessible in the outer `SELECT`.

---

## Adding a New Backend

1. Implement all methods in the `GraphBackend` protocol.
2. Add a branch in `graph/pipeline.py::_open_store_for_pipeline()`.
3. Add the backend name as a valid value for `GraphConfig.backend` in `config.py`.
4. Add a new fixture in `eval/conftest.py` and parametrize the parity + lifecycle tests.
