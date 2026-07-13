"""Plan 246: detail=summary vs full."""

from __future__ import annotations

from agentscaffold.mcp.detail import apply_detail


def test_summary_drops_markdown_and_truncates_lists() -> None:
    payload = {
        "challenges": [{"text": f"c{i}"} for i in range(10)],
        "challenges_markdown": "# big",
        "gaps": [{"text": f"g{i}"} for i in range(8)],
        "meta": {},
    }
    summary = apply_detail(payload, "summary")
    full = apply_detail(payload, "full")

    assert "challenges_markdown" not in summary
    assert len(summary["challenges"]) == 5
    assert summary.get("challenges_truncated") == 5
    assert "challenges_markdown" in full
    assert len(full["challenges"]) == 10
    assert len(str(summary)) < len(str(full))
