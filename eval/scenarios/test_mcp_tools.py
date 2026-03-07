"""MCP tool scenarios: all tool dispatches, error handling, JSON well-formedness."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
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


def _patch_mcp(config, store, root=None):
    """Return context managers that patch the MCP dispatch dependencies.

    _dispatch_tool imports load_config, graph_available, open_graph locally
    from their source modules, so we patch at the source.
    Uses _NoCloseStore to prevent the shared session store from being closed.
    If *root* is given, also patches Path.cwd so filesystem-reading tools
    (e.g. scaffold_orient) resolve files relative to the sim project.
    """
    wrapper = _NoCloseStore(store)
    patches = [
        patch("agentscaffold.config.load_config", return_value=config),
        patch("agentscaffold.graph.graph_available", return_value=True),
        patch("agentscaffold.graph.open_graph", return_value=wrapper),
    ]
    if root is not None:
        patches.append(patch.object(Path, "cwd", return_value=root))
    return tuple(patches)


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


# ---------------------------------------------------------------------------
# Composite MCP tool tests
# ---------------------------------------------------------------------------


def _enter_patches(patches):
    """Enter a tuple of context-manager patches using ExitStack.

    Returns (stack, result_of_last_enter).  Caller should call
    ``stack.__exit__(None, None, None)`` when done.
    """
    stack = contextlib.ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


class TestScaffoldPrepareReview:
    """Scenario: scaffold_prepare_review returns full review context."""

    @timed
    def test_prepare_review(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool("scaffold_prepare_review", {"plan_number": 42})
        finally:
            stack.__exit__(None, None, None)

        expected_keys = ["brief", "challenges", "gaps", "governing_adrs"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_prepare_review",
            passed=len(missing) == 0 and "error" not in data,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys}",
            actual=f"Present: {present}, Missing: {missing}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"


class TestScaffoldPrepareImpl:
    """Scenario: scaffold_prepare_implementation returns implementation context."""

    @timed
    def test_prepare_implementation(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool("scaffold_prepare_implementation", {"plan_number": 42})
        finally:
            stack.__exit__(None, None, None)

        expected_keys = ["brief", "impacted_files", "dependencies"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_prepare_implementation",
            passed=len(missing) == 0 and "error" not in data,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys}",
            actual=f"Present: {present}, Missing: {missing}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"


class TestScaffoldComparePlans:
    """Scenario: scaffold_compare_plans detects overlap between two plans."""

    @timed
    def test_compare_plans(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_compare_plans", {"plan_a": 42, "plan_b": 55})

        expected_keys = ["shared_files", "conflict_risk"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_compare_plans",
            passed=len(missing) == 0 and "error" not in data,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys}",
            actual=f"Present: {present}, Missing: {missing}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"


class TestScaffoldStaleness:
    """Scenario: scaffold_staleness_check evaluates plan staleness."""

    @timed
    def test_staleness_check(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_staleness_check", {"plan_number": 42})

        expected_keys = ["is_stale", "stale_signals"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_staleness_check",
            passed=len(missing) == 0 and "error" not in data,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys}",
            actual=f"Present: {present}, Missing: {missing}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"


class TestScaffoldPrepareRewrite:
    """Scenario: scaffold_prepare_rewrite is a superset of staleness."""

    @timed
    def test_prepare_rewrite(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_prepare_rewrite", {"plan_number": 42})

        staleness_keys = ["is_stale", "stale_signals"]
        rewrite_keys = ["dependencies", "recent_completed_plans"]
        all_keys = staleness_keys + rewrite_keys
        present = [k for k in all_keys if k in data]
        missing = [k for k in all_keys if k not in data]

        result = EvalResult(
            scenario="mcp_prepare_rewrite",
            passed=len(missing) == 0 and "error" not in data,
            score=len(present) / len(all_keys),
            expected=f"Keys: {all_keys}",
            actual=f"Present: {present}, Missing: {missing}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"


class TestScaffoldPrepareRetro:
    """Scenario: scaffold_prepare_retro returns retro context."""

    @timed
    def test_prepare_retro(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_prepare_retro", {"plan_number": 42})

        expected_keys = ["verification", "retro_insights"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_prepare_retro",
            passed=len(missing) == 0 and "error" not in data,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys}",
            actual=f"Present: {present}, Missing: {missing}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"


class TestScaffoldOrient:
    """Scenario: scaffold_orient returns stats + workflow state."""

    @timed
    def test_orient(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool("scaffold_orient", {})
        finally:
            stack.__exit__(None, None, None)

        expected_keys = ["stats", "workflow_state", "recent_plans"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        ws = data.get("workflow_state", {})
        has_blockers = "blockers" in ws
        has_next = "next_steps" in ws

        result = EvalResult(
            scenario="mcp_orient",
            passed=len(missing) == 0 and has_blockers and has_next,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys}, workflow_state has blockers + next_steps",
            actual=(
                f"Present: {present}, Missing: {missing}, "
                f"blockers={has_blockers}, next_steps={has_next}"
            ),
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"
        assert has_blockers and has_next, "workflow_state missing blockers or next_steps"


class TestScaffoldFindStudies:
    """Scenario: scaffold_find_studies searches studies by topic."""

    @timed
    def test_find_studies(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_find_studies", {"topic": "caching"})

        expected_keys = ["studies", "count"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_find_studies",
            passed=len(missing) == 0 and data.get("count", 0) > 0,
            score=1.0 if data.get("count", 0) > 0 else 0.5,
            expected="Studies found for topic 'caching'",
            actual=f"Present: {present}, Missing: {missing}, count={data.get('count')}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"
        assert data.get("count", 0) > 0, "Expected at least one study for 'caching'"


class TestScaffoldPriorExperiments:
    """Scenario: scaffold_prior_experiments for a plan."""

    @timed
    def test_prior_experiments(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_prior_experiments", {"plan_number": 42})

        expected_keys = ["directly_referenced", "total_count"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_prior_experiments",
            passed=len(missing) == 0 and "error" not in data,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys}",
            actual=f"Present: {present}, total_count={data.get('total_count')}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"


class TestScaffoldFindADRs:
    """Scenario: scaffold_find_adrs searches ADRs by topic."""

    @timed
    def test_find_adrs(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_find_adrs", {"topic": "provider"})

        expected_keys = ["adrs", "count"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        result = EvalResult(
            scenario="mcp_find_adrs",
            passed=len(missing) == 0 and data.get("count", 0) > 0,
            score=1.0 if data.get("count", 0) > 0 else 0.5,
            expected="ADRs found for topic 'provider'",
            actual=f"Present: {present}, Missing: {missing}, count={data.get('count')}",
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"
        assert data.get("count", 0) > 0, "Expected at least one ADR for 'provider'"


class TestScaffoldDecisionContext:
    """Scenario: scaffold_decision_context returns full decision chain."""

    @timed
    def test_decision_context(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            data = _dispatch_tool("scaffold_decision_context", {"plan_number": 42})

        expected_keys = [
            "governing_adrs",
            "validation_spikes",
            "has_full_decision_chain",
        ]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        has_chain = data.get("has_full_decision_chain", False)

        result = EvalResult(
            scenario="mcp_decision_context",
            passed=len(missing) == 0 and has_chain,
            score=1.0 if has_chain else 0.5,
            expected="Full decision chain with ADRs/spikes/studies for plan 42",
            actual=(f"Present: {present}, Missing: {missing}, " f"has_chain={has_chain}"),
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"
        assert has_chain, "Expected a full decision chain for plan 42"
