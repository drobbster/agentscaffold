# ADR-023: AgentScaffold Graph Backend Migration — KuzuDB → DuckDB + DuckPGQ

**Status**: Accepted
**Date**: 2026-03-16
**Author**: AI Agent
**Reviewers**: daverobb
**Plan**: 149 — AgentScaffold Architecture Evolution
**Study**: docs/studies/STU-2026-03-03-agentscaffold-vs-claude-code-architecture.md

---

## Context

AgentScaffold used KuzuDB as its sole graph store since initial implementation. The
architecture study (STU-2026-03-03) identified several problems with this choice:

1. **KuzuDB is a dead dependency** in the broader trading system stack. No other component
   uses it, so it carries its own install/upgrade burden with no shared benefit.
2. **DuckDB is already ubiquitous** in the system (feature store, backtester, analytics).
   A DuckDB-based graph store reuses an existing operational and dependency footprint.
3. **DuckPGQ** (DuckDB's PGQ extension, GA in DuckDB 1.2+) provides native property graph
   query syntax, making graph semantics expressible in SQL without a separate graph engine.
4. **Embedding similarity search** (VSS) is available as a DuckDB extension, eliminating
   the need for a separate vector index.
5. KuzuDB's wire protocol and Python client were not stable across minor versions, causing
   recurring CI failures.

The study validated that the 5 structurally most complex Cypher query patterns used in
agentscaffold could be translated to DuckPGQ SQL (spike A.0.5, 1-hour timebox, PASSED).

---

## Decision

Migrate AgentScaffold's graph storage from KuzuDB to DuckDB + DuckPGQ, using the
`GraphBackend` protocol (ADR companion: [graph_backend_interface.md]) to allow both
backends to coexist during transition.

**New default**: `graph.backend: duckpgq` in `scaffold.yaml` / `GraphConfig`.

**Migration path for existing installations**: On first run after upgrade, if the stored
schema version does not match the current version, agentscaffold clears and re-indexes.
A console message prompts the user.

**KuzuDB retention**: KuzuBackend remains available as a non-default option for any
installation that explicitly sets `graph.backend: kuzu`. No deprecation timeline set.

> **Update (2026-06-12)**: The transition is complete. KuzuBackend, the kuzu dependency,
> and all Cypher code paths have been removed; `DuckPGQBackend` is now the only backend
> (`open_graph()` rejects any other `graph.backend` value, and `query_compat.is_duckpgq()`
> always returns True). The default `graph.db_path` is `.scaffold/graph.duckdb`. Setting
> `graph.backend: kuzu` is no longer supported and raises `ValueError`.

---

## Query Translation

| Cypher pattern | DuckPGQ equivalent | Notes |
|---|---|---|
| `MATCH (n:Label) RETURN n.prop` | `SELECT prop FROM Label` | Direct table scan |
| `MATCH (a)-[:REL]->(b) RETURN a.p, b.q` | `GRAPH_TABLE(...MATCH...COLUMNS(a.p, b.q))` | Variable scoping via COLUMNS clause |
| `MATCH path = (a)-[*1..3]-(b)` | Multiple `JOIN` hops or recursive CTE | Translated per query in `query_compat.py` |
| `WHERE n.prop CONTAINS 'x'` | `WHERE prop LIKE '%x%'` | Standard SQL |
| Embedding similarity (`ORDER BY score`) | DuckDB VSS `array_cosine_similarity()` | Replaces Kuzu vector index |

Key translation rule (from spike A.0.5): `GRAPH_TABLE()` variables are scoped to the
inner `COLUMNS()` clause and not accessible in the outer `SELECT`. All multi-hop queries
must export required columns via `COLUMNS (a.prop AS alias)`.

---

## Consequences

**Positive:**
- Eliminates KuzuDB as a standalone dependency. `pip install agentscaffold` no longer
  pulls in the kuzu wheel.
- DuckDB version is shared with the rest of the trading system — one upgrade path.
- DuckPGQ SQL is inspectable with standard SQL tooling (DBeaver, duckdb CLI).
- VSS embeddings co-located with graph data; no separate index file.
- Eval harness validated parity: all 5 backend parity scenarios pass identically on both
  backends (node counts, query results, search, finding write, incremental changeset).

**Negative / Risks:**
- DuckPGQ is a community extension; its API may change across DuckDB minor versions.
  Mitigated by pinning `duckdb>=1.2,<2` in package dependencies.
- PGQ syntax (`GRAPH_TABLE`) is less familiar than Cypher for contributors used to Neo4j
  conventions. Mitigated by `query_compat.py` dual-dialect helper.
- Concurrent writes to DuckDB require WAL locking; high-frequency MCP tool calls (e.g.
  `scaffold_record_finding` in rapid succession) must serialize. Current implementation
  uses connection-per-call; connection pooling deferred.

---

## Alternatives Considered

| Option | Rejected because |
|---|---|
| Keep KuzuDB, upgrade version | Does not solve dependency isolation; KuzuDB API still unstable |
| Neo4j (embedded or docker) | Heavyweight; licensing; adds another infra dependency |
| SQLite with adjacency list tables | No native graph syntax; complex multi-hop queries require recursive CTEs throughout |
| NetworkX in-memory graph | No persistence; not suitable for cross-session knowledge graph |
