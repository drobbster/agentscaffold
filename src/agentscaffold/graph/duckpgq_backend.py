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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscaffold.config import PROJECT_DELIMITER
from agentscaffold.graph.duckpgq_schema import (
    EDGE_TABLE_NAMES,
    NODE_TABLE_NAMES,
    SCHEMA_VERSION,
)
from agentscaffold.graph.duckpgq_schema import init_schema as _duckpgq_init_schema

logger = logging.getLogger(__name__)

# Node tables that carry no ``project`` column (Plan 225): GraphMeta is
# workspace-global and Project is the namespace itself. Mirrors
# duckpgq_schema._PROJECT_SCOPED_EXCLUDE.
_NO_PROJECT_COLUMN: frozenset[str] = frozenset({"GraphMeta", "Project"})

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]

_EXTRAS_MSG = "DuckPGQ backend requires duckdb: pip install agentscaffold[graph-duckpgq]"
_EXT_MSG = (
    "DuckPGQ backend requires the duckpgq community extension. "
    "Run: INSTALL duckpgq FROM community; LOAD duckpgq in DuckDB. "
    "If you are offline, the extension must already be installed in the DuckDB "
    "extension cache."
)
_LOCK_MSG = (
    "Could not open the knowledge graph at {path}: another process -- likely the "
    "MCP server or a running 'scaffold index' -- holds a write lock on it. "
    "Close the other AgentScaffold process (or stop the MCP server) and retry."
)


class GraphLockError(RuntimeError):
    """Raised when the graph database is locked by another process."""


class GraphCorruptionError(RuntimeError):
    """Raised when a multi-project write would corrupt cross-project isolation.

    The choke-point check-before-insert (Plan 225) raises this if a node ID is
    about to be written under one project while it already exists under another
    -- a signal that ID-prefixing or project stamping has gone wrong. Prefixing
    structurally prevents cross-project collisions, so this should never fire in
    practice; it is a fail-loud safety net (the spike showed a post-index
    invariant cannot see a silently-dropped row).
    """


def _is_lock_error(exc: Exception) -> bool:
    """Return True if *exc* looks like a DuckDB file-lock contention error."""
    message = str(exc).lower()
    if "could not set lock" in message or "conflicting lock" in message:
        return True
    io_exc = getattr(duckdb, "IOException", None) if duckdb is not None else None
    if io_exc is not None and isinstance(exc, io_exc):
        return "lock" in message
    return False


def _connect(
    db_str: str,
    *,
    retries: int = 4,
    backoff: float = 0.2,
    read_only: bool = False,
):
    """Open a DuckDB connection, retrying briefly on lock contention.

    Non-lock errors propagate immediately. After the bounded retry budget is
    exhausted a :class:`GraphLockError` is raised with actionable guidance.
    In-memory databases never lock, so they are returned on the first try.

    ``read_only=True`` uses DuckDB's READ_ONLY access mode. Prefer the default
    (writable) configuration for same-process concurrent readers during an
    in-process index: DuckDB rejects a second connection that differs in
    access mode from an existing writer (Plan 244 spike).
    """
    if duckdb is None:
        raise ImportError(_EXTRAS_MSG)
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            if read_only:
                return duckdb.connect(db_str, read_only=True)
            return duckdb.connect(db_str)
        except Exception as exc:
            if not _is_lock_error(exc):
                raise
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff * (2**attempt))
    raise GraphLockError(_LOCK_MSG.format(path=db_str)) from last_exc


# Edge and node table names are imported from duckpgq_schema (single source of
# truth, derived from EDGE_DEFS / NODE_TABLES) so they cannot drift here.

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

# Preserved user/agent knowledge -- survives a schema-version rebuild via
# export_governance()/import_governance() rather than being wiped by clear_all().
# Mirrors clear_derived()'s preservation policy.
_PRESERVED_NODE_TABLES: tuple[str, ...] = (
    "ReviewFinding",
    "BacklogItem",
    "Session",
    "GraphMeta",
)
_PRESERVED_EDGE_TABLES: tuple[str, ...] = (
    "FINDING_ABOUT_FILE",
    "FINDING_ABOUT_FUNC",
    "FINDING_LED_TO",
    "FINDING_ADDRESSED_BY",
    "SESSION_MODIFIED",
    "BACKLOG_ITEM_OF",
)


