"""MCP tool scenarios: all tool dispatches, error handling, JSON well-formedness."""

from __future__ import annotations

import json
from unittest.mock import patch

from eval.runner import EvalResult, collect_result, timed


class _NoCloseStore:
    """Wrapper that prevents _dispatch_tool's finally block from closing the shared store."""

    def __init__(self, store):
        self._store = store

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._store, name)


def _patch_mcp(config, store):
    """Return context managers that patch the MCP dispatch dependencies.

    _dispatch_tool imports load_config, graph_available, open_graph locally
    from their source modules, so we patch at the source.
    Uses _NoCloseStore to prevent the shared session store from being closed.
    """
    wrapper = _NoCloseStore(store)
    return (
        patch("agentscaffold.config.load_config", return_value=config),
        patch("agentscaffold.graph.graph_available", return_value=True),
        patch("agentscaffold.graph.open_graph", return_value=wrapper),
    )


class TestScaffoldStats:
    """Scenario: scaffold_stats returns valid codebase overview."""

    @timed
    def test_stats_returns_data(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool("scaffold_stats", {})

        is_valid = "error" not in result_data
        is_json = True
        try:
            json.dumps(result_data, default=str)
        except (TypeError, ValueError):
            is_json = False

        result = EvalResult(
            scenario="mcp_stats",
            passed=is_valid and is_json,
            score=1.0 if is_valid and is_json else 0.0,
            expected="Valid stats dict without error",
            actual=f"Keys: {list(result_data.keys())[:5]}, JSON-valid: {is_json}",
            category="mcp",
        )
        collect_result(result)
        assert is_valid
        assert is_json


class TestScaffoldQuery:
    """Scenario: scaffold_query executes Cypher and returns results."""

    @timed
    def test_query_returns_results(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool(
                "scaffold_query",
                {"cypher": "MATCH (f:File) RETURN f.path LIMIT 5"},
            )

        has_results = "results" in result_data
        count = result_data.get("count", 0)

        result = EvalResult(
            scenario="mcp_query",
            passed=has_results and count > 0,
            score=1.0 if has_results and count > 0 else 0.0,
            expected="Results array with count > 0",
            actual=f"has_results={has_results}, count={count}",
            category="mcp",
        )
        collect_result(result)
        assert has_results and count > 0


class TestScaffoldContext:
    """Scenario: scaffold_context returns symbol info."""

    @timed
    def test_context_for_known_symbol(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool("scaffold_context", {"symbol": "normalize_ohlcv"})

        has_symbol = "symbol" in result_data and "error" not in result_data

        result = EvalResult(
            scenario="mcp_context_known",
            passed=has_symbol,
            score=1.0 if has_symbol else 0.0,
            expected="Symbol details for normalize_ohlcv",
            actual=f"Keys: {list(result_data.keys())}",
            category="mcp",
        )
        collect_result(result)
        assert has_symbol

    @timed
    def test_context_for_unknown_symbol(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool("scaffold_context", {"symbol": "nonexistent_xyz"})

        has_error = "error" in result_data

        result = EvalResult(
            scenario="mcp_context_unknown",
            passed=has_error,
            score=1.0 if has_error else 0.0,
            expected="Error response for unknown symbol",
            actual=f"Keys: {list(result_data.keys())}",
            category="mcp",
        )
        collect_result(result)
        assert has_error


class TestScaffoldSearch:
    """Scenario: scaffold_search hybrid search works."""

    @timed
    def test_search_cypher_mode(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool(
                "scaffold_search",
                {"query": "DataRouter", "mode": "cypher", "top_k": 5},
            )

        has_results = result_data.get("count", 0) > 0
        has_markdown = bool(result_data.get("markdown"))

        result = EvalResult(
            scenario="mcp_search_cypher",
            passed=has_results,
            score=1.0 if has_results and has_markdown else 0.5,
            expected="Search results for 'DataRouter'",
            actual=f"count={result_data.get('count')}, has_markdown={has_markdown}",
            category="mcp",
        )
        collect_result(result)
        assert has_results


class TestScaffoldReviewContext:
    """Scenario: scaffold_review_context for Dialectic Engine."""

    @timed
    def test_review_context_all(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool(
                "scaffold_review_context",
                {"plan_number": 42, "review_type": "all"},
            )

        expected_keys = ["brief", "challenges", "gaps", "verification", "retro_insights"]
        present = [k for k in expected_keys if k in result_data]
        missing = [k for k in expected_keys if k not in result_data]

        result = EvalResult(
            scenario="mcp_review_all",
            passed=len(missing) == 0,
            score=len(present) / len(expected_keys),
            expected=f"All keys: {expected_keys}",
            actual=f"Present: {present}, Missing: {missing}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing review keys: {missing}"

    @timed
    def test_review_context_json_wellformed(self, indexed_sim):
        """All MCP responses should be JSON-serializable."""
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool(
                "scaffold_review_context",
                {"plan_number": 42, "review_type": "all"},
            )

        try:
            serialized = json.dumps(result_data, default=str)
            is_valid = True
            observations = [f"Serialized size: {len(serialized)} bytes"]
        except (TypeError, ValueError) as exc:
            is_valid = False
            observations = [f"Serialization error: {exc}"]

        result = EvalResult(
            scenario="mcp_review_json_wellformed",
            passed=is_valid,
            score=1.0 if is_valid else 0.0,
            expected="JSON-serializable response",
            actual=f"Valid: {is_valid}",
            observations=observations,
            category="mcp",
        )
        collect_result(result)
        assert is_valid
