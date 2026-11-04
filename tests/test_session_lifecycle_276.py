"""Plan 276: sessions expire when idle and are stamped with their project."""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _set(store, session_id: str, **columns: str) -> None:
    assignments = ", ".join(f"{column} = '{value}'" for column, value in columns.items())
    store.execute(f"UPDATE Session SET {assignments} WHERE id = '{session_id}'")


def _open_ids(store) -> set[str]:
    rows = store.query("SELECT id AS \"id\" FROM Session WHERE endedAt IS NULL OR endedAt = ''")
    return {row["id"] for row in rows}


@pytest.fixture()
def store(tmp_path):
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.pipeline import run_pipeline

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    db_path = tmp_path / "graph.db"
    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))
    run_pipeline(repo, config)
    backend = DuckPGQBackend(db_path)
    yield backend
    backend.close()


# ---------------------------------------------------------------------------
# graph.sessions
# ---------------------------------------------------------------------------


def test_idle_session_is_closed_by_the_next_start(store) -> None:
    from agentscaffold.graph.sessions import AUTO_CLOSE_SUFFIX, get_session, start_session

    old = start_session(store, summary="old chat", project="lone", idle_hours=12)
    _set(store, old, lastActivity=_ago(13))

    new = start_session(store, summary="new chat", project="lone", idle_hours=12)

    assert new != old
    closed = get_session(store, old)
    assert closed["ended_at"]
    assert closed["summary"].endswith(AUTO_CLOSE_SUFFIX)


def test_start_inside_the_idle_window_reuses_and_refreshes(store) -> None:
    from agentscaffold.graph.sessions import get_session, start_session

    first = start_session(store, project="lone", idle_hours=12)
    stale_mark = _ago(2)
    _set(store, first, lastActivity=stale_mark)

    again = start_session(store, project="lone", idle_hours=12)

    assert again == first
    assert get_session(store, first)["last_activity"] > stale_mark


def test_new_sessions_record_their_project(store) -> None:
    from agentscaffold.graph.sessions import get_session, start_session

    sid = start_session(store, project="lone", idle_hours=12)
    assert get_session(store, sid)["project"] == "lone"


def test_recent_legacy_session_is_not_reused_by_a_stamped_start(store) -> None:
    from agentscaffold.graph.sessions import start_session

    legacy = start_session(store, project=None, idle_hours=12)
    stamped = start_session(store, project="lone", idle_hours=12)

    assert stamped != legacy
    assert legacy in _open_ids(store)


def test_idle_legacy_session_is_closed_by_a_stamped_start(store) -> None:
    from agentscaffold.graph.sessions import start_session

    legacy = start_session(store, project=None, idle_hours=12)
    _set(store, legacy, lastActivity=_ago(30))

    start_session(store, project="lone", idle_hours=12)

    assert legacy not in _open_ids(store)


def test_legacy_session_without_last_activity_ages_from_its_date(store) -> None:
    from agentscaffold.graph.sessions import start_session

    old = start_session(store, project="lone", idle_hours=12)
    _set(store, old, lastActivity="", date=_ago(48))

    new = start_session(store, project="lone", idle_hours=12)

    assert new != old
    assert old not in _open_ids(store)


def test_force_new_closes_even_an_active_session(store) -> None:
    from agentscaffold.graph.sessions import FORCE_NEW_SUFFIX, get_session, start_session

    current = start_session(store, project="lone", idle_hours=12)
    fresh = start_session(store, project="lone", idle_hours=12, force_new=True)

    assert fresh != current
    assert get_session(store, current)["summary"].endswith(FORCE_NEW_SUFFIX)
    assert _open_ids(store) == {fresh}


def test_zero_idle_hours_disables_expiry(store) -> None:
    from agentscaffold.graph.sessions import start_session

    old = start_session(store, project="lone", idle_hours=0)
    _set(store, old, lastActivity=_ago(24 * 60))

    assert start_session(store, project="lone", idle_hours=0) == old


