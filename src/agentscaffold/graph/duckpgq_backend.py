"""DuckDB + DuckPGQ backend for the AgentScaffold knowledge graph.

Implements the GraphBackend protocol using DuckDB with the duckpgq community
extension for property graph queries.

Query dialect: SQL.  Consumers call through ``graph/query_compat.py``
which provides the ``ql()``, ``ql_scalar()``, and ``ql_execute()`` helpers.

Requires: pip install agentscaffold[graph-duckpgq]
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscaffold.graph.duckpgq_schema import SCHEMA_VERSION
from agentscaffold.graph.duckpgq_schema import init_schema as _duckpgq_init_schema

logger = logging.getLogger(__name__)

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]

_EXTRAS_MSG = "DuckPGQ backend requires duckdb: pip install agentscaffold[graph-duckpgq]"
_EXT_MSG = (
    "DuckPGQ backend requires the duckpgq community extension. "
    "Run: INSTALL duckpgq FROM community; LOAD duckpgq in DuckDB."
)

# Edge table names — mirrors EDGE_TABLES in duckpgq_schema.py.
# Keep in sync with duckpgq_schema.EDGE_TABLES when adding new edge types.
_EDGE_TABLE_NAMES: tuple[str, ...] = (
    "CONTAINS",
    "CONTAINS_FOLDER",
    "DEFINES_FUNCTION",
    "DEFINES_CLASS",
    "DEFINES_INTERFACE",
    "HAS_METHOD",
    "IMPORTS",
    "CALLS",
    "METHOD_CALLS",
    "EXTENDS",
    "IMPLEMENTS",
    "MEMBER_OF_COMMUNITY",
    "STEP_IN_PROCESS",
    "BELONGS_TO_LAYER",
    "PLAN_IMPACTS",
    "PLAN_INTRODUCES_FUNC",
    "PLAN_INTRODUCES_CLASS",
    "CONTRACT_DECLARES_FUNC",
    "CONTRACT_DECLARES_CLASS",
    "LEARNING_RELATES_TO_FILE",
    "LEARNING_RELATES_TO_FUNC",
    "FINDING_ABOUT_FILE",
    "FINDING_ABOUT_FUNC",
    "FINDING_LED_TO",
    "FINDING_ADDRESSED_BY",
    "SESSION_MODIFIED",
    "DEPENDS_ON_PLAN",
    "STUDY_REFERENCES_PLAN",
    "STUDY_REFERENCES_FILE",
    "ADR_GOVERNS",
    "ADR_SUPERSEDES",
    "ADR_CITES_STUDY",
    "ADR_CITES_SPIKE",
    "SPIKE_FOR_PLAN",
    "BACKLOG_ITEM_OF",
    "CONFIG_REFERENCES",
)

# Governance artifacts derived from docs/ (plans, contracts, learnings, etc.).
# These are re-ingested wholesale by process_governance(); clearing them before
# re-ingestion keeps incremental runs free of stale edges/nodes. ReviewFinding
# and Session are intentionally excluded -- they are user/agent knowledge, not
# derived governance, and are preserved across re-indexing.
_GOVERNANCE_NODE_TABLES: tuple[str, ...] = (
    "Plan",
    "Contract",
    "Learning",
    "Study",
    "ADR",
    "Spike",
)
_GOVERNANCE_EDGE_TABLES: tuple[str, ...] = (
    "PLAN_IMPACTS",
    "PLAN_INTRODUCES_FUNC",
    "PLAN_INTRODUCES_CLASS",
    "CONTRACT_DECLARES_FUNC",
    "CONTRACT_DECLARES_CLASS",
    "LEARNING_RELATES_TO_FILE",
    "LEARNING_RELATES_TO_FUNC",
    "DEPENDS_ON_PLAN",
    "STUDY_REFERENCES_PLAN",
    "STUDY_REFERENCES_FILE",
    "ADR_GOVERNS",
    "ADR_SUPERSEDES",
    "ADR_CITES_STUDY",
    "ADR_CITES_SPIKE",
    "SPIKE_FOR_PLAN",
)


class DuckPGQBackend:
    """DuckDB + DuckPGQ implementation of the GraphBackend protocol.

    Uses SQL for all queries and DuckPGQ GRAPH_TABLE for graph traversals.
    Use ``open_graph(config, backend='duckpgq')`` from ``agentscaffold.graph``
    to obtain an instance rather than instantiating this class directly.
    """

    def __init__(self, db_path: Path | str) -> None:
        if duckdb is None:
            raise ImportError(_EXTRAS_MSG)

        self._db_path = Path(db_path) if str(db_path) != ":memory:" else Path(":memory:")
        if str(db_path) != ":memory:":
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = duckdb.connect(str(db_path))
        self._load_extension()

    def _load_extension(self) -> None:
        """Install and load the duckpgq community extension."""
        try:
            self._conn.execute("INSTALL duckpgq FROM community")
        except Exception:
            pass  # already installed or offline; try to load anyway
        try:
            self._conn.execute("LOAD duckpgq")
        except Exception as exc:
            raise RuntimeError(_EXT_MSG) from exc
        self._load_vss_extension()

    def _load_vss_extension(self) -> None:
        """Optionally install and load the DuckDB vss extension (HNSW indexing).

        Gracefully skips if the extension is unavailable or offline.  The
        EmbeddingStore still works via list_cosine_similarity() without vss;
        the extension only adds ANN index support for large embedding sets.
        """
        try:
            self._conn.execute("INSTALL vss FROM community")
        except Exception:
            pass
        try:
            self._conn.execute("LOAD vss")
            self._vss_available = True
        except Exception:
            self._vss_available = False

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create all node/edge tables and register the property graph."""
        _duckpgq_init_schema(self._conn)
        self._ensure_meta()

    def schema_version(self) -> int | None:
        """Return the stored schema version, or None if no metadata exists."""
        try:
            row = self._conn.execute(
                "SELECT schemaVersion FROM GraphMeta WHERE id = 'singleton'"
            ).fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    def schema_current(self) -> bool:
        """Return True if the stored schema version matches the code version."""
        stored = self.schema_version()
        return stored is not None and stored == SCHEMA_VERSION

    def _ensure_meta(self) -> None:
        """Create or update the singleton GraphMeta row."""
        now = datetime.now(timezone.utc).isoformat()
        if self.schema_version() is None:
            self._conn.execute(
                "INSERT INTO GraphMeta"
                " (id, schemaVersion, lastIndexed, pipelineState, phasesCompleted)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT DO NOTHING",
                ["singleton", SCHEMA_VERSION, now, "initialized", "[]"],
            )
        else:
            self._conn.execute(
                "UPDATE GraphMeta SET schemaVersion = ?, lastIndexed = ? WHERE id = 'singleton'",
                [SCHEMA_VERSION, now],
            )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def execute(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a SQL query and return the raw DuckDB result cursor."""
        if params:
            return self._conn.execute(query, list(params.values()))
        return self._conn.execute(query)

    def _reregister_property_graph(self) -> None:
        """Re-register the property graph for this connection.

        DuckPGQ's property graph name is connection-global. If another
        connection called DROP+CREATE on the same graph name, this connection
        loses its graph registration. This method recovers by re-running
        DROP+CREATE on this connection.

        Handles the case where DROP silently no-ops and CREATE then raises
        "already exists" by swallowing the duplicate-create error.
        """
        from agentscaffold.graph.duckpgq_schema import (
            CREATE_PROPERTY_GRAPH_SQL,
            DROP_PROPERTY_GRAPH_SQL,
        )

        try:
            self._conn.execute(DROP_PROPERTY_GRAPH_SQL)
        except Exception:
            pass  # IF EXISTS should not raise, but guard anyway
        try:
            self._conn.execute(CREATE_PROPERTY_GRAPH_SQL)
        except Exception as exc:
            if "already exists" not in str(exc):
                raise

    def query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as a list of dicts.

        Column names in returned dicts are the raw SQL column names.
        Use ``query_compat.py`` for backend-agnostic queries.
        """
        try:
            if params:
                result = self._conn.execute(query, list(params.values()))
            else:
                result = self._conn.execute(query)
        except Exception as exc:
            if "Property graph" in str(exc) and "does not exist" in str(exc):
                self._reregister_property_graph()
                if params:
                    result = self._conn.execute(query, list(params.values()))
                else:
                    result = self._conn.execute(query)
            else:
                raise
        if result is None or result.description is None:
            return []
        cols = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(cols, row)) for row in rows]

    def query_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a query expected to return a single scalar value."""
        if params:
            result = self._conn.execute(query, list(params.values()))
        else:
            result = self._conn.execute(query)
        row = result.fetchone() if result else None
        return row[0] if row else None

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def create_node(self, table: str, props: dict[str, Any]) -> None:
        """Insert a single node (row) into the given table.

        Silently ignores duplicate ``id`` values (ON CONFLICT DO NOTHING).
        None values are stored as empty strings.
        """
        if not props:
            return
        cols = list(props.keys())
        placeholders = ", ".join(["?" for _ in cols])
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
            " ON CONFLICT DO NOTHING"
        )
        vals = [v if v is not None else "" for v in props.values()]
        self._conn.execute(sql, vals)

    def create_edge(
        self,
        rel_table: str,
        from_table: str,  # noqa: ARG002 — kept for protocol compatibility
        from_id: str,
        to_table: str,  # noqa: ARG002 — kept for protocol compatibility
        to_id: str,
        props: dict[str, Any] | None = None,
    ) -> None:
        """Insert a single edge (src, dst, ...) into an edge table.

        ``from_table`` and ``to_table`` are accepted for protocol compatibility
        but are not used — the edge table's src/dst columns already encode the
        relationship directionality.

        The insert is idempotent on ``(src, dst)``: a relationship between the
        same pair of nodes in the same edge table is created at most once. This
        mirrors ``create_node``'s ON CONFLICT DO NOTHING semantics and prevents
        duplicate edges from accumulating when a processor re-runs over the same
        files (e.g. incremental indexing). All edge tables in the schema model a
        single logical relationship per node pair, so deduplicating on
        ``(src, dst)`` is semantically correct; edge properties (confidence,
        importedNames, changeType) are retained from the first insert.
        """
        cols = ["src", "dst"]
        vals: list[Any] = [from_id, to_id]
        if props:
            cols += list(props.keys())
            vals += [v if v is not None else "" for v in props.values()]
        placeholders = ", ".join(["?" for _ in cols])
        sql = (
            f"INSERT INTO {rel_table} ({', '.join(cols)})"
            f" SELECT {placeholders}"
            f" WHERE NOT EXISTS"
            f" (SELECT 1 FROM {rel_table} WHERE src = ? AND dst = ?)"
        )
        self._conn.execute(sql, [*vals, from_id, to_id])

    def node_count(self, table: str) -> int:
        """Return the number of rows in a node table."""
        val = self.query_scalar(f"SELECT COUNT(*) FROM {table}")
        return int(val) if val is not None else 0

    def edge_count(self, rel_table: str) -> int:
        """Return the number of rows in an edge table."""
        val = self.query_scalar(f"SELECT COUNT(*) FROM {rel_table}")
        return int(val) if val is not None else 0

    def clear_table(self, table: str) -> None:
        """Delete all rows from a node table, cascading to referencing edges.

        Iterates all edge tables and deletes rows whose src or dst references
        the given node table, then deletes all rows from the node table itself.
        """
        for edge_table in _EDGE_TABLE_NAMES:
            try:
                self._conn.execute(
                    f"DELETE FROM {edge_table}"
                    f" WHERE src IN (SELECT id FROM {table})"
                    f" OR dst IN (SELECT id FROM {table})"
                )
            except Exception:
                pass  # Edge table may not reference this node type
        self._conn.execute(f"DELETE FROM {table}")

    def clear_all(self) -> None:
        """Close the database, delete the file, and reinitialize from scratch."""
        self._conn.close()
        db_str = str(self._db_path)
        if db_str != ":memory:":
            if self._db_path.is_dir():
                shutil.rmtree(self._db_path)
            elif self._db_path.exists():
                self._db_path.unlink()
            wal = self._db_path.with_suffix(self._db_path.suffix + ".wal")
            if wal.exists():
                wal.unlink()
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(db_str)
        self._load_extension()
        _duckpgq_init_schema(self._conn, force_recreate_graph=True)
        self._ensure_meta()

    def clear_derived(self) -> None:
        """Clear index-derived data while preserving user-generated knowledge.

        Keeps: ReviewFinding (+ edges), Session (+ edges)
        Clears: everything else (files, functions, classes, communities, governance, etc.)

        This is the correct method for full re-indexing -- learned knowledge
        (review findings, sessions) survives while derived data is rebuilt.
        """
        # Tables that represent knowledge gained through work, not derived from code
        preserve_nodes = {"ReviewFinding", "BacklogItem", "Session", "GraphMeta"}
        preserve_edges = {
            "FINDING_ABOUT_FILE",
            "FINDING_ABOUT_FUNC",
            "FINDING_LED_TO",
            "FINDING_ADDRESSED_BY",
            "SESSION_MODIFIED",
        }

        # Drop and recreate the property graph (required before table changes)
        from agentscaffold.graph.duckpgq_schema import (
            DROP_PROPERTY_GRAPH_SQL,
        )

        try:
            self._conn.execute(DROP_PROPERTY_GRAPH_SQL)
        except Exception:
            pass

        # Clear derived edge tables
        for edge_table in _EDGE_TABLE_NAMES:
            if edge_table not in preserve_edges:
                try:
                    self._conn.execute(f"DELETE FROM {edge_table}")
                except Exception:
                    pass

        # Clear derived node tables
        from agentscaffold.graph.duckpgq_schema import NODE_TABLES

        for stmt in NODE_TABLES:
            # Extract table name from CREATE TABLE IF NOT EXISTS <name>
            table_name = stmt.strip().split("(")[0].split()[-1]
            if table_name not in preserve_nodes:
                try:
                    self._conn.execute(f"DELETE FROM {table_name}")
                except Exception:
                    pass

        # Clear auxiliary tables except GraphMeta
        try:
            self._conn.execute("DELETE FROM EmbeddingStore")
        except Exception:
            pass
        try:
            self._conn.execute("DELETE FROM ParsingWarning")
        except Exception:
            pass

        # Recreate the property graph
        from agentscaffold.graph.duckpgq_schema import CREATE_PROPERTY_GRAPH_SQL

        self._conn.execute(CREATE_PROPERTY_GRAPH_SQL)

    def clear_governance(self) -> None:
        """Delete governance nodes and edges so they can be re-ingested cleanly.

        Used before re-running ``process_governance`` (notably in incremental
        indexing) to avoid stale plan/contract/learning edges lingering after a
        governance document changes. Preserves ReviewFinding, BacklogItem and
        Session knowledge, matching ``clear_derived``'s preservation policy.

        Uses plain DELETE (DML), so the registered property graph is unaffected.
        """
        for edge_table in _GOVERNANCE_EDGE_TABLES:
            try:
                self._conn.execute(f"DELETE FROM {edge_table}")
            except Exception:
                pass
        for node_table in _GOVERNANCE_NODE_TABLES:
            try:
                self._conn.execute(f"DELETE FROM {node_table}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Pipeline state management
    # ------------------------------------------------------------------

    def update_pipeline_state(self, state: str, phases_completed: list[str]) -> None:
        """Update the pipeline execution state in the GraphMeta singleton."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE GraphMeta"
            " SET pipelineState = ?, phasesCompleted = ?, lastIndexed = ?"
            " WHERE id = 'singleton'",
            [state, json.dumps(phases_completed), now],
        )

    def get_pipeline_state(self) -> dict[str, Any]:
        """Return current pipeline state from the GraphMeta singleton."""
        row = self._conn.execute(
            "SELECT pipelineState, phasesCompleted, lastIndexed"
            " FROM GraphMeta WHERE id = 'singleton'"
        ).fetchone()
        if not row:
            return {"state": "unknown", "phases_completed": [], "last_indexed": None}
        state, phases_raw, last_indexed = row
        try:
            phases = json.loads(phases_raw) if phases_raw else []
        except (json.JSONDecodeError, TypeError):
            phases = []
        return {
            "state": state or "unknown",
            "phases_completed": phases,
            "last_indexed": last_indexed,
        }

    def add_parsing_warning(
        self,
        warning_id: str,
        file_path: str,
        phase: str,
        message: str,
        severity: str = "warning",
    ) -> None:
        """Record a parsing warning for later review."""
        self.create_node(
            "ParsingWarning",
            {
                "id": warning_id,
                "filePath": file_path,
                "phase": phase,
                "message": message,
                "severity": severity,
            },
        )

    def get_parsing_warnings(self) -> list[dict[str, Any]]:
        """Return all parsing warnings ordered by severity descending."""
        return self.query(
            "SELECT filePath, phase, message, severity FROM ParsingWarning ORDER BY severity DESC"
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the graph."""
        meta = self.get_pipeline_state()
        return {
            "schema_version": SCHEMA_VERSION,
            "last_indexed": meta["last_indexed"],
            "pipeline_state": meta["state"],
            "phases_completed": meta["phases_completed"],
            "files": self.node_count("File"),
            "folders": self.node_count("Folder"),
            "functions": self.node_count("Function"),
            "classes": self.node_count("Class"),
            "methods": self.node_count("Method"),
            "interfaces": self.node_count("Interface"),
            "imports_edges": self.edge_count("IMPORTS"),
            "calls_edges": self.edge_count("CALLS"),
            "communities": self.node_count("Community"),
            "plans": self.node_count("Plan"),
            "contracts": self.node_count("Contract"),
            "learnings": self.node_count("Learning"),
            "studies": self.node_count("Study"),
            "adrs": self.node_count("ADR"),
            "spikes": self.node_count("Spike"),
            "review_findings": self.node_count("ReviewFinding"),
            "backlog_items": self.node_count("BacklogItem"),
            "parsing_warnings": self.node_count("ParsingWarning"),
        }

    # ------------------------------------------------------------------
    # Embeddings (Step A.8)
    # ------------------------------------------------------------------

    def store_embedding(
        self,
        node_id: str,
        node_type: str,
        vector: list[float],
    ) -> None:
        """Insert or replace a float-array embedding for a node.

        Args:
            node_id:   The node's ``id`` value.
            node_type: The node table name (e.g. ``"Function"``).
            vector:    Embedding as a plain Python list of floats.
        """
        self._conn.execute(
            "INSERT INTO EmbeddingStore (node_id, node_type, embedding)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT (node_id, node_type) DO UPDATE SET embedding = excluded.embedding",
            [node_id, node_type, vector],
        )

    def embeddings_count(self, node_type: str) -> int:
        """Return the number of stored embeddings for a given node type."""
        val = self.query_scalar(
            f"SELECT COUNT(*) FROM EmbeddingStore WHERE node_type = '{node_type}'"
        )
        return int(val) if val is not None else 0

    def search_similar_vss(
        self,
        node_type: str,
        query_vector: list[float],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Approximate nearest-neighbour search using DuckDB list functions.

        Uses ``list_cosine_similarity`` for exact cosine similarity over the
        EmbeddingStore.  When the vss extension is loaded, the same table can
        be accelerated with an HNSW index; query syntax is unchanged.

        Returns a list of dicts with ``node_id`` and ``similarity`` keys,
        ordered by similarity descending.
        """
        result = self._conn.execute(
            "SELECT node_id,"
            " list_cosine_similarity(embedding, ?) AS similarity"
            " FROM EmbeddingStore"
            " WHERE node_type = ?"
            " ORDER BY similarity DESC"
            " LIMIT ?",
            [query_vector, node_type, top_k],
        )
        if result is None or result.description is None:
            return []
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> DuckPGQBackend:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
