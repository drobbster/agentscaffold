"""KuzuDB adapter for the AgentScaffold knowledge graph.

Handles database lifecycle, schema initialization, query execution,
and metadata management.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentscaffold.graph.schema import SCHEMA_VERSION, all_ddl_statements

logger = logging.getLogger(__name__)

try:
    import kuzu
except ImportError:
    kuzu = None  # type: ignore[assignment]

_GRAPH_EXTRAS_MSG = "Knowledge graph requires extra dependencies: pip install agentscaffold[graph]"


class GraphStore:
    """Wrapper around KuzuDB providing schema management and query helpers."""

    def __init__(self, db_path: Path | str, *, read_only: bool = False) -> None:
        if kuzu is None:
            raise ImportError(_GRAPH_EXTRAS_MSG)

        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self._db_path), read_only=read_only)
        self._conn = kuzu.Connection(self._db)

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create all node and edge tables if they don't exist."""
        for ddl in all_ddl_statements():
            self._conn.execute(ddl.strip())
        self._ensure_meta()

    def schema_version(self) -> int | None:
        """Return the stored schema version, or None if no metadata exists."""
        try:
            result = self._conn.execute(
                "MATCH (m:GraphMeta) WHERE m.id = 'singleton' RETURN m.schemaVersion"
            )
            rows = result.get_as_df()
            if len(rows) == 0:
                return None
            return int(rows.iloc[0, 0])
        except Exception:
            return None

    def schema_current(self) -> bool:
        """Return True if the stored schema version matches the code version."""
        stored = self.schema_version()
        return stored is not None and stored == SCHEMA_VERSION

    def _ensure_meta(self) -> None:
        """Create or update the singleton GraphMeta node."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.schema_version()
        if existing is None:
            self._conn.execute(
                "CREATE (m:GraphMeta {"
                "  id: 'singleton',"
                f"  schemaVersion: {SCHEMA_VERSION},"
                f"  lastIndexed: '{now}',"
                "  pipelineState: 'initialized',"
                "  phasesCompleted: '[]'"
                "})"
            )
        else:
            self._conn.execute(
                "MATCH (m:GraphMeta) WHERE m.id = 'singleton' "
                f"SET m.schemaVersion = {SCHEMA_VERSION}, "
                f"m.lastIndexed = '{now}'"
            )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def execute(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a Cypher query and return the raw KuzuDB result."""
        if params:
            return self._conn.execute(cypher, params)
        return self._conn.execute(cypher)

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as list of dicts."""
        result = self.execute(cypher, params)
        df = result.get_as_df()
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def query_scalar(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a query expected to return a single scalar value."""
        result = self.execute(cypher, params)
        df = result.get_as_df()
        if df.empty:
            return None
        return df.iloc[0, 0]

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def create_node(self, table: str, props: dict[str, Any]) -> None:
        """Insert a single node."""
        prop_strs = []
        for k, v in props.items():
            if isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace("'", "\\'")
                prop_strs.append(f"{k}: '{escaped}'")
            elif isinstance(v, bool):
                prop_strs.append(f"{k}: {'true' if v else 'false'}")
            elif v is None:
                prop_strs.append(f"{k}: ''")
            else:
                prop_strs.append(f"{k}: {v}")
        props_cypher = ", ".join(prop_strs)
        self._conn.execute(f"CREATE (n:{table} {{{props_cypher}}})")

    def create_edge(
        self,
        rel_table: str,
        from_table: str,
        from_id: str,
        to_table: str,
        to_id: str,
        props: dict[str, Any] | None = None,
    ) -> None:
        """Insert a single edge between two existing nodes."""
        from_id_esc = from_id.replace("\\", "\\\\").replace("'", "\\'")
        to_id_esc = to_id.replace("\\", "\\\\").replace("'", "\\'")
        if props:
            prop_strs = []
            for k, v in props.items():
                if isinstance(v, str):
                    escaped = v.replace("\\", "\\\\").replace("'", "\\'")
                    prop_strs.append(f"{k}: '{escaped}'")
                elif isinstance(v, float):
                    prop_strs.append(f"{k}: {v}")
                else:
                    prop_strs.append(f"{k}: {v}")
            props_cypher = "{" + ", ".join(prop_strs) + "}"
        else:
            props_cypher = ""

        cypher = (
            f"MATCH (a:{from_table}), (b:{to_table}) "
            f"WHERE a.id = '{from_id_esc}' AND b.id = '{to_id_esc}' "
            f"CREATE (a)-[:{rel_table} {props_cypher}]->(b)"
        )
        self._conn.execute(cypher)

    def node_count(self, table: str) -> int:
        """Return the number of nodes in a table."""
        val = self.query_scalar(f"MATCH (n:{table}) RETURN count(n)")
        return int(val) if val is not None else 0

    def edge_count(self, rel_table: str) -> int:
        """Return the number of edges in a relationship table."""
        val = self.query_scalar(f"MATCH ()-[r:{rel_table}]->() RETURN count(r)")
        return int(val) if val is not None else 0

    def clear_table(self, table: str) -> None:
        """Delete all nodes (and their edges) from a node table."""
        self._conn.execute(f"MATCH (n:{table}) DELETE n")

    def clear_all(self) -> None:
        """Drop and recreate the entire schema. Use for full re-index."""
        self._db.close()
        import shutil

        if self._db_path.exists():
            if self._db_path.is_dir():
                shutil.rmtree(self._db_path)
            else:
                self._db_path.unlink()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self._db_path))
        self._conn = kuzu.Connection(self._db)
        self.init_schema()

    # ------------------------------------------------------------------
    # Pipeline state management
    # ------------------------------------------------------------------

    def update_pipeline_state(self, state: str, phases_completed: list[str]) -> None:
        """Update the pipeline execution state in metadata."""
        now = datetime.now(timezone.utc).isoformat()
        phases_json = json.dumps(phases_completed)
        self._conn.execute(
            "MATCH (m:GraphMeta) WHERE m.id = 'singleton' "
            f"SET m.pipelineState = '{state}', "
            f"m.phasesCompleted = '{phases_json}', "
            f"m.lastIndexed = '{now}'"
        )

    def get_pipeline_state(self) -> dict[str, Any]:
        """Return current pipeline state from metadata."""
        rows = self.query(
            "MATCH (m:GraphMeta) WHERE m.id = 'singleton' "
            "RETURN m.pipelineState, m.phasesCompleted, m.lastIndexed"
        )
        if not rows:
            return {"state": "unknown", "phases_completed": [], "last_indexed": None}
        row = rows[0]
        phases_raw = row.get("m.phasesCompleted", "[]")
        try:
            phases = json.loads(phases_raw)
        except (json.JSONDecodeError, TypeError):
            phases = []
        return {
            "state": row.get("m.pipelineState", "unknown"),
            "phases_completed": phases,
            "last_indexed": row.get("m.lastIndexed"),
        }

    def add_parsing_warning(
        self, warning_id: str, file_path: str, phase: str, message: str, severity: str = "warning"
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
        """Return all parsing warnings."""
        return self.query(
            "MATCH (w:ParsingWarning) "
            "RETURN w.filePath, w.phase, w.message, w.severity "
            "ORDER BY w.severity DESC"
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
            "review_findings": self.node_count("ReviewFinding"),
            "parsing_warnings": self.node_count("ParsingWarning"),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
