"""Plan 275: tool responses say when no AgentScaffold session is open."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"

EXCLUDED_TOOLS = (
    "scaffold_session_start",
    "scaffold_session_end",
    "scaffold_session_list",
    "scaffold_session_context",
    "scaffold_session_record_decision",
    "scaffold_projects",
)


def _session_count(store) -> int:
    return int(store.query('SELECT count(*) AS "n" FROM Session')[0]["n"])


@pytest.fixture()
def indexed_store(tmp_path):
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.pipeline import run_pipeline

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    db_path = tmp_path / "graph.db"
    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))
    run_pipeline(repo, config)
    store = DuckPGQBackend(db_path)
    yield store
    store.close()


@pytest.fixture()
def single_project(tmp_path, monkeypatch):
    """A registered, indexed lone repository (no workspace.yaml)."""
    from agentscaffold.config import load_config
    from agentscaffold.graph.pipeline import run_pipeline
    from agentscaffold.workspace_registry import register_workspace

    monkeypatch.delenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", raising=False)
    repo = tmp_path / "lone"
    shutil.copytree(FIXTURE_REPO, repo)
    (repo / "scaffold.yaml").write_text(
        f"project:\n  name: lone\ngraph:\n  db_path: {tmp_path / 'lone.duckdb'}\n"
    )
    run_pipeline(root=repo, config=load_config(repo / "scaffold.yaml"))
    register_workspace(repo, name="lone")
    return repo


def _call(tool: str, repo: Path, **arguments):
    from agentscaffold.mcp.server import _dispatch_tool

    arguments.setdefault("working_path", str(repo))
    return _dispatch_tool(tool, arguments)


# ---------------------------------------------------------------------------
# session_meta
# ---------------------------------------------------------------------------


def test_no_open_session_with_hint(indexed_store) -> None:
    from agentscaffold.mcp.procedure_hint import session_meta

    meta = session_meta(indexed_store, None, with_hint=True)
    assert meta["session_open"] is False
    hint = meta["procedure_hint"]
    assert len(hint) <= 200
    assert hint.index("scaffold_session_start") < hint.index("scaffold_orient")


def test_no_open_session_without_hint(indexed_store) -> None:
    from agentscaffold.mcp.procedure_hint import session_meta

    assert session_meta(indexed_store, None, with_hint=False) == {"session_open": False}


def test_open_session_under_the_writers_key(indexed_store) -> None:
    from agentscaffold.graph.sessions import start_session
    from agentscaffold.mcp.procedure_hint import session_meta

    start_session(indexed_store, summary="275", project=None)
    assert session_meta(indexed_store, None, with_hint=True) == {"session_open": True}


def test_a_session_in_another_project_does_not_count(indexed_store) -> None:
    from agentscaffold.graph.sessions import start_session
    from agentscaffold.mcp.procedure_hint import session_meta

    start_session(indexed_store, summary="alpha work", project="alpha")
    assert session_meta(indexed_store, "beta", with_hint=False) == {"session_open": False}
    assert session_meta(indexed_store, "alpha", with_hint=False) == {"session_open": True}


def test_lookup_failure_yields_nothing() -> None:
    from agentscaffold.mcp.procedure_hint import session_meta

    class Broken:
        def query(self, *_a, **_k):
            raise RuntimeError("graph locked")

    assert session_meta(Broken(), None, with_hint=True) == {}


def test_lookup_never_creates_a_session(indexed_store) -> None:
    from agentscaffold.mcp.procedure_hint import session_meta

    before = _session_count(indexed_store)
    for _ in range(3):
        session_meta(indexed_store, None, with_hint=True)
    assert _session_count(indexed_store) == before


@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_opt_out_disables_the_lookup(monkeypatch, value: str) -> None:
    from agentscaffold.mcp.procedure_hint import procedure_delivery_enabled

    monkeypatch.setenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", value)
    assert procedure_delivery_enabled() is False


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_orient_without_session_carries_hint_and_reads_carry_boolean(single_project) -> None:
    orient = _call("scaffold_orient", single_project)
    assert orient["meta"]["session_open"] is False
    assert len(orient["meta"]["procedure_hint"]) <= 200

    search = _call("scaffold_search", single_project, query="helper")
    assert search["meta"]["session_open"] is False
    assert "procedure_hint" not in search["meta"]


def test_write_tool_without_session_carries_hint(single_project) -> None:
    result = _call(
        "scaffold_record_backlog_item",
        single_project,
        plan_number=1,
        items=[{"title": "275 hint probe"}],
        dry_run=True,
    )
    assert result["meta"]["session_open"] is False
    assert "procedure_hint" in result["meta"]


def test_single_project_session_is_seen_after_start(single_project) -> None:
    """Regression for rf::248d2c3854ae: the lookup uses the writer's key."""
    started = _call("scaffold_session_start", single_project, summary="275")
    assert started["id"].startswith("session::")

    orient = _call("scaffold_orient", single_project)
    assert orient["meta"]["session_open"] is True
    assert "procedure_hint" not in orient["meta"]


@pytest.mark.parametrize("tool", EXCLUDED_TOOLS)
def test_session_and_projects_tools_carry_neither_key(single_project, tool: str) -> None:
    arguments: dict[str, object] = {}
    if tool == "scaffold_session_record_decision":
        arguments = {"decision": "probe", "dry_run": True}
    elif tool == "scaffold_session_start":
        arguments = {"dry_run": True}
    result = _call(tool, single_project, **arguments)
    meta = result.get("meta", {})
    assert "session_open" not in meta
    assert "procedure_hint" not in meta


def test_error_response_carries_neither_key(single_project) -> None:
    result = _call("scaffold_query", single_project)
    assert "error" in result
    meta = result.get("meta", {})
    assert "session_open" not in meta
    assert "procedure_hint" not in meta


def test_lookup_failure_leaves_the_tool_result_intact(single_project, monkeypatch) -> None:
    import agentscaffold.mcp.procedure_hint as hint_mod
    from agentscaffold.graph import GraphLockError

    def _locked(*_a, **_k):
        raise GraphLockError("locked")

    monkeypatch.setattr(hint_mod, "find_open_session", _locked)
    orient = _call("scaffold_orient", single_project)
    assert "error" not in orient
    assert "session_brief" in orient
    assert "session_open" not in orient["meta"]


def test_opt_out_removes_the_keys(single_project, monkeypatch) -> None:
    monkeypatch.setenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", "0")
    orient = _call("scaffold_orient", single_project)
    assert "session_open" not in orient["meta"]
    assert "procedure_hint" not in orient["meta"]


def test_session_in_project_a_is_not_open_for_project_b(
    scratch_two_project_workspace, monkeypatch
) -> None:
    from agentscaffold.mcp.server import _dispatch_tool
    from tests.fixtures.multiproject import index_workspace

    monkeypatch.delenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", raising=False)
    ws = scratch_two_project_workspace
    index_workspace(ws)
    alpha_path = str(ws.source_file(ws.alpha_name))
    beta_path = str(ws.source_file(ws.beta_name))

    _dispatch_tool("scaffold_session_start", {"working_path": alpha_path, "summary": "alpha"})

    alpha = _dispatch_tool("scaffold_orient", {"working_path": alpha_path})
    beta = _dispatch_tool("scaffold_orient", {"working_path": beta_path})
    assert alpha["meta"]["session_open"] is True
    assert beta["meta"]["session_open"] is False
    assert "procedure_hint" in beta["meta"]
