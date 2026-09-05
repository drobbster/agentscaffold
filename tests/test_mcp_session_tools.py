"""MCP session tools: start, end, list, context, and orient embed (Plan 263)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.mcp.registry import WRITE_TOOLS

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def indexed_store(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    db_path = tmp_path / "graph.db"
    from agentscaffold.config import GraphConfig, ScaffoldConfig

    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))
    run_pipeline(repo, config)
    store = DuckPGQBackend(db_path)
    yield store, config, repo
    store.close()


def test_write_tools_include_session_start_and_end():
    assert "scaffold_session_start" in WRITE_TOOLS
    assert "scaffold_session_end" in WRITE_TOOLS
    assert "scaffold_session_record_decision" in WRITE_TOOLS
    assert "scaffold_session_list" not in WRITE_TOOLS
    assert "scaffold_session_context" not in WRITE_TOOLS


def test_mcp_session_round_trip(indexed_store, monkeypatch):
    store, _config, _repo = indexed_store
    monkeypatch.setattr("agentscaffold.mcp.server._current_project_or_none", lambda: None)
    from agentscaffold.mcp.server import (
        _tool_session_context,
        _tool_session_end,
        _tool_session_list,
        _tool_session_start,
    )

    meta = {}
    started = _tool_session_start(store, {"plan_numbers": [263], "summary": "mcp start"}, meta)
    sid = started["id"]
    assert sid.startswith("session::")
    again = _tool_session_start(store, {"summary": "second"}, meta)
    assert again["id"] == sid

    files = store.query('SELECT path AS "f.path" FROM File LIMIT 1')
    file_path = files[0]["f.path"] if files else "missing.py"
    ended = _tool_session_end(
        store,
        {
            "summary": "mcp end",
            "decisions": [
                {
                    "decision": "expose sessions on MCP",
                    "evidence": "Session was 0 after 245 plans",
                    "status": "observed",
                }
            ],
            "files": [file_path],
            "plan_numbers": [263],
        },
        meta,
    )
    assert ended["id"] == sid
    assert ended["ended_at"]
    assert ended["summary"] == "mcp end"
    assert ended["decisions"][0]["decision"] == "expose sessions on MCP"
    assert file_path in ended["files_modified"]

    listed = _tool_session_list(store, {"limit": 5}, meta)
    assert listed["count"] >= 1
    assert listed["sessions"][0]["id"] == sid

    ctx = _tool_session_context(store, {"limit": 3}, meta)
    assert ctx["session_context"]["session_count"] >= 1
    assert 263 in ctx["session_context"]["recent_plan_numbers"]

    rows = store.query("SELECT count(*) AS n FROM Session")
    assert rows[0]["n"] >= 1


def test_orient_embeds_session_context(indexed_store, monkeypatch, tmp_path):
    store, config, _repo = indexed_store
    monkeypatch.setattr("agentscaffold.mcp.server._current_project_or_none", lambda: None)
    from agentscaffold.graph.sessions import start_session
    from agentscaffold.mcp.server import _tool_orient

    start_session(store, plan_numbers=[263], summary="in orient")
    result = _tool_orient(store, {}, tmp_path, config, {})
    assert "session_context" in result
    assert result["session_context"]["session_count"] >= 1


def test_orient_omits_session_context_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("agentscaffold.mcp.server._current_project_or_none", lambda: None)
    db_path = tmp_path / "empty.db"
    store = DuckPGQBackend(db_path)
    store.init_schema()
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.mcp.server import _tool_orient

    result = _tool_orient(store, {}, tmp_path, ScaffoldConfig(), {})
    assert "session_context" not in result
    store.close()


def test_record_decision_tool_opens_session(tmp_path, monkeypatch):
    monkeypatch.setattr("agentscaffold.mcp.server._current_project_or_none", lambda: None)
    db_path = tmp_path / "empty.db"
    store = DuckPGQBackend(db_path)
    store.init_schema()
    from agentscaffold.mcp.server import _tool_session_record_decision

    result = _tool_session_record_decision(
        store,
        {
            "decision": "require decisions to be populated",
            "evidence": "optional field would stay empty",
            "status": "observed",
            "kind": "strategic",
            "plan_numbers": [263],
        },
        {},
    )
    assert result["status"] == "recorded"
    assert result["decision_count"] >= 1
    assert result["decision"]["kind"] == "strategic"
    store.close()


def test_decision_context_includes_session_decisions(tmp_path, monkeypatch):
    monkeypatch.setattr("agentscaffold.mcp.server._current_project_or_none", lambda: None)
    db_path = tmp_path / "empty.db"
    store = DuckPGQBackend(db_path)
    store.init_schema()
    from agentscaffold.graph.sessions import record_decision
    from agentscaffold.mcp.server import _tool_decision_context

    store.create_node(
        "Plan",
        {
            "id": "plan::263",
            "number": 263,
            "title": "Session continuity",
            "status": "In Progress",
        },
    )
    record_decision(
        store,
        decision="do not auto-log findings as decisions",
        evidence="those are not strategic calls",
        status="observed",
        kind="strategic",
        plan_numbers=[263],
    )
    result = _tool_decision_context(store, {"plan_number": 263}, {})
    assert result["has_full_decision_chain"] is True
    assert result["session_decisions"][0]["kind"] == "strategic"
    store.close()


def test_end_without_open_session_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("agentscaffold.mcp.server._current_project_or_none", lambda: None)
    db_path = tmp_path / "empty.db"
    store = DuckPGQBackend(db_path)
    store.init_schema()
    from agentscaffold.mcp.server import _tool_session_end

    result = _tool_session_end(store, {"summary": "nothing"}, {})
    assert result["error"] == "No open session."
    store.close()
