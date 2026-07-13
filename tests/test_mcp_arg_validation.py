"""Plan 246: required-arg validation fails loud."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


def test_impact_missing_file_or_symbol_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import agentscaffold.config as config_mod
    import agentscaffold.graph as graph_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.mcp.server import _dispatch_tool

    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: Path.cwd())
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: ScaffoldConfig())
    # Should fail before open_graph
    opened = {"n": 0}

    def _open(*a, **k):
        opened["n"] += 1
        raise AssertionError("open_graph should not be called")

    monkeypatch.setattr(graph_mod, "open_graph", _open)
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)

    result = _dispatch_tool("scaffold_impact", {})
    assert result.get("missing_argument") == "file_or_symbol"
    assert "error" in result
    assert opened["n"] == 0


def test_impact_empty_string_errors() -> None:
    from agentscaffold.mcp.server import _tool_impact

    result = _tool_impact(MagicMock(), {"file_or_symbol": "  "}, {})
    assert result.get("missing_argument") == "file_or_symbol"
