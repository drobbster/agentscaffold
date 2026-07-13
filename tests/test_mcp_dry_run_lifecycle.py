"""Plan 246: dry_run lifecycle writes nothing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


def test_begin_plan_dry_run_skips_writes() -> None:
    from agentscaffold.mcp.server import _tool_begin_plan

    store = MagicMock()
    store.get_stats.return_value = {
        "files": 5,
        "plans": 1,
        "functions": 1,
        "methods": 0,
        "classes": 0,
    }

    wrote = {"findings": 0, "stamp": 0}

    def _batch(*a, **k):
        wrote["findings"] += 1
        return {"ids": ["x"], "count": 1}

    def _stamp(*a, **k):
        wrote["stamp"] += 1
        return "2026-07-12T00:00:00Z"

    with (
        patch(
            "agentscaffold.mcp.server._tool_prepare_review",
            return_value={
                "challenges": [{"category": "c", "text": "t", "severity": "high", "evidence": {}}],
                "gaps": [],
                "open_findings": [],
            },
        ),
        patch("agentscaffold.graph.findings.record_findings_batch", side_effect=_batch),
        patch("agentscaffold.review.queries.stamp_plan_reviewed", side_effect=_stamp),
        patch(
            "agentscaffold.mcp.plan_card.build_plan_card",
            return_value={"plan_number": 1},
        ),
    ):
        result = _tool_begin_plan(
            store,
            {"plan_number": 1, "dry_run": True},
            {},
            Path.cwd(),
            MagicMock(),
        )

    assert result["dry_run"] is True
    assert result["findings_written"]["count"] == 0
    assert result["reviewed_at"] is None
    assert wrote["findings"] == 0
    assert wrote["stamp"] == 0


def test_complete_plan_dry_run_skips_writes() -> None:
    from agentscaffold.mcp.server import _tool_complete_plan

    store = MagicMock()
    store.get_stats.return_value = {"files": 5, "plans": 1}
    wrote = {"n": 0}

    def _batch(*a, **k):
        wrote["n"] += 1
        return {"ids": ["x"], "count": 1}

    with (
        patch(
            "agentscaffold.mcp.server._tool_prepare_retro",
            return_value={
                "retro_insights": [{"category": "retro", "text": "learn"}],
                "verification": [],
            },
        ),
        patch("agentscaffold.graph.findings.record_findings_batch", side_effect=_batch),
        patch("agentscaffold.graph.backlog.record_backlog_items_batch", side_effect=_batch),
    ):
        result = _tool_complete_plan(
            store,
            {
                "plan_number": 1,
                "dry_run": True,
                "backlog_items": [{"title": "x"}],
            },
            {},
        )

    assert result["dry_run"] is True
    assert result["findings_written"]["count"] == 0
    assert result["backlog_items_written"]["count"] == 0
    assert wrote["n"] == 0
