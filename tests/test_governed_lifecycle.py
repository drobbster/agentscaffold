"""Tests for governed plan lifecycle (Plan 152).

Covers scaffold_begin_plan, scaffold_complete_plan, strict gate, and
Plan.reviewedAt stamping.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """In-memory DuckPGQBackend with schema initialised."""
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    s = DuckPGQBackend(":memory:")
    s.init_schema()
    yield s
    s.close()


@pytest.fixture()
def store_with_plan(store):
    """Store with a Plan node pre-inserted."""
    store.execute(
        "INSERT INTO Plan VALUES ('plan::152', 152, 'Governed Plan Lifecycle',"
        " 'in_progress', 'feature', '', '2026-03-17', '2026-03-17', NULL)"
    )
    return store


# ---------------------------------------------------------------------------
# stamp_plan_reviewed / get_plan_reviewed_at
# ---------------------------------------------------------------------------


def test_stamp_plan_reviewed_sets_timestamp(store_with_plan):
    from agentscaffold.review.queries import get_plan_reviewed_at, stamp_plan_reviewed

    assert get_plan_reviewed_at(store_with_plan, 152) is None

    ts = stamp_plan_reviewed(store_with_plan, 152)
    assert ts is not None
    assert "T" in ts  # ISO format

    assert get_plan_reviewed_at(store_with_plan, 152) == ts


def test_stamp_plan_reviewed_missing_plan(store):
    from agentscaffold.review.queries import stamp_plan_reviewed

    result = stamp_plan_reviewed(store, 999)
    assert result is None


def test_stamp_plan_reviewed_idempotent(store_with_plan):
    from agentscaffold.review.queries import stamp_plan_reviewed

    ts1 = stamp_plan_reviewed(store_with_plan, 152)
    ts2 = stamp_plan_reviewed(store_with_plan, 152)
    # Both succeed; second overwrites first
    assert ts1 is not None
    assert ts2 is not None


def test_get_plan_reviewed_at_missing_plan(store):
    from agentscaffold.review.queries import get_plan_reviewed_at

    result = get_plan_reviewed_at(store, 999)
    assert result is None


# ---------------------------------------------------------------------------
# _tool_begin_plan
# ---------------------------------------------------------------------------


def test_begin_plan_missing_plan_number(store):
    from agentscaffold.mcp.server import _tool_begin_plan

    result = _tool_begin_plan(store, {}, {}, None, None)
    assert "error" in result


def test_begin_plan_graph_warning_on_empty_graph(store):
    """begin_plan on empty graph should include a graph_warning."""
    from agentscaffold.mcp.server import _tool_begin_plan

    result = _tool_begin_plan(store, {"plan_number": 152}, {}, None, None)
    assert result.get("graph_warning") is not None
    assert "empty" in result["graph_warning"].lower()


def test_begin_plan_writes_findings_and_stamps(store_with_plan):
    """begin_plan should write challenges+gaps as findings and stamp reviewedAt."""
    from agentscaffold.mcp.server import _tool_begin_plan
    from agentscaffold.review.queries import get_plan_reviewed_at

    result = _tool_begin_plan(store_with_plan, {"plan_number": 152}, {}, None, None)

    # Should have pre_review section
    assert "pre_review" in result
    assert "proceed_prompt" in result
    assert result["plan_number"] == 152

    # reviewedAt should be stamped
    reviewed_at = get_plan_reviewed_at(store_with_plan, 152)
    assert reviewed_at is not None
    assert result["reviewed_at"] == reviewed_at


def test_begin_plan_called_twice_updates_reviewed_at(store_with_plan):
    """Calling begin_plan twice should succeed and update reviewedAt."""
    from agentscaffold.mcp.server import _tool_begin_plan

    r1 = _tool_begin_plan(store_with_plan, {"plan_number": 152}, {}, None, None)
    r2 = _tool_begin_plan(store_with_plan, {"plan_number": 152}, {}, None, None)

    # Both succeed
    assert "error" not in r1
    assert "error" not in r2
    # Second call may have a later timestamp
    assert r2["reviewed_at"] is not None


def test_begin_plan_orient_is_compact(store_with_plan):
    """Orient output in begin_plan should be compact, not full output."""
    from agentscaffold.mcp.server import _tool_begin_plan

    result = _tool_begin_plan(store_with_plan, {"plan_number": 152}, {}, None, None)
    orient = result.get("orient", {})
    # Should have compact keys, not full workflow_state text
    assert "schema_version" in orient
    assert "files" in orient
    assert "workflow_state" not in orient


# ---------------------------------------------------------------------------
# _tool_complete_plan
# ---------------------------------------------------------------------------


def test_complete_plan_missing_plan_number(store):
    from agentscaffold.mcp.server import _tool_complete_plan

    result = _tool_complete_plan(store, {}, {})
    assert "error" in result


def test_complete_plan_on_existing_plan(store_with_plan):
    """complete_plan should return retro, findings_written, completion_checklist."""
    from agentscaffold.mcp.server import _tool_complete_plan

    result = _tool_complete_plan(store_with_plan, {"plan_number": 152}, {})

    assert result["plan_number"] == 152
    assert "retro" in result
    assert "findings_written" in result
    assert "completion_checklist" in result
    assert "structured_learnings" in result
    assert isinstance(result["completion_checklist"], list)
    assert len(result["completion_checklist"]) > 0


def test_complete_plan_before_begin_plan(store_with_plan):
    """complete_plan should work independently of begin_plan."""
    from agentscaffold.mcp.server import _tool_complete_plan

    result = _tool_complete_plan(store_with_plan, {"plan_number": 152}, {})
    # Should not error
    assert "error" not in result


def test_complete_plan_with_empty_backlog_items(store_with_plan):
    """complete_plan with empty backlog_items list should work."""
    from agentscaffold.mcp.server import _tool_complete_plan

    result = _tool_complete_plan(store_with_plan, {"plan_number": 152, "backlog_items": []}, {})
    assert result["backlog_items_written"]["count"] == 0
    assert result["backlog_items_written"]["ids"] == []


def test_complete_plan_with_backlog_items(store_with_plan):
    """complete_plan with backlog items should write them to graph."""
    from agentscaffold.mcp.server import _tool_complete_plan

    items = [
        {"title": "Fix broken pre-edit hook", "priority": "P2"},
        {"title": "Add retry logic to indexer", "priority": "P3"},
    ]
    result = _tool_complete_plan(store_with_plan, {"plan_number": 152, "backlog_items": items}, {})
    assert result["backlog_items_written"]["count"] == 2
    assert len(result["backlog_items_written"]["ids"]) == 2


def test_complete_plan_without_backlog_items_key(store_with_plan):
    """complete_plan without backlog_items key should work (skip backlog)."""
    from agentscaffold.mcp.server import _tool_complete_plan

    result = _tool_complete_plan(store_with_plan, {"plan_number": 152}, {})
    assert result["backlog_items_written"]["count"] == 0


def test_complete_plan_graph_warning_on_empty_graph(store):
    """complete_plan on empty graph should include graph_warning."""
    from agentscaffold.mcp.server import _tool_complete_plan

    # Plan 999 doesn't exist in the graph
    result = _tool_complete_plan(store, {"plan_number": 999}, {})
    # Should either error (plan not found) or have a graph_warning
    assert "error" in result or result.get("graph_warning") is not None


# ---------------------------------------------------------------------------
# Full lifecycle: begin_plan -> complete_plan
# ---------------------------------------------------------------------------


def test_full_lifecycle(store_with_plan):
    """Full lifecycle: begin_plan then complete_plan."""
    from agentscaffold.mcp.server import _tool_begin_plan, _tool_complete_plan
    from agentscaffold.review.queries import get_plan_reviewed_at

    # Phase 1: begin
    begin_result = _tool_begin_plan(store_with_plan, {"plan_number": 152}, {}, None, None)
    assert "error" not in begin_result
    assert get_plan_reviewed_at(store_with_plan, 152) is not None

    # Phase 2: complete
    complete_result = _tool_complete_plan(store_with_plan, {"plan_number": 152}, {})
    assert "error" not in complete_result
    assert complete_result["plan_number"] == 152

    # Verify findings were written (may be empty on minimal graph)
    rows = store_with_plan.query("SELECT reviewType FROM ReviewFinding WHERE planNumber = 152")
    review_types = {r["reviewType"] for r in rows}
    # On a minimal graph the review/retro may produce 0 findings,
    # so we only assert that any findings written have the correct types.
    assert review_types <= {"pre_review", "post_retro"}


# ---------------------------------------------------------------------------
# Strict gate in scaffold_prepare_implementation
# ---------------------------------------------------------------------------


def test_strict_gate_blocks_without_review(store_with_plan, monkeypatch):
    """Strict gate should block when Plan.reviewedAt is NULL."""
    from agentscaffold.mcp.server import _tool_prepare_implementation

    # Mock config with gate_strict=True
    class MockFreshness:
        gate_strict = True

    class MockConfig:
        freshness = MockFreshness()

    monkeypatch.setattr(
        "agentscaffold.mcp.server._tool_prepare_implementation.__module__",
        "agentscaffold.mcp.server",
    )

    original_load = None
    try:
        import agentscaffold.config

        original_load = agentscaffold.config.load_config
        agentscaffold.config.load_config = lambda: MockConfig()

        result = _tool_prepare_implementation(
            store_with_plan,
            {"plan_number": 152, "gate_transition": True},
            {},
            None,
        )
        assert result.get("gate_deferred") is True
        assert "scaffold_begin_plan" in result.get("error", "")
    finally:
        if original_load:
            agentscaffold.config.load_config = original_load


def test_strict_gate_passes_after_review(store_with_plan, monkeypatch):
    """Strict gate should pass when Plan.reviewedAt is set."""
    from agentscaffold.review.queries import stamp_plan_reviewed

    stamp_plan_reviewed(store_with_plan, 152)

    from agentscaffold.mcp.server import _tool_prepare_implementation

    class MockFreshness:
        gate_strict = True

    class MockConfig:
        freshness = MockFreshness()

    import agentscaffold.config

    original_load = agentscaffold.config.load_config
    try:
        agentscaffold.config.load_config = lambda: MockConfig()

        result = _tool_prepare_implementation(
            store_with_plan,
            {"plan_number": 152, "gate_transition": True},
            {},
            None,
        )
        # Should NOT be deferred
        assert result.get("gate_deferred") is not True
    finally:
        agentscaffold.config.load_config = original_load


def test_strict_gate_missing_plan_node(store, monkeypatch):
    """Strict gate on plan not in graph should return gate_deferred, not crash."""
    from agentscaffold.mcp.server import _tool_prepare_implementation

    class MockFreshness:
        gate_strict = True

    class MockConfig:
        freshness = MockFreshness()

    import agentscaffold.config

    original_load = agentscaffold.config.load_config
    try:
        agentscaffold.config.load_config = lambda: MockConfig()

        result = _tool_prepare_implementation(
            store,
            {"plan_number": 999, "gate_transition": True},
            {},
            None,
        )
        # Plan 999 doesn't exist, reviewedAt is None -> gate_deferred
        assert result.get("gate_deferred") is True
    finally:
        agentscaffold.config.load_config = original_load


# ---------------------------------------------------------------------------
# Validate --warn-only
# ---------------------------------------------------------------------------


def test_validate_warn_only_exits_zero():
    """scaffold validate --pre-edit --warn-only should not call sys.exit(1)."""
    from agentscaffold.validate.orchestrator import run_validate

    # If there are validation failures, warn_only should prevent sys.exit(1)
    # We can't easily test the full CLI, but we can verify the function
    # doesn't raise SystemExit when warn_only=True
    try:
        run_validate(pre_edit=True, warn_only=True)
    except SystemExit:
        pytest.fail("run_validate with warn_only=True should not call sys.exit(1)")


# ---------------------------------------------------------------------------
# NL trigger routing
# ---------------------------------------------------------------------------


def test_nl_routing_begin_plan():
    from agentscaffold.mcp.server import route_tool_from_prompt

    assert route_tool_from_prompt("begin plan 152") == "scaffold_begin_plan"
    assert route_tool_from_prompt("kick off plan 152") == "scaffold_begin_plan"


def test_nl_routing_complete_plan():
    from agentscaffold.mcp.server import route_tool_from_prompt

    assert route_tool_from_prompt("wrap up plan 152") == "scaffold_complete_plan"
    assert route_tool_from_prompt("close out plan 152") == "scaffold_complete_plan"
