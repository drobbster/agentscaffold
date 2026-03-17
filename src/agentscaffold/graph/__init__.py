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
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

if TYPE_CHECKING:
    from agentscaffold.config import ScaffoldConfig

__all__ = [
    "DuckPGQBackend",
    "GraphBackend",
    "graph_available",
    "index",
    "open_graph",
]


def graph_available(config: ScaffoldConfig | None = None) -> bool:
    """Return True if a knowledge graph database exists on disk."""
    db_path = _resolve_db_path(config)
    return db_path.is_file()


def open_graph(config: ScaffoldConfig | None = None, *, backend: str | None = None) -> GraphBackend:
    """Open an existing graph database for querying.

    Args:
        config: Optional scaffold config. Used to resolve db_path.
        backend: Reserved for future use. Only "duckpgq" is supported.

    Raises:
        ValueError: if an unknown backend name is given.
    """
    backend_name = backend or _resolve_backend(config)
    db_path = _resolve_db_path(config)

    if backend_name == "duckpgq":
        return DuckPGQBackend(db_path)

    raise ValueError(f"Unknown backend '{backend_name}'. Supported: 'duckpgq'.")


def index(
    path: Path | None = None,
    config: ScaffoldConfig | None = None,
    *,
    incremental: bool = False,
    embeddings: bool = False,
    audit: bool = False,
) -> dict:
    """Build or rebuild the knowledge graph.

    Returns an index summary dict with quality metrics.
    """
    from agentscaffold.graph.pipeline import run_pipeline

    return run_pipeline(
        root=path or Path.cwd(),
        config=config,
        incremental=incremental,
        embeddings=embeddings,
        audit=audit,
    )


def _resolve_db_path(config: ScaffoldConfig | None) -> Path:
    if config is not None and hasattr(config, "graph"):
        return Path(config.graph.db_path)
    return Path(".scaffold/graph.db")


def _resolve_backend(config: ScaffoldConfig | None) -> str:
    if config is not None and hasattr(config, "graph") and hasattr(config.graph, "backend"):
        return config.graph.backend or "duckpgq"
    return "duckpgq"