class DuckPGQBackend:
    """DuckDB + DuckPGQ implementation of the GraphBackend protocol.

    Uses SQL for all queries and DuckPGQ GRAPH_TABLE for graph traversals.
    Use ``open_graph(config, backend='duckpgq')`` from ``agentscaffold.graph``
    to obtain an instance rather than instantiating this class directly.
    """

    def __init__(self, db_path: Path | str, *, read_only: bool = False) -> None:
        if duckdb is None:
            raise ImportError(_EXTRAS_MSG)

        self._db_path = Path(db_path) if str(db_path) != ":memory:" else Path(":memory:")
        if str(db_path) != ":memory:" and not read_only:
            from agentscaffold.paths import ensure_parent_dir

            ensure_parent_dir(self._db_path)

        # AgentScaffold read-preferring open (Plan 244). Does not force DuckDB
        # READ_ONLY mode -- same-process concurrent readers must match the
        # writer's access mode. Guards mutation helpers instead.
        self._read_only = read_only
        # Short retries for read-preferring opens so MCP tools soft-defer quickly
        # when another *process* holds the DuckDB file lock.
        retries = 2 if read_only else 4
        backoff = 0.05 if read_only else 0.2
        self._conn = _connect(
            str(db_path),
            retries=retries,
            backoff=backoff,
            read_only=False,
        )
        # Active write project (Plan 225). None == single-project mode: writes
        # are unprefixed and unstamped, exactly as before. When set (multi-project
        # indexing of one project), create_node/create_edge/store_embedding
        # project-qualify IDs and stamp the project column at this choke point.
        self._write_project: str | None = None
        self._load_extension()
        if not self._read_only:
            from agentscaffold.graph.duckpgq_schema import ensure_additive_columns

            ensure_additive_columns(self._conn)

    def _ensure_writable(self) -> None:
        if self._read_only:
            raise RuntimeError(
                "Knowledge graph was opened read-preferring; mutations are not allowed."
            )

    def _load_extension(self) -> None:
        """Install and load the duckpgq community extension."""
        try:
            self._conn.execute("INSTALL duckpgq FROM community")
        except Exception as exc:
            # Already installed or offline; try to load from cache anyway, but
            # record the cause so a later LOAD failure is explainable.
            logger.debug("INSTALL duckpgq failed (continuing to LOAD from cache): %s", exc)
        try:
            self._conn.execute("LOAD duckpgq")
        except Exception as exc:
            logger.warning("Failed to LOAD duckpgq extension: %s", exc)
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
        except Exception as exc:
            logger.debug("vss extension unavailable (semantic search still works): %s", exc)
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

    # -- Multi-project write scope (Plan 225) -------------------------------

    @property
    def write_project(self) -> str | None:
        """The active write project, or None in single-project mode."""
        return self._write_project

    def set_write_project(self, project: str | None) -> None:
        """Set the active write project for subsequent create_* calls.

        ``None`` restores single-project behavior (no prefixing/stamping). A
        string switches the choke point into multi-project mode for that project:
        IDs are qualified as ``{project}::{raw_id}`` and the ``project`` column is
        stamped. The indexing pipeline sets this per project.
        """
        self._write_project = project

    def _qualify(self, raw_id: str) -> str:
        """Project-qualify a raw ID under the active write project (idempotent)."""
        wp = self._write_project
        if wp is None:
            return raw_id
        prefix = f"{wp}{PROJECT_DELIMITER}"
        return raw_id if raw_id.startswith(prefix) else f"{prefix}{raw_id}"

    def _guard_collision(self, table: str, node_id: str, project: str) -> None:
        """Check-before-insert guard: fail loud on a cross-project ID collision.

        Cheap PK lookup, multi-project mode only. Prefixing makes a true
        collision structurally impossible, so this only fires if stamping and
        prefixing disagree (a logic error), which a post-index invariant could
        not detect once a row was silently dropped.
        """
        try:
            row = self._conn.execute(
                f"SELECT project FROM {table} WHERE id = ?", [node_id]
            ).fetchone()
        except Exception:
            return
        if row is not None and row[0] not in (None, "", project):
            raise GraphCorruptionError(
                f"Node id {node_id!r} already exists in {table} under project "
                f"{row[0]!r}; refusing to write it under {project!r}."
            )

    def create_node(self, table: str, props: dict[str, Any]) -> None:
        """Insert a single node (row) into the given table.

        Silently ignores duplicate ``id`` values (ON CONFLICT DO NOTHING).
        None values are stored as empty strings. In multi-project mode the node
        ID is project-qualified and the ``project`` column is stamped at this
        choke point (with a check-before-insert collision guard).
        """
        self._ensure_writable()
        if not props:
            return
        wp = self._write_project
        if wp is not None and table not in _NO_PROJECT_COLUMN:
            props = dict(props)
            if props.get("id") is not None:
                props["id"] = self._qualify(str(props["id"]))
            props["project"] = wp
            if props.get("id"):
                self._guard_collision(table, str(props["id"]), wp)
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
        self._ensure_writable()
        # Multi-project: qualify both endpoints under the active write project so
        # the edge references the same prefixed node IDs create_node produced.
        # Cross-project edges are a non-goal, so both endpoints share the prefix.
        if self._write_project is not None:
            from_id = self._qualify(from_id)
            to_id = self._qualify(to_id)
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

    def clear_table(self, table: str, project: str | None = None) -> None:
        """Delete rows from a node table, cascading to referencing edges.

        Iterates all edge tables and deletes rows whose src or dst references
        the given node table, then deletes from the node table itself. When
        *project* is given (multi-project), only that project's rows (and the
        edges referencing them) are deleted, leaving sibling projects intact;
        when None, all rows are deleted (single-project behavior).
        """
        self._ensure_writable()
        node_filter = "" if project is None else " WHERE project = ?"
        node_params: list[Any] = [] if project is None else [project]
        for edge_table in EDGE_TABLE_NAMES:
            try:
                self._conn.execute(
                    f"DELETE FROM {edge_table}"
                    f" WHERE src IN (SELECT id FROM {table}{node_filter})"
                    f" OR dst IN (SELECT id FROM {table}{node_filter})",
                    node_params + node_params,
                )
            except Exception:
                pass  # Edge table may not reference this node type
        self._conn.execute(f"DELETE FROM {table}{node_filter}", node_params)

    def clear_all(self) -> None:
        """Close the database, delete the file, and reinitialize from scratch."""
        self._ensure_writable()
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
            from agentscaffold.paths import ensure_parent_dir

            ensure_parent_dir(self._db_path)
        self._conn = _connect(db_str)
        self._load_extension()
        _duckpgq_init_schema(self._conn, force_recreate_graph=True)
        self._ensure_meta()

    def clear_derived(self, project: str | None = None) -> None:
        """Clear index-derived data while preserving user-generated knowledge.

        Keeps: ReviewFinding (+ edges), Session (+ edges)
        Clears: everything else (files, functions, classes, communities, governance, etc.)

        This is the correct method for full re-indexing -- learned knowledge
        (review findings, sessions) survives while derived data is rebuilt.

        When *project* is given (multi-project), only that project's derived data
        is cleared, leaving siblings intact: node/auxiliary rows are filtered by
        the ``project`` column and edges by their project-prefixed endpoints
        (``{project}::%``). When None, everything is cleared (single-project).
        """
        self._ensure_writable()
        # Tables that represent knowledge gained through work, not derived from code
        preserve_nodes = {"ReviewFinding", "BacklogItem", "Session", "GraphMeta"}
        preserve_edges = {
            "FINDING_ABOUT_FILE",
            "FINDING_ABOUT_FUNC",
            "FINDING_LED_TO",
            "FINDING_ADDRESSED_BY",
            "SESSION_MODIFIED",
        }

        node_filter = "" if project is None else " WHERE project = ?"
        node_params: list[Any] = [] if project is None else [project]
        like = None if project is None else f"{project}{PROJECT_DELIMITER}%"

        # Drop and recreate the property graph (required before table changes)
        from agentscaffold.graph.duckpgq_schema import (
            DROP_PROPERTY_GRAPH_SQL,
        )

        try:
            self._conn.execute(DROP_PROPERTY_GRAPH_SQL)
        except Exception:
            pass

        # Clear derived edge tables (scoped by prefixed endpoints in multi-project)
        for edge_table in EDGE_TABLE_NAMES:
            if edge_table not in preserve_edges:
                try:
                    if like is None:
                        self._conn.execute(f"DELETE FROM {edge_table}")
                    else:
                        self._conn.execute(
                            f"DELETE FROM {edge_table} WHERE src LIKE ? OR dst LIKE ?",
                            [like, like],
                        )
                except Exception:
                    pass

        # Clear derived node tables (scoped by project column in multi-project)
        for table_name in NODE_TABLE_NAMES:
            if table_name not in preserve_nodes:
                try:
                    self._conn.execute(f"DELETE FROM {table_name}{node_filter}", node_params)
                except Exception:
                    pass

        # Clear auxiliary tables except GraphMeta
        try:
            self._conn.execute(f"DELETE FROM EmbeddingStore{node_filter}", node_params)
        except Exception:
            pass

        # Recreate the property graph
        from agentscaffold.graph.duckpgq_schema import CREATE_PROPERTY_GRAPH_SQL

        self._conn.execute(CREATE_PROPERTY_GRAPH_SQL)

    def clear_governance(self, project: str | None = None) -> None:
        """Delete governance nodes and edges so they can be re-ingested cleanly.

        Used before re-running ``process_governance`` (notably in incremental
        indexing) to avoid stale plan/contract/learning edges lingering after a
        governance document changes. Preserves ReviewFinding, BacklogItem and
        Session knowledge, matching ``clear_derived``'s preservation policy.

        When *project* is given (multi-project), only that project's governance
        is cleared (nodes by ``project`` column, edges by prefixed endpoints),
        leaving siblings intact. Uses plain DELETE (DML), so the registered
        property graph is unaffected.
        """
        self._ensure_writable()
        node_filter = "" if project is None else " WHERE project = ?"
        node_params: list[Any] = [] if project is None else [project]
        like = None if project is None else f"{project}{PROJECT_DELIMITER}%"
        for edge_table in _GOVERNANCE_EDGE_TABLES:
            try:
                if like is None:
                    self._conn.execute(f"DELETE FROM {edge_table}")
                else:
                    self._conn.execute(
                        f"DELETE FROM {edge_table} WHERE src LIKE ? OR dst LIKE ?",
                        [like, like],
                    )
            except Exception:
                pass
        for node_table in _GOVERNANCE_NODE_TABLES:
            try:
                self._conn.execute(f"DELETE FROM {node_table}{node_filter}", node_params)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Single -> multi-project mode flip (Plan 225)
    # ------------------------------------------------------------------

    def migrate_to_multi_project(self, project: str) -> dict[str, int]:
        """Atomically re-key the existing single-project graph into *project*.

        When a lone repo gains a sibling, the rows already in the shared cache
        are unprefixed (id ``plan::1``, ``project = ''``) and must be rewritten
        to ``{project}::plan::1`` with the ``project`` column stamped, so the new
        sibling's identically-named nodes cannot collide. Node ids, every edge
        endpoint, and embedding ``node_id``s are rewritten inside one
        transaction; any failure rolls the whole thing back so the cache is never
        left half-migrated (the spike showed a partial migration is the worst
        outcome). Idempotent: rows already prefixed for *project* are skipped, so
        re-running is a safe no-op. Returns per-category rewrite counts.

        The property graph is dropped before and recreated after the structural
        id rewrites (CREATE PROPERTY GRAPH is not transactional), and is always
        recreated even on rollback so the graph is never left unregistered.
        """
        from agentscaffold.config import validate_project_name
        from agentscaffold.graph.duckpgq_schema import (
            CREATE_PROPERTY_GRAPH_SQL,
            DROP_PROPERTY_GRAPH_SQL,
        )

        validate_project_name(project)
        prefix = f"{project}{PROJECT_DELIMITER}"
        like = f"{prefix}%"
        counts = {"nodes": 0, "edges": 0, "embeddings": 0}

        # Pre-count the rows that will actually be rewritten (project='' and not
        # already prefixed), so the return value is meaningful and idempotent.
        for table in NODE_TABLE_NAMES:
            if table in _NO_PROJECT_COLUMN:
                continue
            counts["nodes"] += int(
                self.query_scalar(
                    f"SELECT COUNT(*) FROM {table} WHERE project = '' AND id NOT LIKE ?",
                    {"like": like},
                )
                or 0
            )
        counts["embeddings"] = int(
            self.query_scalar(
                "SELECT COUNT(*) FROM EmbeddingStore WHERE project = '' AND node_id NOT LIKE ?",
                {"like": like},
            )
            or 0
        )
        for edge_table in EDGE_TABLE_NAMES:
            counts["edges"] += int(
                self.query_scalar(
                    f"SELECT COUNT(*) FROM {edge_table} WHERE src NOT LIKE ?",
                    {"like": like},
                )
                or 0
            )

        try:
            self._conn.execute(DROP_PROPERTY_GRAPH_SQL)
        except Exception:
            pass

        self._conn.execute("BEGIN TRANSACTION")
        try:
            for table in NODE_TABLE_NAMES:
                if table in _NO_PROJECT_COLUMN:
                    continue
                self._conn.execute(
                    f"UPDATE {table} SET id = ? || id, project = ?"
                    " WHERE project = '' AND id NOT LIKE ?",
                    [prefix, project, like],
                )
            for edge_table in EDGE_TABLE_NAMES:
                self._conn.execute(
                    f"UPDATE {edge_table} SET src = ? || src WHERE src NOT LIKE ?",
                    [prefix, like],
                )
                self._conn.execute(
                    f"UPDATE {edge_table} SET dst = ? || dst WHERE dst NOT LIKE ?",
                    [prefix, like],
                )
            self._conn.execute(
                "UPDATE EmbeddingStore SET node_id = ? || node_id, project = ?"
                " WHERE project = '' AND node_id NOT LIKE ?",
                [prefix, project, like],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        finally:
            self._conn.execute(CREATE_PROPERTY_GRAPH_SQL)
        return counts

    def verify_integrity(self) -> list[str]:
        """Return multi-project invariant violations (empty list == healthy).

        Invariant: any project-stamped node row must carry the matching
        ``{project}::`` id prefix, and no row may be stamped with a project while
        its id is bare. This is the post-migration / post-index safety net the
        spike recommended; the CLI runs it after a mode flip.
        """
        problems: list[str] = []
        for table in NODE_TABLE_NAMES:
            if table in _NO_PROJECT_COLUMN:
                continue
            try:
                rows = self._conn.execute(
                    f"SELECT id, project FROM {table}"
                    f" WHERE project <> '' AND id NOT LIKE project || '{PROJECT_DELIMITER}' || '%'"
                ).fetchall()
            except Exception:
                continue
            for r in rows:
                problems.append(
                    f"{table}: id {r[0]!r} is stamped project {r[1]!r} but lacks its id prefix"
                )
        return problems

    # ------------------------------------------------------------------
    # Governance export / import (schema migration safety)
    # ------------------------------------------------------------------

    def _table_columns(self, table: str) -> list[str]:
        """Return the column names of a table, or [] if it does not exist."""
        try:
            rows = self._conn.execute(f"PRAGMA table_info('{table}')").fetchall()
        except Exception:
            return []
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        return [row[1] for row in rows]

    def export_governance(self) -> dict[str, Any]:
        """Export preserved user/agent knowledge to a plain dict.

        Covers the preserved node tables (ReviewFinding, BacklogItem, Session,
        GraphMeta) and preserved edges (FINDING_*, SESSION_MODIFIED,
        BACKLOG_ITEM_OF). Each table records its column list so
        ``import_governance`` can perform per-table compatibility checks. Tables
        that do not exist in the current (old) schema are skipped.

        This is the data-preservation step run *before* a destructive
        schema-version rebuild. It must succeed before any rebuild proceeds.
        """
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}

        for table in _PRESERVED_NODE_TABLES:
            columns = self._table_columns(table)
            if not columns:
                continue
            nodes[table] = {
                "columns": columns,
                "rows": self.query(f"SELECT * FROM {table}"),
            }

        for table in _PRESERVED_EDGE_TABLES:
            columns = self._table_columns(table)
            if not columns:
                continue
            edges[table] = {
                "columns": columns,
                "rows": self.query(f"SELECT * FROM {table}"),
            }

        return {
            "export_schema_version": self.schema_version(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes,
            "edges": edges,
        }

    def import_governance(self, data: dict[str, Any]) -> dict[str, Any]:
        """Re-import governance previously produced by ``export_governance``.

        Performs a per-table column compatibility check: only columns present in
        BOTH the export and the current schema are inserted. A table whose
        primary key (``id`` for nodes, ``src``/``dst`` for edges) is missing from
        the current schema is skipped and reported, and the overall result is
        marked ``compatible=False`` so the caller can keep the export file and
        warn the user. GraphMeta inserts are idempotent no-ops (the freshly
        initialized singleton already exists), so the new schema version is
        never reverted.

        Returns a summary dict: ``imported`` (per-table counts), ``skipped``
        (per-table reasons), and ``compatible`` (bool).
        """
        self._ensure_writable()
        imported: dict[str, int] = {}
        skipped: dict[str, str] = {}
        compatible = True

        node_data = data.get("nodes", {})
        for table, payload in node_data.items():
            current_cols = set(self._table_columns(table))
            if not current_cols:
                skipped[table] = "table absent from current schema"
                compatible = False
                continue
            if "id" not in current_cols:
                skipped[table] = "primary key 'id' absent from current schema"
                compatible = False
                continue
            usable = [c for c in payload.get("columns", []) if c in current_cols]
            count = 0
            for row in payload.get("rows", []):
                props = {c: row.get(c) for c in usable}
                if not props.get("id"):
                    continue
                self.create_node(table, props)
                count += 1
            imported[table] = count

        edge_data = data.get("edges", {})
        for table, payload in edge_data.items():
            current_cols = set(self._table_columns(table))
            if not current_cols:
                skipped[table] = "edge table absent from current schema"
                compatible = False
                continue
            if not {"src", "dst"} <= current_cols:
                skipped[table] = "src/dst columns absent from current schema"
                compatible = False
                continue
            prop_cols = [
                c
                for c in payload.get("columns", [])
                if c in current_cols and c not in ("src", "dst")
            ]
            count = 0
            for row in payload.get("rows", []):
                src = row.get("src")
                dst = row.get("dst")
                if not src or not dst:
                    continue
                props = {c: row.get(c) for c in prop_cols}
                self.create_edge(table, "", src, "", dst, props or None)
                count += 1
            imported[table] = count

        return {"imported": imported, "skipped": skipped, "compatible": compatible}

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
            "sessions": self.node_count("Session"),
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
        *,
        model: str = "",
        text_hash: str = "",
    ) -> None:
        """Insert or replace a float-array embedding for a node.

        Args:
            node_id:   The node's ``id`` value.
            node_type: The node table name (e.g. ``"Function"``).
            vector:    Embedding as a plain Python list of floats.
            model:     Embedding model that produced the vector.
            text_hash: Stable hash of the embedded text, used for incremental skips.

        In multi-project mode the ``node_id`` is project-qualified to match the
        node tables and the ``project`` column is stamped, so embedding search
        can be scoped/federated and scoped-cleared like the rest of the graph.
        """
        self._ensure_writable()
        model = model or "all-MiniLM-L6-v2"
        if self._write_project is not None:
            self._conn.execute(
                "INSERT INTO EmbeddingStore"
                " (node_id, node_type, embedding, project, model, text_hash)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (node_id, node_type) DO UPDATE SET"
                " embedding = excluded.embedding,"
                " project = excluded.project,"
                " model = excluded.model,"
                " text_hash = excluded.text_hash",
                [self._qualify(node_id), node_type, vector, self._write_project, model, text_hash],
            )
        else:
            self._conn.execute(
                "INSERT INTO EmbeddingStore (node_id, node_type, embedding, model, text_hash)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (node_id, node_type) DO UPDATE SET"
                " embedding = excluded.embedding,"
                " model = excluded.model,"
                " text_hash = excluded.text_hash",
                [node_id, node_type, vector, model, text_hash],
            )

    def embeddings_count(self, node_type: str) -> int:
        """Return the number of stored embeddings for a given node type."""
        val = self.query_scalar(
            f"SELECT COUNT(*) FROM EmbeddingStore WHERE node_type = '{node_type}'"
        )
        return int(val) if val is not None else 0

    def ensure_embedding_hnsw_index(self) -> bool:
        """Best-effort HNSW index for EmbeddingStore when DuckDB vss is available.

        Exact cosine search is always correct and remains the fallback. This
        method only wires the optional acceleration path; failures are logged at
        debug level because many offline/minimal installs cannot install/load
        the community ``vss`` extension.
        """
        if not getattr(self, "_vss_available", False):
            return False
        try:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_embedding_store_hnsw"
                " ON EmbeddingStore USING HNSW (embedding)"
                " WITH (metric = 'cosine')"
            )
            return True
        except Exception as exc:
            logger.debug("HNSW embedding index unavailable; exact cosine remains active: %s", exc)
            return False

    def search_similar_vss(
        self,
        node_type: str,
        query_vector: list[float],
        top_k: int = 10,
        project: str | None = None,
        model: str = "all-MiniLM-L6-v2",
    ) -> list[dict[str, Any]]:
        """Approximate nearest-neighbour search using DuckDB list functions.

        Uses ``list_cosine_similarity`` for exact cosine similarity over the
        EmbeddingStore.  When the vss extension is loaded, the same table can
        be accelerated with an HNSW index; query syntax is unchanged.

        When *project* is given (multi-project), results are filtered to that
        project; when None, the search spans all projects (single-project, or an
        explicit federated query). The ``project`` column is always returned for
        per-hit provenance. Results are ordered by similarity descending.
        """
        project_filter = "" if project is None else " AND project = ?"
        params: list[Any] = [query_vector, node_type, model]
        if project is not None:
            params.append(project)
        params.append(top_k)
        result = self._conn.execute(
            "SELECT node_id, project,"
            " list_cosine_similarity(embedding, ?) AS similarity"
            " FROM EmbeddingStore"
            " WHERE node_type = ?"
            " AND model = ?"
            f"{project_filter}"
            " ORDER BY similarity DESC"
            " LIMIT ?",
            params,
        )
        if result is None or result.description is None:
            return []
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row)) for row in result.fetchall()]

    def query_class_bases(self, class_id: str) -> list[dict[str, Any]]:
        """Return EXTENDS rows leaving *class_id*, including unresolved bases.

        Uses the SQL table, not GRAPH_TABLE: a dangling ``dst`` has no Class
        vertex, so MATCH would silently omit unresolved edges.
        """
        rows = self.query(
            "SELECT e.dst AS dst, e.resolved AS resolved, e.baseName AS baseName, "
            "c.name AS name, c.filePath AS filePath "
            "FROM EXTENDS e LEFT JOIN Class c ON c.id = e.dst "
            "WHERE e.src = ?",
            {"src": class_id},
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            dst = str(row.get("dst") or "")
            resolved = bool(row.get("resolved")) or "class::" in dst
            name = row.get("name") or row.get("baseName") or ""
            result.append(
                {
                    "name": name,
                    "baseName": row.get("baseName") or name,
                    "resolved": resolved,
                    "filePath": row.get("filePath") or "",
                    "id": row.get("dst") or "",
                }
            )
        return result

    def query_class_subclasses(self, class_id: str, *, max_depth: int = 32) -> list[dict[str, Any]]:
        """Return transitive subclasses of *class_id*, depth-labelled.

        Walks resolved EXTENDS only (unresolved destinations have no children).
        Direction is dst -> src: EXTENDS points subclass -> base.
        """
        rows = self.query(
            "WITH RECURSIVE d AS ("
            "  SELECT src, 1 AS depth FROM EXTENDS "
            "  WHERE dst = ? AND (resolved = true OR dst LIKE '%class::%') "
            "  UNION ALL "
            "  SELECT e.src, d.depth + 1 FROM EXTENDS e "
            "  JOIN d ON e.dst = d.src "
            "  WHERE (e.resolved = true OR e.dst LIKE '%class::%') AND d.depth < ?"
            ") "
            "SELECT d.src AS src, d.depth AS depth, c.name AS name, "
            "c.filePath AS filePath FROM d "
            "JOIN Class c ON c.id = d.src "
            "ORDER BY d.depth, c.name",
            {"dst": class_id, "max_depth": max_depth},
        )
        return [
            {
                "name": row.get("name") or "",
                "filePath": row.get("filePath") or "",
                "id": row.get("src") or "",
                "depth": int(row.get("depth") or 0),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        finally:
            lock_cm = getattr(self, "_graph_write_lock_cm", None)
            if lock_cm is not None:
                try:
                    lock_cm.__exit__(None, None, None)
                finally:
                    setattr(self, "_graph_write_lock_cm", None)
                    setattr(self, "_graph_write_lock_active", False)

    def __enter__(self) -> DuckPGQBackend:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
