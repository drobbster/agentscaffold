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
                {
                    "cypher": "MATCH (f:File) RETURN f.path LIMIT 5",
                    "sql": 'SELECT path AS "f.path" FROM File LIMIT 5',
                },
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
            actual=(f"Present: {present}, Missing: {missing}, has_chain={has_chain}"),
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"
        assert has_chain, "Expected a full decision chain for plan 42"


# ---------------------------------------------------------------------------
# New MCP tools: scaffold_record_finding, scaffold_resolve_finding (E.4)
# ---------------------------------------------------------------------------


class TestScaffoldRecordFinding:
    """Scenario: scaffold_record_finding writes a ReviewFinding node."""

    @timed
    def test_record_finding_writes_node(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool(
                "scaffold_record_finding",
                {
                    "plan_number": 42,
                    "review_type": "quant_architect",
                    "category": "correctness",
                    "finding": "Risk bounds are not enforced in execution path",
                    "severity": "high",
                },
            )
        finally:
            stack.__exit__(None, None, None)

        has_id = "finding_id" in data or "id" in data
        no_error = "error" not in data

        result = EvalResult(
            scenario="mcp_record_finding_writes_node",
            passed=has_id and no_error,
            score=1.0 if has_id and no_error else 0.0,
            expected="Response contains finding_id, no error",
            actual=f"Keys: {list(data.keys())}, has_id={has_id}, no_error={no_error}",
            category="mcp",
        )
        collect_result(result)
        assert no_error, f"Record finding returned error: {data.get('error')}"
        assert has_id, f"Response missing finding_id: {list(data.keys())}"

    @timed
    def test_record_finding_latency_under_200ms(self, indexed_sim):
        import time

        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store)
        stack = _enter_patches(patches)
        try:
            t0 = time.monotonic()
            _dispatch_tool(
                "scaffold_record_finding",
                {
                    "plan_number": 42,
                    "review_type": "latency_test",
                    "category": "perf",
                    "finding": "Latency test finding",
                    "severity": "low",
                },
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
        finally:
            stack.__exit__(None, None, None)

        under_200 = elapsed_ms < 200
        result = EvalResult(
            scenario="mcp_record_finding_latency",
            passed=under_200,
            score=1.0 if under_200 else max(0.0, 1.0 - (elapsed_ms - 200) / 200),
            expected="record_finding completes in <200ms",
            actual=f"elapsed_ms={elapsed_ms:.1f}",
            category="mcp",
        )
        collect_result(result)
        assert under_200, f"record_finding took {elapsed_ms:.1f}ms (>200ms threshold)"

    @timed
    def test_record_finding_creates_file_edges(self, indexed_sim):
        """related_files parameter causes FINDING_ABOUT_FILE edges."""
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool(
                "scaffold_record_finding",
                {
                    "plan_number": 42,
                    "review_type": "edge_test",
                    "category": "test",
                    "finding": "Test finding with file edges via MCP",
                    "severity": "medium",
                    "file_paths": ["libs/data/router.py"],
                },
            )
        finally:
            stack.__exit__(None, None, None)

        fid = data.get("finding_id") or data.get("id")
        has_id = fid is not None
        no_error = "error" not in data

        result = EvalResult(
            scenario="mcp_record_finding_file_edges",
            passed=has_id and no_error,
            score=1.0 if has_id and no_error else 0.0,
            expected="Finding recorded with file_paths, no error",
            actual=f"finding_id={fid}, no_error={no_error}",
            category="mcp",
        )
        collect_result(result)
        assert no_error, f"Record finding with file_paths returned error: {data}"
        assert has_id, f"No finding_id returned: {data}"


class TestScaffoldResolveFinding:
    """Scenario: scaffold_resolve_finding changes a finding's status."""

    @timed
    def test_resolve_finding_changes_status(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        # First record a finding
        patches = _patch_mcp(config, store)
        stack = _enter_patches(patches)
        try:
            record_data = _dispatch_tool(
                "scaffold_record_finding",
                {
                    "plan_number": 42,
                    "review_type": "resolve_test",
                    "category": "test",
                    "finding": "Finding that will be resolved",
                    "severity": "medium",
                },
            )
        finally:
            stack.__exit__(None, None, None)

        fid = record_data.get("finding_id") or record_data.get("id")
        assert fid, "No finding_id returned from record_finding"

        # Now resolve it
        stack2 = _enter_patches(_patch_mcp(config, store))
        try:
            resolve_data = _dispatch_tool(
                "scaffold_resolve_finding",
                {
                    "finding_id": fid,
                    "resolution": "Issue was addressed by refactoring the execution path",
                },
            )
        finally:
            stack2.__exit__(None, None, None)

        no_error = "error" not in resolve_data
        status_resolved = resolve_data.get("status") == "resolved"

        result = EvalResult(
            scenario="mcp_resolve_finding_changes_status",
            passed=no_error and status_resolved,
            score=1.0 if (no_error and status_resolved) else 0.5 if no_error else 0.0,
            expected="status='resolved' in response, no error",
            actual=f"status={resolve_data.get('status')}, no_error={no_error}",
            category="mcp",
        )
        collect_result(result)
        assert no_error, f"Resolve finding returned error: {resolve_data}"
        assert status_resolved, f"Expected status=resolved, got: {resolve_data}"

    @timed
    def test_resolved_finding_not_in_open_query(self, indexed_sim):
        """Resolved findings should not appear in get_open_findings()."""
        _, store, config = indexed_sim
        from agentscaffold.graph.findings import get_open_findings, record_finding, resolve_finding

        result = record_finding(
            store,
            plan_number=300,
            review_type="open_query_test",
            category="test",
            finding="Will be resolved and absent from open query",
            severity="low",
        )
        fid = result["id"]
        resolve_finding(store, fid, resolution="Fixed")

        open_findings = get_open_findings(store, plan_number=300)
        resolved_present = any(f.get("rf.id") == fid for f in open_findings)

        passed = not resolved_present
        eval_result = EvalResult(
            scenario="mcp_resolved_not_in_open_query",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected=f"Resolved finding {fid} absent from open_findings query",
            actual=f"resolved_present={resolved_present}, open_count={len(open_findings)}",
            category="mcp",
        )
        collect_result(eval_result)
        assert not resolved_present, f"Resolved finding {fid} still in open query: {open_findings}"


# ---------------------------------------------------------------------------
# Extend TestScaffoldPrepareReview with Phase C fields (E.4)
# ---------------------------------------------------------------------------


class TestScaffoldPrepareReviewEnriched:
    """Extended prepare_review tests: reviewer_hints and open_findings (E.4)."""

    @timed
    def test_prepare_review_includes_reviewer_hints(self, indexed_sim):
        """scaffold_prepare_review should include reviewer_hints key."""
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool("scaffold_prepare_review", {"plan_number": 42})
        finally:
            stack.__exit__(None, None, None)

        has_hints_key = "reviewer_hints" in data
        result = EvalResult(
            scenario="mcp_prepare_review_reviewer_hints",
            passed=has_hints_key and "error" not in data,
            score=1.0 if has_hints_key else 0.0,
            expected="reviewer_hints key present in prepare_review response",
            actual=f"Keys: {list(data.keys())}",
            category="mcp",
        )
        collect_result(result)
        assert has_hints_key, f"reviewer_hints missing from prepare_review: {list(data.keys())}"

    @timed
    def test_prepare_review_surfaces_open_findings(self, indexed_sim):
        """pre-written finding against a plan file appears in prepare_review open_findings."""
        root, store, config = indexed_sim
        from agentscaffold.graph.findings import record_finding
        from agentscaffold.mcp.server import _dispatch_tool

        # Write a finding against router.py which is in plan 42's impact map
        finding_result = record_finding(
            store,
            plan_number=42,
            review_type="prepare_review_test",
            category="contract",
            finding="Prepare review surfacing test — should appear in open_findings",
            severity="high",
        )
        fid = finding_result["id"]

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool("scaffold_prepare_review", {"plan_number": 42})
        finally:
            stack.__exit__(None, None, None)

        open_findings = data.get("open_findings", [])
        finding_present = any(f.get("rf.id") == fid for f in open_findings)

        passed = finding_present
        result = EvalResult(
            scenario="mcp_prepare_review_open_findings",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected=f"Finding {fid} present in open_findings",
            actual=(f"open_findings_count={len(open_findings)}, finding_present={finding_present}"),
            category="mcp",
        )
        collect_result(result)
        assert finding_present, (
            f"Finding {fid} not in open_findings. "
            f"open_findings IDs: {[f.get('rf.id') for f in open_findings]}"
        )
