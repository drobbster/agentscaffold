"""Knowledge graph subsystem for AgentScaffold.

Public API:
    index(path, config)  -- Build/rebuild the knowledge graph
    open_graph(config)   -- Open an existing graph for querying
    graph_available(config) -- Check if a graph exists
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.graph.store import GraphStore


def graph_available(config: ScaffoldConfig | None = None) -> bool:
    """Return True if a knowledge graph database exists on disk."""
    db_path = _resolve_db_path(config)
    if db_path.is_file():
        return True
    if db_path.is_dir():
        return any(db_path.iterdir())
    return False


def open_graph(config: ScaffoldConfig | None = None) -> GraphStore:
    """Open an existing graph database for querying.

    Raises FileNotFoundError if no graph exists.
    """
    from agentscaffold.graph.store import GraphStore

    db_path = _resolve_db_path(config)
    if not graph_available(config):
        raise FileNotFoundError(
            f"No knowledge graph found at {db_path}. Run 'scaffold index' first."
        )
    return GraphStore(db_path)


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
