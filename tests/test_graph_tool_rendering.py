"""Tests for Plan 238: graph-tool rendering and signal hygiene.

Covers the boundary helpers and the four fixes across the plan/governance
composites: tolerant completed-plan detection, tolerant ADR active filtering,
alias-key cleaning at the tool boundary, and normalized-status output.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Boundary helpers
# ---------------------------------------------------------------------------


def test_is_plan_complete_tolerates_dates_and_notes():
    from agentscaffold.mcp.server import _is_plan_complete

    assert _is_plan_complete("COMPLETE")
    assert _is_plan_complete("Complete")
    assert _is_plan_complete("COMPLETE (2026-07-09)")
    assert _is_plan_complete("Complete; 144-F control-plane done")
    assert not _is_plan_complete("In Progress")
    assert not _is_plan_complete("")
    assert not _is_plan_complete(None)


def test_adr_is_active():
    from agentscaffold.mcp.server import _adr_is_active

    assert _adr_is_active("Accepted")
    assert _adr_is_active("Proposed")
    assert not _adr_is_active("Superseded")
    assert not _adr_is_active("Superseded by ADR-030")
    assert not _adr_is_active("Deprecated")


def test_clean_out_rows_strips_alias_prefixes():
    from agentscaffold.mcp.server import _clean_out_rows

    rows = [{"p.number": 1, "p.title": "X"}, {"a.status": "Accepted"}]
    cleaned = _clean_out_rows(rows)
    assert cleaned == [{"number": 1, "title": "X"}, {"status": "Accepted"}]
    assert _clean_out_rows(None) == []


def test_with_normalized_status_adds_field():
    from agentscaffold.mcp.server import _with_normalized_status

    rows = [{"p.number": 1, "p.status": "COMPLETE (2026-07-09)"}]
    out = _with_normalized_status(rows)
    assert out[0]["status"] == "COMPLETE (2026-07-09)"
    assert out[0]["status_normalized"] == "Complete"
    assert "p.status" not in out[0]


# ---------------------------------------------------------------------------
# Finding A: completed detection is date/note tolerant
# ---------------------------------------------------------------------------


def test_staleness_counts_dated_complete_overlap():
    from agentscaffold.mcp.server import _tool_staleness_check

    store = MagicMock()

    def _impacted(_s, num, **_k):
        # Both the target plan (5) and the completed plan (4) touch the same file.
        return [{"f.path": "libs/data/router.py"}]

    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.title": "T", "p.status": "In Progress", "p.lastUpdated": "2026-07-01"},
        ),
        patch("agentscaffold.review.queries.get_plan_impacted_files", side_effect=_impacted),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[
                {"p.number": 4, "p.title": "Prior", "p.status": "COMPLETE (2026-07-09)"},
            ],
        ),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
    ):
        result = _tool_staleness_check(store, {"plan_number": 5}, {})

    assert result["is_stale"] is True
    assert len(result["overlapping_completed_plans"]) == 1
    assert result["overlapping_completed_plans"][0]["plan"] == 4
    assert result["plan_status_normalized"] == "In Progress"


def test_prepare_rewrite_lists_dated_complete():
    from agentscaffold.mcp.server import _tool_prepare_rewrite

    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.title": "T", "p.status": "Draft", "p.lastUpdated": ""},
        ),
        patch("agentscaffold.review.queries.get_plan_impacted_files", return_value=[]),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[{"p.number": 7, "p.title": "Done", "p.status": "COMPLETE (2026-06-01)"}],
        ),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_plan_dependencies", return_value=[]),
    ):
        result = _tool_prepare_rewrite(store, {"plan_number": 5}, {})

    nums = [p["number"] for p in result["recent_completed_plans"]]
    assert 7 in nums


# ---------------------------------------------------------------------------
# Finding C/D: clean keys + normalized status in composite outputs
# ---------------------------------------------------------------------------


def _has_dotted_key(obj) -> bool:
    if isinstance(obj, dict):
        return any("." in k for k in obj) or any(_has_dotted_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_dotted_key(v) for v in obj)
    return False


def test_decision_context_clean_and_normalized():
    from agentscaffold.mcp.server import _tool_decision_context

    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.title": "T", "p.status": "COMPLETE (2026-07-09)"},
        ),
        patch(
            "agentscaffold.review.queries.get_adrs_for_plan",
            return_value=[{"a.number": 23, "a.title": "Storage", "a.status": "Accepted"}],
        ),
        patch("agentscaffold.review.queries.get_spikes_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_plan_dependencies", return_value=[]),
    ):
        result = _tool_decision_context(store, {"plan_number": 5}, {})

    assert result["plan_status_normalized"] == "Complete"
    assert not _has_dotted_key(result["governing_adrs"])
    assert result["governing_adrs"][0]["number"] == 23


def test_compare_plans_normalized_status_and_no_empty_paths():
    from agentscaffold.mcp.server import _tool_compare_plans

    store = MagicMock()

    def _by_num(_s, n, **_k):
        return {"p.title": f"Plan {n}", "p.status": "COMPLETE (2026-07-09)"}

    with (
        patch("agentscaffold.review.queries.get_plan_by_number", side_effect=_by_num),
        patch(
            "agentscaffold.review.queries.get_plan_impacted_files",
            return_value=[{"f.path": "a.py"}, {"f.path": ""}],
        ),
    ):
        result = _tool_compare_plans(store, {"plan_a": 1, "plan_b": 2}, {})

    assert result["plan_a"]["status_normalized"] == "Complete"
    assert result["plan_b"]["status_normalized"] == "Complete"
    # Empty-string paths are dropped from the shared/only sets.
    assert "" not in result["shared_files"]


def test_find_adrs_output_is_clean():
    from agentscaffold.mcp.server import _tool_find_adrs

    store = MagicMock()
    with patch(
        "agentscaffold.review.queries.get_all_adrs",
        return_value=[{"a.number": 1, "a.title": "Caching", "a.status": "Accepted"}],
    ):
        result = _tool_find_adrs(store, {"topic": "cach"}, {})

    assert result["count"] == 1
    assert not _has_dotted_key(result["adrs"])


# ---------------------------------------------------------------------------
# Finding B: orient ADR active filter + clean output
# ---------------------------------------------------------------------------


def test_orient_excludes_superseded_adr_and_cleans():
    from pathlib import Path

    from agentscaffold.mcp import server

    store = MagicMock()
    store.get_stats.return_value = {"files": 1, "plans": 1}
    store.query.return_value = [{"cnt": 0}]

    adrs = [
        {"a.number": 1, "a.title": "Active one", "a.status": "Accepted"},
        {"a.number": 2, "a.title": "Old one", "a.status": "Superseded by ADR-030"},
    ]

    with (
        patch("agentscaffold.mcp.coverage.repo_coverage", return_value={}),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[{"p.number": 9, "p.title": "P", "p.status": "COMPLETE (2026-07-09)"}],
        ),
        patch("agentscaffold.review.queries.get_hot_files", return_value=[]),
        patch("agentscaffold.review.queries.get_all_studies", return_value=[]),
        patch("agentscaffold.review.queries.get_all_adrs", return_value=adrs),
        patch("agentscaffold.review.queries.get_open_backlog_items", return_value=[]),
        patch.object(server, "_parse_workflow_state", return_value={}),
        patch.object(server, "_current_project_or_none", return_value=None),
    ):
        result = server._tool_orient(store, {}, Path("/tmp"), None)

    active_titles = [a["title"] for a in result["active_adrs"]]
    assert active_titles == ["Active one"]
    assert not _has_dotted_key(result["active_adrs"])
    assert result["recent_plans"][0]["status_normalized"] == "Complete"
