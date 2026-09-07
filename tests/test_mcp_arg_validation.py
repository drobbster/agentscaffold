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


def test_find_studies_missing_topic_is_structured() -> None:
    from agentscaffold.mcp.server import _tool_find_studies

    result = _tool_find_studies(MagicMock(), {}, {})
    assert result.get("missing_argument") == "topic"
    assert "error" in result


def test_find_studies_missing_topic_fails_before_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agentscaffold.graph as graph_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool

    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: Path.cwd())
    opened = {"n": 0}

    def _open(*a, **k):
        opened["n"] += 1
        raise AssertionError("open_graph should not be called")

    monkeypatch.setattr(graph_mod, "open_graph", _open)
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)

    result = _dispatch_tool("scaffold_find_studies", {})
    assert result.get("missing_argument") == "topic"
    assert opened["n"] == 0


def test_find_adrs_blank_topic_is_structured() -> None:
    from agentscaffold.mcp.server import _tool_find_adrs

    result = _tool_find_adrs(MagicMock(), {"topic": "  "}, {})
    assert result.get("missing_argument") == "topic"


def test_prior_experiments_missing_plan_is_not_empty_experiments() -> None:
    from unittest.mock import patch

    from agentscaffold.mcp.server import _tool_prior_experiments

    store = MagicMock()
    with patch(
        "agentscaffold.review.queries.get_plan_by_number",
        return_value=None,
    ):
        result = _tool_prior_experiments(store, {"plan_number": 999}, {})
    assert "no experiments" in result["why_empty"].lower()
    assert result["total_count"] == 0
    assert "not found" in result["error"].lower()


def test_find_adrs_matches_file_body(tmp_path: Path) -> None:
    from agentscaffold.mcp.server import _adr_matches_topic

    path = tmp_path / "adr-001-cache.md"
    path.write_text("# Something else\n\nThis ADR describes the cache layout.\n")
    adr = {"a.title": "Unrelated title", "a.filePath": str(path)}
    assert _adr_matches_topic(adr, "cache")
    assert not _adr_matches_topic(adr, "missingtoken")