def test_idle_aware_lookup_never_writes(store) -> None:
    from agentscaffold.graph.sessions import find_open_session, start_session

    sid = start_session(store, project="lone", idle_hours=12)
    _set(store, sid, lastActivity=_ago(13))

    assert find_open_session(store, project="lone", exact_project=True, idle_hours=12) is None
    assert sid in _open_ids(store)


def test_exact_lookup_ignores_other_projects(store) -> None:
    from agentscaffold.graph.sessions import find_open_session, start_session

    start_session(store, project="alpha", idle_hours=12)
    assert find_open_session(store, project="beta", exact_project=True) is None


def test_record_decision_on_an_idle_session_starts_a_new_one(store) -> None:
    from agentscaffold.graph.sessions import record_decision, start_session

    old = start_session(store, project="lone", idle_hours=12)
    _set(store, old, lastActivity=_ago(13))

    result = record_decision(store, decision="ship it", project="lone", idle_hours=12)

    assert result["id"] != old
    assert old not in _open_ids(store)


def test_touch_refreshes_only_an_active_session(store) -> None:
    from agentscaffold.graph.sessions import get_session, start_session, touch_session

    sid = start_session(store, project="lone", idle_hours=12)
    mark = _ago(3)
    _set(store, sid, lastActivity=mark)
    assert touch_session(store, project="lone", idle_hours=12) == sid
    assert get_session(store, sid)["last_activity"] > mark

    _set(store, sid, lastActivity=_ago(13))
    assert touch_session(store, project="lone", idle_hours=12) is None


def test_legacy_rows_stay_visible_to_scoped_reads(store) -> None:
    from agentscaffold.graph.sessions import (
        list_sessions,
        record_decision,
        session_decisions_for_plan,
        start_session,
    )

    legacy = start_session(store, project=None, plan_numbers=[42])
    record_decision(store, decision="legacy call", plan_numbers=[42], project=None)
    nulled = start_session(store, project="gone")
    store.execute(f"UPDATE Session SET project = NULL WHERE id = '{nulled}'")
    start_session(store, project="other")

    listed = {s["id"] for s in list_sessions(store, project="lone")}
    assert {legacy, nulled} <= listed
    assert all(s["project"] in {"", "lone"} for s in list_sessions(store, project="lone"))
    decisions = session_decisions_for_plan(store, 42, project="lone")
    assert [d["decision"] for d in decisions] == ["legacy call"]


def test_lookup_on_a_graph_without_last_activity(tmp_path) -> None:
    """A read-only open cannot add the column, so the age falls back to ``date``."""
    import duckdb

    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.sessions import find_open_session

    db = tmp_path / "old.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute(
        "CREATE TABLE Session (id VARCHAR PRIMARY KEY, date VARCHAR, planNumbers VARCHAR, "
        "filesModified VARCHAR, summary VARCHAR, decisions VARCHAR, endedAt VARCHAR, "
        "project VARCHAR DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO Session VALUES ('session::recent', ?, '[]', '[]', '', '[]', '', 'lone')",
        [_ago(1)],
    )
    conn.execute(
        "INSERT INTO Session VALUES ('session::stale', ?, '[]', '[]', '', '[]', '', 'old')",
        [_ago(40)],
    )
    conn.close()

    ro = DuckPGQBackend(db, read_only=True)
    try:
        found = find_open_session(ro, project="lone", exact_project=True, idle_hours=12)
        assert found is not None and found["id"] == "session::recent"
        assert find_open_session(ro, project="old", exact_project=True, idle_hours=12) is None
    finally:
        ro.close()


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


@pytest.fixture()
def lone(tmp_path, monkeypatch):
    from tests.fixtures.lone_project import build_lone_project

    monkeypatch.delenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", raising=False)
    return build_lone_project(tmp_path)


def _call(tool: str, repo: Path, **arguments):
    from agentscaffold.mcp.server import _dispatch_tool

    arguments.setdefault("working_path", str(repo))
    return _dispatch_tool(tool, arguments)


