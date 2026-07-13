"""Plan 246: why_empty explainer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agentscaffold.mcp.why_empty import explain_why_empty


def test_why_empty_missing_target() -> None:
    store = MagicMock()
    store.get_stats.return_value = {"files": 10}
    with patch(
        "agentscaffold.mcp.why_empty.repo_coverage",
        return_value={"available": True, "parsed_pct": 80},
    ):
        result = explain_why_empty(store, kind="impact", target="", meta={})
    assert any("missing" in r.lower() or "Required" in r for r in result["reasons"])


def test_why_empty_degraded_search() -> None:
    store = MagicMock()
    store.get_stats.return_value = {"files": 10}
    with patch(
        "agentscaffold.mcp.why_empty.repo_coverage",
        return_value={"available": True, "parsed_pct": 90},
    ):
        result = explain_why_empty(
            store,
            kind="search",
            query="normalize_feeds",
            meta={"retrieval_status": "degraded", "retrieval_reason": "no embeddings"},
        )
    assert any("degraded" in r.lower() for r in result["reasons"])
    assert any("grep" in s.lower() for s in result["suggestions"])
