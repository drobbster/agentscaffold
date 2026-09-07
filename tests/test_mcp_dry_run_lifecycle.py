"""Plan 246: dry_run lifecycle writes nothing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


def test_every_write_tool_advertises_dry_run() -> None:
    from agentscaffold.mcp.registry import WRITE_TOOLS, get_tool_spec

    assert len(WRITE_TOOLS) == 10
    for name in WRITE_TOOLS:
        spec = get_tool_spec(name)
        assert spec is not None
        assert "dry_run" in spec.input_schema.get("properties", {}), name


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


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (
            "scaffold_record_finding",
            {
                "plan_number": 1,
                "review_type": "probe",
                "category": "probe",
                "finding": "probe",
                "dry_run": True,
            },
        ),
        (
            "scaffold_resolve_finding",
            {"finding_id": "rf::none", "resolution": "probe", "dry_run": True},
        ),
        (
            "scaffold_record_findings_batch",
            {
                "plan_number": 1,
                "review_type": "probe",
                "findings": [{"category": "c", "finding": "f"}],
                "dry_run": True,
            },
        ),
        (
            "scaffold_record_backlog_item",
            {"plan_number": 1, "title": "probe", "dry_run": True},
        ),
        (
            "scaffold_resolve_backlog_item",
            {"item_id": "bi::none", "dry_run": True},
        ),
        ("scaffold_session_start", {"summary": "probe", "dry_run": True}),
        (
            "scaffold_session_record_decision",
            {"decision": "probe", "dry_run": True},
        ),
        ("scaffold_session_end", {"dry_run": True}),
    ],
)
def test_remaining_write_tools_advertise_and_honour_dry_run(tool: str, arguments: dict) -> None:
    from agentscaffold.mcp.registry import WRITE_TOOLS, get_tool_spec

    assert tool in WRITE_TOOLS
    spec = get_tool_spec(tool)
    assert spec is not None
    assert "dry_run" in spec.input_schema.get("properties", {})

    with (
        patch("agentscaffold.graph.findings.record_finding") as rec_f,
        patch("agentscaffold.graph.findings.resolve_finding") as res_f,
        patch("agentscaffold.graph.findings.record_findings_batch") as rec_fb,
        patch("agentscaffold.graph.backlog.record_backlog_item") as rec_b,
        patch("agentscaffold.graph.backlog.resolve_backlog_item") as res_b,
        patch("agentscaffold.graph.sessions.start_session") as start,
        patch("agentscaffold.graph.sessions.record_decision") as decide,
        patch("agentscaffold.graph.sessions.end_session") as end,
    ):
        # Dispatch still needs a resolvable project; unit-call the handlers instead.
        from agentscaffold.mcp import server as server_mod

        handler = {
            "scaffold_record_finding": server_mod._tool_record_finding,
            "scaffold_resolve_finding": server_mod._tool_resolve_finding,
            "scaffold_record_findings_batch": server_mod._tool_record_findings_batch,
            "scaffold_record_backlog_item": server_mod._tool_record_backlog_item,
            "scaffold_resolve_backlog_item": server_mod._tool_resolve_backlog_item,
            "scaffold_session_start": server_mod._tool_session_start,
            "scaffold_session_record_decision": server_mod._tool_session_record_decision,
            "scaffold_session_end": server_mod._tool_session_end,
        }[tool]
        result = handler(MagicMock(), arguments, {})

    assert result["dry_run"] is True
    assert result["would_write"] is True
    assert rec_f.call_count == 0
    assert res_f.call_count == 0
    assert rec_fb.call_count == 0
    assert rec_b.call_count == 0
    assert res_b.call_count == 0
    assert start.call_count == 0
    assert decide.call_count == 0
    assert end.call_count == 0
