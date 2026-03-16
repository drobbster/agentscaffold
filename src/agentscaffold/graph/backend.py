"""GraphBackend Protocol: the abstract interface all graph backend implementations must satisfy.

Both KuzuBackend (KuzuDB) and DuckPGQBackend (DuckDB + duckpgq) implement this protocol,
enabling consumers to be backend-agnostic.

Usage::

    from agentscaffold.graph import open_graph
    with open_graph() as store:
        rows = store.query("...")

Design notes:
- All methods match the current GraphStore public surface exactly (audited in Plan 149 Step A.0).
- schema_version() and schema_current() are methods, not properties, so they appear in
  both implementations identically.
- The Protocol uses runtime_checkable so isinstance() checks work if needed.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GraphBackend(Protocol):
    """Structural protocol for AgentScaffold graph backends.

    Implementations must provide all methods below. They do not need to inherit
    from this class — duck typing via structural subtyping is sufficient.
    """

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create all node and edge tables if they don't exist."""
        ...

    def schema_version(self) -> int | None:
        """Return the stored schema version, or None if no metadata exists."""
        ...

    def schema_current(self) -> bool:
        """Return True if the stored schema version matches the code version."""
        ...

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def execute(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a raw query and return the backend-native result object."""
        ...

    def query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a query and return results as a list of dicts."""
        ...

    def query_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a query expected to return a single scalar value."""
        ...

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def create_node(self, table: str, props: dict[str, Any]) -> None:
        """Insert a single node into the given table."""
        ...

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
        ...

    def node_count(self, table: str) -> int:
        """Return the number of nodes in a table."""
        ...

    def edge_count(self, rel_table: str) -> int:
        """Return the number of edges in a relationship table."""
        ...

    def clear_table(self, table: str) -> None:
        """Delete all nodes (and their edges) from a node table."""
        ...

    def clear_all(self) -> None:
        """Drop and recreate the entire schema. Use for full re-index."""
        ...

    # ------------------------------------------------------------------
    # Pipeline state management
    # ------------------------------------------------------------------

    def update_pipeline_state(self, state: str, phases_completed: list[str]) -> None:
        """Update the pipeline execution state in metadata."""
        ...

    def get_pipeline_state(self) -> dict[str, Any]:
        """Return current pipeline state from metadata."""
        ...

    def add_parsing_warning(
        self,
        warning_id: str,
        file_path: str,
        phase: str,
        message: str,
        severity: str = "warning",
    ) -> None:
        """Record a parsing warning for later review."""
        ...

    def get_parsing_warnings(self) -> list[dict[str, Any]]:
        """Return all parsing warnings."""
        ...

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the graph."""
        ...

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        ...

    def __enter__(self) -> GraphBackend: ...

    def __exit__(self, *args: object) -> None: ...
