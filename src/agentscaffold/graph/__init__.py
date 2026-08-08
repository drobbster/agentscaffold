"""Knowledge graph subsystem for AgentScaffold.

Public API:
    index(path, config)  -- Build/rebuild the knowledge graph
    open_graph(config)   -- Open an existing graph for querying
    graph_available(config) -- Check if a graph exists
    GraphBackend         -- Protocol class for backend-agnostic type annotations
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend, GraphLockError

if TYPE_CHECKING:
    from agentscaffold.config import ScaffoldConfig

__all__ = [
    "DuckPGQBackend",
    "GraphBackend",
    "GraphLockError",
    "graph_available",
    "index",
    "open_graph",
]


def graph_available(config: ScaffoldConfig | None = None) -> bool:
    """Return True if a knowledge graph database exists on disk."""
    db_path = _resolve_db_path(config)
    return db_path.is_file()


def open_graph(
    config: ScaffoldConfig | None = None,
    *,
    backend: str | None = None,
    lock_timeout: float = 8.0,
    read_only: bool = False,
) -> GraphBackend:
    """Open an existing graph database for querying.

    Args:
        config: Optional scaffold config. Used to resolve db_path.
        backend: Reserved for future use. Only "duckpgq" is supported.
        lock_timeout: Seconds to wait for AgentScaffold's shared graph write
            lock before attempting to open DuckDB. Ignored when
            ``read_only=True`` (Plan 244): readers skip the exclusive writer
            wait so MCP tools stay responsive during in-process refresh.
        read_only: When True, open without waiting for the AgentScaffold write
            lock and without enabling governance write-through. Same-process
            concurrent readers can query while an incremental index holds the
            lock; cross-process DuckDB file locks still raise GraphLockError
            quickly for soft ``refresh_in_progress`` handling.

    Raises:
        ValueError: if an unknown backend name is given.
        GraphLockError: if the database cannot be opened (writer wait expired
            for write opens, or DuckDB file lock for read opens).
    """
    backend_name = backend or _resolve_backend(config)
    db_path = _resolve_db_path(config)

    if backend_name == "duckpgq":
        from agentscaffold.graph.locks import wait_for_graph_write_lock_clear

        if not read_only:
            if not wait_for_graph_write_lock_clear(db_path, timeout=lock_timeout):
                from agentscaffold.graph.locks import open_graph_lock_message

                raise GraphLockError(open_graph_lock_message(db_path))
        store = DuckPGQBackend(db_path, read_only=read_only)
        if not read_only:
            # Enable git-backed governance write-through (Plan 222): runtime
            # finding/session/backlog mutations re-serialize to the committed
            # artifact so the graph stays a derived index of git state.
            from agentscaffold.graph.governance_store import (
                enable_write_through,
                resolve_governance_artifact,
            )

            enable_write_through(store, resolve_governance_artifact(config))
        return store

    raise ValueError(f"Unknown backend '{backend_name}'. Supported: 'duckpgq'.")


def index(
    path: Path | None = None,
    config: ScaffoldConfig | None = None,
    *,
    incremental: bool = False,
    embeddings: bool = False,
    audit: bool = False,
    force_rebuild: bool = False,
    quiet: bool = False,
) -> dict:
    """Build or rebuild the knowledge graph.

    Returns an index summary dict with quality metrics.

    Pass ``quiet=True`` when indexing inside an MCP stdio process so Rich
    progress cannot corrupt the JSON-RPC stdout channel.
    """
    from agentscaffold.active_root import default_start
    from agentscaffold.graph.pipeline import run_pipeline

    return run_pipeline(
        root=path or default_start(),
        config=config,
        incremental=incremental,
        embeddings=embeddings,
        audit=audit,
        force_rebuild=force_rebuild,
        quiet=quiet,
    )


def _resolve_db_path(config: ScaffoldConfig | None) -> Path:
    """Resolve the graph DB path against the project root (Plan 221).

    Delegates to :func:`agentscaffold.paths.resolve_db_path` so a relative
    ``db_path`` resolves under the project root (nearest ``scaffold.yaml`` ->
    nearest ``.git`` -> cwd) instead of the bare working directory. This makes
    ``open_graph`` agree with ``run_pipeline`` when invoked from a subdirectory.
    """
    from agentscaffold.paths import resolve_db_path

    return resolve_db_path(config)


def _resolve_backend(config: ScaffoldConfig | None) -> str:
    if config is not None and hasattr(config, "graph") and hasattr(config.graph, "backend"):
        return config.graph.backend or "duckpgq"
    return "duckpgq"