@contextmanager
def _as_of(hours_ago: float):
    """Write sessions as if *hours_ago* hours had passed since.

    Restores ``_now`` itself rather than through ``monkeypatch.undo()``, which
    would also undo the registry isolation in ``conftest``.
    """
    import agentscaffold.graph.sessions as sessions_mod

    real = sessions_mod._now
    sessions_mod._now = lambda: _ago(hours_ago)
    try:
        yield
    finally:
        sessions_mod._now = real


def test_mcp_start_stamps_the_resolved_project(lone) -> None:
    started = _call("scaffold_session_start", lone)
    assert started["session"]["project"] == "lone"


def test_mcp_force_new(lone) -> None:
    first = _call("scaffold_session_start", lone)["id"]
    again = _call("scaffold_session_start", lone)["id"]
    fresh = _call("scaffold_session_start", lone, force_new=True)["id"]
    assert again == first
    assert fresh != first


def test_idle_session_reads_as_closed_in_the_hint(lone) -> None:
    """Plan 275 integration: an idle session must not suppress the hint."""
    with _as_of(13):
        _call("scaffold_session_start", lone)

    orient = _call("scaffold_orient", lone)
    assert orient["meta"]["session_open"] is False
    assert "procedure_hint" in orient["meta"]


def test_governance_writes_refresh_activity_and_reads_do_not(lone) -> None:
    with _as_of(3):
        sid = _call("scaffold_session_start", lone)["id"]

    def last_activity() -> str:
        sessions = _call("scaffold_session_list", lone)["sessions"]
        return next(s["last_activity"] for s in sessions if s["id"] == sid)

    before = last_activity()
    _call("scaffold_search", lone, query="router")
    assert last_activity() == before

    _call(
        "scaffold_record_backlog_item",
        lone,
        plan_number=42,
        items=[{"title": "276 activity probe", "priority": "P3"}],
    )
    assert last_activity() > before


def test_orient_warns_about_a_long_running_session(tmp_path, monkeypatch) -> None:
    from tests.fixtures.lone_project import build_lone_project

    monkeypatch.delenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", raising=False)
    repo = build_lone_project(tmp_path, name="busy", extra_config="sessions:\n  idle_hours: 48\n")
    with _as_of(30):
        _call("scaffold_session_start", repo)

    orient = _call("scaffold_orient", repo)
    warning = orient.get("session_warning") or ""
    assert "30 hours" in warning
    assert "force_new" in warning
    assert orient["meta"]["session_open"] is True


def test_no_warning_for_a_fresh_session(lone) -> None:
    _call("scaffold_session_start", lone)
    assert "session_warning" not in _call("scaffold_orient", lone)


def test_session_context_returns_legacy_sessions(lone, monkeypatch) -> None:
    import agentscaffold.mcp.server as server_mod

    real = server_mod._stamp_project
    monkeypatch.setattr(server_mod, "_stamp_project", lambda _resolution: "")
    legacy = _call("scaffold_session_start", lone, summary="legacy")["id"]
    monkeypatch.setattr(server_mod, "_stamp_project", real)

    ctx = _call("scaffold_session_context", lone)["session_context"]
    assert legacy in str(ctx)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_session_commands_are_stamped_and_scoped(lone, monkeypatch, cli_runner) -> None:
    from agentscaffold.cli import app
    from agentscaffold.config import load_config
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.sessions import get_session, start_session
    from agentscaffold.paths import resolve_db_path

    monkeypatch.chdir(lone)
    db_path = resolve_db_path(load_config(lone / "scaffold.yaml"))

    started = cli_runner.invoke(app, ["session", "start", "--summary", "cli"])
    assert started.exit_code == 0, started.output
    sid = started.output.split("Session started:")[1].split()[0]

    other = DuckPGQBackend(db_path)
    try:
        assert get_session(other, sid)["project"] == "lone"
        foreign = start_session(other, project="elsewhere")
    finally:
        other.close()

    ended = cli_runner.invoke(app, ["session", "end", "--summary", "done"])
    assert ended.exit_code == 0, ended.output

    check = DuckPGQBackend(db_path)
    try:
        assert get_session(check, sid)["ended_at"]
        assert not get_session(check, foreign)["ended_at"]
    finally:
        check.close()
