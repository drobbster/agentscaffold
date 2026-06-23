"""Tests for MCP server dispatch robustness (Plan 218)."""

from __future__ import annotations

import pytest

# Skip if duckdb is not installed (graph import chain requires it).
pytest.importorskip("duckdb", reason="duckdb not installed")


def test_dispatch_tool_returns_graph_locked_on_lock(monkeypatch) -> None:
    """A GraphLockError while opening the graph yields a clean error dict."""
    from pathlib import Path

    import agentscaffold.config as config_mod
    import agentscaffold.graph as graph_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.graph import GraphLockError
    from agentscaffold.mcp.server import _dispatch_tool

    # Pin the per-call root so os.chdir is a no-op (no cwd leak across tests).
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: Path.cwd())
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: ScaffoldConfig())
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)

    def _raise_lock(config=None, **kwargs):
        raise GraphLockError("another process holds .scaffold/graph.duckdb")

    monkeypatch.setattr(graph_mod, "open_graph", _raise_lock)

    result = _dispatch_tool("scaffold_stats", {})

    assert result.get("graph_locked") is True
    assert "another process" in result.get("error", "")


def test_dispatch_tool_returns_generic_error_on_open_failure(monkeypatch) -> None:
    """A non-lock open failure surfaces as a generic error dict, not a crash."""
    from pathlib import Path

    import agentscaffold.config as config_mod
    import agentscaffold.graph as graph_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.mcp.server import _dispatch_tool

    # Pin the per-call root so os.chdir is a no-op (no cwd leak across tests).
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: Path.cwd())
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: ScaffoldConfig())
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)

    def _raise(config=None, **kwargs):
        raise RuntimeError("corrupt database")

    monkeypatch.setattr(graph_mod, "open_graph", _raise)

    result = _dispatch_tool("scaffold_stats", {})

    assert "graph_locked" not in result
    assert "corrupt database" in result.get("error", "")
