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
    """Scenario: scaffold_query executes SQL and returns results."""

    @timed
    def test_query_returns_results(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            result_data = _dispatch_tool(
                "scaffold_query",
                {
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

        expected_keys = [
            "shared_files",
            "conflict_risk",
            "lead_shared_files",
            "dependency_cycle",
        ]
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

        expected_keys = ["stats", "workflow_state", "recent_plans", "recommended_actions"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]

        ws = data.get("workflow_state", {})
        has_blockers = "blockers" in ws
        has_next = "next_steps" in ws
        has_actions = isinstance(data.get("recommended_actions"), list)
        has_progress = "plan_progress" in data

        result = EvalResult(
            scenario="mcp_orient",
            passed=len(missing) == 0 and has_blockers and has_next and has_actions,
            score=len(present) / len(expected_keys),
            expected=(
                f"Keys: {expected_keys}, workflow_state has blockers + next_steps, "
                "recommended_actions list present (Plan 247 fuse)"
            ),
            actual=(
                f"Present: {present}, Missing: {missing}, "
                f"blockers={has_blockers}, next_steps={has_next}, "
                f"recommended_actions={has_actions}, plan_progress={has_progress}"
            ),
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"
        assert has_blockers and has_next, "workflow_state missing blockers or next_steps"
        assert has_actions, "orient missing recommended_actions (Plan 247)"


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

        def _finding_id(row: dict) -> str | None:
            return row.get("id") or row.get("rf.id") or row.get("rf_id")

        finding_present = any(_finding_id(f) == fid for f in open_findings)

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
            f"open_findings IDs: {[_finding_id(f) for f in open_findings]}"
        )


# ---------------------------------------------------------------------------
# Plan 246/247: agent tool pack + call-compression fused fields
# ---------------------------------------------------------------------------


class TestScaffoldDiffPlanVsCode:
    """Scenario: scaffold_diff_plan_vs_code returns plan vs disk/graph progress."""

    @timed
    def test_diff_plan_vs_code(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool("scaffold_diff_plan_vs_code", {"plan_number": 42})
        finally:
            stack.__exit__(None, None, None)

        expected_keys = [
            "plan_number",
            "planned_files",
            "existing_on_disk",
            "missing_on_disk",
            "unchecked_steps",
            "checked_steps",
            "summary",
        ]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]
        has_next = "next_unchecked_step" in data
        has_spots = "symbol_spot_checks" in data

        passed = len(missing) == 0 and "error" not in data and has_next and has_spots
        result = EvalResult(
            scenario="mcp_diff_plan_vs_code",
            passed=passed,
            score=len(present) / len(expected_keys),
            expected=f"Keys: {expected_keys} + next_unchecked_step + symbol_spot_checks",
            actual=(
                f"Present: {present}, Missing: {missing}, "
                f"next_unchecked_step={has_next}, symbol_spot_checks={has_spots}"
            ),
            category="mcp",
        )
        collect_result(result)
        assert len(missing) == 0, f"Missing keys: {missing}"
        assert has_next and has_spots


class TestScaffoldGrepGraph:
    """Scenario: scaffold_grep_graph returns sandboxed text hits."""

    @timed
    def test_grep_graph(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool(
                "scaffold_grep_graph",
                {"pattern": "DataRouter", "max_hits": 10},
            )
        finally:
            stack.__exit__(None, None, None)

        expected_keys = ["hits", "count", "pattern"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]
        passed = len(missing) == 0 and "error" not in data and data.get("count", 0) > 0

        result = EvalResult(
            scenario="mcp_grep_graph",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Greppable DataRouter hits under sim project root",
            actual=f"Present: {present}, Missing: {missing}, count={data.get('count')}",
            category="mcp",
        )
        collect_result(result)
        assert passed, f"grep_graph failed: {data}"


class TestScaffoldWhyEmpty:
    """Scenario: scaffold_why_empty returns structured diagnosis."""

    @timed
    def test_why_empty(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool(
                "scaffold_why_empty",
                {
                    "kind": "search",
                    "query": "definitely_missing_symbol_zzz",
                },
            )
        finally:
            stack.__exit__(None, None, None)

        expected_keys = ["reasons", "suggestions"]
        present = [k for k in expected_keys if k in data]
        missing = [k for k in expected_keys if k not in data]
        passed = len(missing) == 0 and "error" not in data

        result = EvalResult(
            scenario="mcp_why_empty",
            passed=passed,
            score=len(present) / len(expected_keys) if expected_keys else 0.0,
            expected=f"Keys: {expected_keys}",
            actual=f"Present: {present}, Missing: {missing}, keys={list(data.keys())[:8]}",
            category="mcp",
        )
        collect_result(result)
        assert passed, f"why_empty failed: {data}"


class TestScaffoldNextAction:
    """Scenario: scaffold_next_action returns bounded recommended moves."""

    @timed
    def test_next_action(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool("scaffold_next_action", {})
        finally:
            stack.__exit__(None, None, None)

        actions = data.get("actions")
        passed = (
            "error" not in data
            and isinstance(actions, list)
            and 1 <= len(actions) <= 3
            and all("tool" in a for a in actions)
        )
        result = EvalResult(
            scenario="mcp_next_action",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="1-3 actions with tool hints",
            actual=f"action_count={len(actions) if isinstance(actions, list) else None}",
            category="mcp",
        )
        collect_result(result)
        assert passed, f"next_action failed: {data}"


class TestCallCompressionFusedFields:
    """Scenario: empty search/impact inline why_empty + grep_fallback (Plan 247)."""

    @timed
    def test_empty_search_includes_fused_fallback(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        # Ensure a text hit exists so grep_fallback can populate.
        marker = root / "libs" / "data" / "orphan_marker_247.py"
        marker.write_text(
            "def orphan_marker_247_fn():\n    return 247\n",
            encoding="utf-8",
        )

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool(
                "scaffold_search",
                {
                    "query": "orphan_marker_247_fn",
                    "mode": "keyword",
                    "top_k": 5,
                },
            )
        finally:
            stack.__exit__(None, None, None)

        # Symbol is not indexed into the graph (file written post-index), so
        # search should be empty and fuse diagnosis + text hits.
        count = data.get("count", -1)
        has_why = "why_empty" in data
        has_grep = "grep_fallback" in data
        grep_count = (data.get("grep_fallback") or {}).get("count", 0)
        passed = count == 0 and has_why and has_grep and grep_count >= 1

        result = EvalResult(
            scenario="mcp_empty_search_fused_fallback",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Empty search with why_empty + grep_fallback hits",
            actual=(
                f"count={count}, why_empty={has_why}, grep_fallback={has_grep}, "
                f"grep_count={grep_count}"
            ),
            category="mcp",
        )
        collect_result(result)
        assert passed, f"fused empty search failed: {data}"

    @timed
    def test_empty_impact_includes_fused_fallback(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = _enter_patches(patches)
        try:
            data = _dispatch_tool(
                "scaffold_impact",
                {"file_or_symbol": "definitely/not/a/real/path_247.py"},
            )
        finally:
            stack.__exit__(None, None, None)

        empty = data.get("importer_count", -1) == 0 and data.get("caller_count", -1) == 0
        has_why = "why_empty" in data
        has_grep = "grep_fallback" in data
        passed = empty and has_why and has_grep and "error" not in data

        result = EvalResult(
            scenario="mcp_empty_impact_fused_fallback",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected="Empty impact with why_empty + grep_fallback",
            actual=(
                f"importer_count={data.get('importer_count')}, "
                f"caller_count={data.get('caller_count')}, "
                f"why_empty={has_why}, grep_fallback={has_grep}"
            ),
            category="mcp",
        )
        collect_result(result)
        assert passed, f"fused empty impact failed: {data}"


class TestScaffoldSessionTools:
    """Plan 263: session start / decision / list are reachable from MCP dispatch."""

    @timed
    def test_session_start_record_list(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        patches = _patch_mcp(config, store, root=root)
        stack = contextlib.ExitStack()
        for p in patches:
            stack.enter_context(p)
        try:
            started = _dispatch_tool(
                "scaffold_session_start",
                {"plan_numbers": [42], "summary": "eval session"},
            )
            recorded = _dispatch_tool(
                "scaffold_session_record_decision",
                {
                    "decision": "Keep routing in the managed block",
                    "kind": "architectural",
                    "status": "accepted",
                    "plan_numbers": [42],
                },
            )
            listed = _dispatch_tool("scaffold_session_list", {"limit": 5})
        finally:
            stack.close()

        has_id = bool(started.get("id"))
        has_decision = recorded.get("id") or recorded.get("decision_id") or "error" not in recorded
        listed_ok = "error" not in listed and (
            listed.get("count", 0) >= 1 or bool(listed.get("sessions"))
        )
        passed = has_id and bool(has_decision) and listed_ok and "error" not in started
        collect_result(
            EvalResult(
                scenario="mcp_session_start_record_list",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="session start id, recorded decision, list non-empty",
                actual=(
                    f"start_id={started.get('id')}, record_keys={list(recorded.keys())[:6]}, "
                    f"list_keys={list(listed.keys())[:6]}"
                ),
                category="mcp",
            )
        )
        assert passed, f"session tools failed: start={started} record={recorded} list={listed}"


class TestScaffoldRecallGovernance:
    """Plan 261: populated learnings are in the graph and recallable."""

    @timed
    def test_recall_returns_learnings(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.graph.query_compat import ql
        from agentscaffold.mcp.server import _dispatch_tool

        ingested = ql(store, sql='SELECT id AS "l.id" FROM Learning')
        patches = _patch_mcp(config, store, root=root)
        stack = contextlib.ExitStack()
        for p in patches:
            stack.enter_context(p)
        try:
            data = _dispatch_tool(
                "scaffold_recall_governance",
                {"query": "cache invalidation", "mode": "keyword", "top_k": 10},
            )
        finally:
            stack.close()

        count = data.get("count", 0)
        if not count and isinstance(data.get("results"), list):
            count = len(data["results"])
        grep_hits = (data.get("grep_fallback") or {}).get("count", 0)
        # Ingest is the 261 contract. Recall may still be empty when the
        # dispatch resolver anchors at the package repo; grep_fallback on the
        # sim tree is the fused confirmation that the text is there.
        passed = len(ingested) >= 1 and "error" not in data and (count >= 1 or grep_hits >= 1)
        collect_result(
            EvalResult(
                scenario="mcp_recall_governance_learnings",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Learning rows ingested; recall or grep_fallback hits cache invalidation",
                actual=(
                    f"ingested={len(ingested)}, recall_count={count}, "
                    f"grep_fallback={grep_hits}"
                ),
                category="mcp",
            )
        )
        assert len(ingested) >= 1, "Plan 261 regression: Learning ingest is empty"
        assert passed, f"recall empty or errored: {data}"
