"""Tests for open_graph() migration UX and default backend — Step A.10."""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.config import GraphConfig, ScaffoldConfig  # noqa: E402
from agentscaffold.graph import _resolve_backend, open_graph  # noqa: E402

# ---------------------------------------------------------------------------
# Default backend
# ---------------------------------------------------------------------------


def test_default_backend_is_duckpgq() -> None:
    assert _resolve_backend(None) == "duckpgq"


def test_graphconfig_default_backend_is_duckpgq() -> None:
    cfg = GraphConfig()
    assert cfg.backend == "duckpgq"


def test_resolve_backend_from_config() -> None:
    cfg = ScaffoldConfig(graph=GraphConfig(backend="kuzu"))
    assert _resolve_backend(cfg) == "kuzu"


def test_resolve_backend_duckpgq_explicit() -> None:
    cfg = ScaffoldConfig(graph=GraphConfig(backend="duckpgq"))
    assert _resolve_backend(cfg) == "duckpgq"


# ---------------------------------------------------------------------------
# Migration UX: RuntimeError when duckpgq finds a KuzuDB directory
# ---------------------------------------------------------------------------


def test_open_graph_duckpgq_raises_on_kuzu_directory(tmp_path: Path) -> None:
    """If a KuzuDB directory exists where duckpgq expects a file, raise RuntimeError."""
    # Simulate a KuzuDB directory (kuzu stores its DB as a directory)
    db_path = tmp_path / "graph.db"
    db_path.mkdir()
    (db_path / "catalog.db").touch()  # mimick KuzuDB directory contents

    config = ScaffoldConfig(graph=GraphConfig(db_path=str(db_path), backend="duckpgq"))
    with pytest.raises(RuntimeError, match="KuzuDB graph detected"):
        open_graph(config, backend="duckpgq")


def test_open_graph_duckpgq_raises_message_has_instructions(tmp_path: Path) -> None:
    """Error message includes actionable instructions."""
    db_path = tmp_path / "graph.db"
    db_path.mkdir()

    config = ScaffoldConfig(graph=GraphConfig(db_path=str(db_path), backend="duckpgq"))
    with pytest.raises(RuntimeError) as exc_info:
        open_graph(config, backend="duckpgq")
    msg = str(exc_info.value)
    assert "scaffold index" in msg
    assert "graph.backend: kuzu" in msg


def test_open_graph_duckpgq_ok_when_no_directory(tmp_path: Path) -> None:
    """open_graph with duckpgq on a non-existent path returns DuckPGQBackend."""
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    db_path = tmp_path / "new_graph.db"
    config = ScaffoldConfig(graph=GraphConfig(db_path=str(db_path), backend="duckpgq"))
    store = open_graph(config, backend="duckpgq")
    try:
        assert isinstance(store, DuckPGQBackend)
    finally:
        store.close()
