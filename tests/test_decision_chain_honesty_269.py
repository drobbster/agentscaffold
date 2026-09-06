"""Plan 269: has_full_decision_chain requires an ADR or spike."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agentscaffold.mcp.server import _tool_decision_context


def _ctx(*, adrs=None, spikes=None, studies=None, decisions=None):
    store = MagicMock()
    store.get_stats.return_value = {"files": 10, "plans": 1}
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.title": "T", "p.status": "Complete"},
        ),
        patch("agentscaffold.review.queries.get_adrs_for_plan", return_value=adrs or []),
        patch("agentscaffold.review.queries.get_spikes_for_plan", return_value=spikes or []),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=studies or []),
        patch("agentscaffold.review.queries.get_plan_dependencies", return_value=[]),
        patch(
            "agentscaffold.graph.sessions.session_decisions_for_plan",
            return_value=decisions or [],
        ),
    ):
        return _tool_decision_context(store, {"plan_number": 270}, {})


def test_session_only_is_not_a_full_chain() -> None:
    result = _ctx(decisions=[{"kind": "operational", "decision": "keep netting"}])
    assert result["has_full_decision_chain"] is False
    assert result["session_decisions"]


def test_adr_makes_the_chain_full() -> None:
    result = _ctx(adrs=[{"number": 25, "title": "MCP topology"}])
    assert result["has_full_decision_chain"] is True


def test_studies_alone_are_not_a_full_chain() -> None:
    result = _ctx(studies=[{"studyId": "STU-1"}])
    assert result["has_full_decision_chain"] is False
