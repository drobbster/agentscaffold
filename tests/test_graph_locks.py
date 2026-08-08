"""Regression tests for graph write-lock reaping (Plan 254)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from agentscaffold.graph.locks import (
    GRAPH_WRITE_LOCK_NAME,
    graph_write_lock,
    graph_write_lock_held,
    wait_for_graph_write_lock_clear,
)


def _plant_lock(db: Path, *, pid: int, purpose: str = "dead", age_s: float = 0.0) -> Path:
    lock = db.parent / GRAPH_WRITE_LOCK_NAME
    lock.mkdir(parents=True, exist_ok=True)
    (lock / "owner.json").write_text(
        json.dumps({"pid": pid, "purpose": purpose, "created_at": time.time() - age_s}),
        encoding="utf-8",
    )
    if age_s:
        past = time.time() - age_s
        os.utime(lock, (past, past))
    return lock


def test_dead_owner_is_reaped_within_short_waiter_budget(tmp_path: Path, monkeypatch) -> None:
    """Abandoned locks with a dead pid clear without waiting for the 600s mtime gate."""
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    lock = _plant_lock(db, pid=999_999_999, purpose="index")
    monkeypatch.setattr(locks_mod, "_pid_is_alive", lambda _pid: False)

    assert wait_for_graph_write_lock_clear(db, timeout=0.5, stale_after=600.0) is True
    assert not lock.exists()


def test_live_owner_is_not_reaped(tmp_path: Path, monkeypatch) -> None:
    """A lock whose owner pid is still alive must block waiters."""
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    lock = _plant_lock(db, pid=os.getpid(), purpose="index")
    monkeypatch.setattr(locks_mod, "_pid_is_alive", lambda pid: pid == os.getpid())

    assert wait_for_graph_write_lock_clear(db, timeout=0.3, stale_after=600.0) is False
    assert lock.exists()


def test_missing_owner_json_still_respects_mtime(tmp_path: Path) -> None:
    """Without owner metadata, only the mtime gate may reap."""
    db = tmp_path / "graph.duckdb"
    lock = db.parent / GRAPH_WRITE_LOCK_NAME
    lock.mkdir(parents=True, exist_ok=True)

    assert wait_for_graph_write_lock_clear(db, timeout=0.2, stale_after=600.0) is False
    assert lock.exists()

    past = time.time() - 10.0
    os.utime(lock, (past, past))
    assert wait_for_graph_write_lock_clear(db, timeout=0.2, stale_after=1.0) is True
    assert not lock.exists()


def test_unknown_pid_liveness_falls_through_to_mtime(tmp_path: Path, monkeypatch) -> None:
    """When the platform cannot answer, keep today's mtime behaviour."""
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    lock = _plant_lock(db, pid=42, purpose="index")
    monkeypatch.setattr(locks_mod, "_pid_is_alive", lambda _pid: None)

    assert wait_for_graph_write_lock_clear(db, timeout=0.2, stale_after=600.0) is False
    assert lock.exists()

    past = time.time() - 10.0
    os.utime(lock, (past, past))
    assert wait_for_graph_write_lock_clear(db, timeout=0.2, stale_after=1.0) is True
    assert not lock.exists()


def test_pid_is_alive_maps_permission_error_to_true(monkeypatch) -> None:
    from agentscaffold.graph import locks as locks_mod

    def _boom(_pid: int, _sig: int) -> None:
        raise PermissionError("not permitted")

    monkeypatch.setattr(locks_mod.os, "kill", _boom)
    assert locks_mod._pid_is_alive(1) is True


def test_pid_is_alive_maps_process_lookup_to_false(monkeypatch) -> None:
    from agentscaffold.graph import locks as locks_mod

    def _boom(_pid: int, _sig: int) -> None:
        raise ProcessLookupError("no such process")

    monkeypatch.setattr(locks_mod.os, "kill", _boom)
    assert locks_mod._pid_is_alive(999_999_999) is False


def test_permission_error_treated_as_alive_does_not_reap(tmp_path: Path, monkeypatch) -> None:
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    lock = _plant_lock(db, pid=1, purpose="index")
    monkeypatch.setattr(locks_mod, "_pid_is_alive", lambda _pid: True)

    assert wait_for_graph_write_lock_clear(db, timeout=0.2, stale_after=600.0) is False
    assert lock.exists()


def test_graph_write_lock_timeout_names_path_and_owner(tmp_path: Path, monkeypatch) -> None:
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    _plant_lock(db, pid=os.getpid(), purpose="governance_write")
    monkeypatch.setattr(locks_mod, "_pid_is_alive", lambda pid: pid == os.getpid())

    with pytest.raises(TimeoutError) as excinfo:
        with graph_write_lock(db, purpose="waiter", timeout=0.2, stale_after=600.0):
            pass

    message = str(excinfo.value)
    assert str(db.parent / GRAPH_WRITE_LOCK_NAME) in message
    assert "governance_write" in message
    assert "still running" not in message.lower()


def test_open_graph_error_avoids_still_running_wording(tmp_path: Path, monkeypatch) -> None:
    import agentscaffold.graph as graph_mod
    from agentscaffold.graph import GraphLockError
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    _plant_lock(db, pid=os.getpid(), purpose="index")
    monkeypatch.setattr(locks_mod, "wait_for_graph_write_lock_clear", lambda *a, **k: False)
    monkeypatch.setattr(graph_mod, "_resolve_db_path", lambda _config: db)
    monkeypatch.setattr(graph_mod, "_resolve_backend", lambda _config: "duckpgq")

    with pytest.raises(GraphLockError) as excinfo:
        graph_mod.open_graph(None)

    message = str(excinfo.value)
    assert str(db) in message
    assert "still running" not in message.lower()
    assert GRAPH_WRITE_LOCK_NAME in message or "lock" in message.lower()


def test_failed_owner_write_releases_anonymous_lock(tmp_path: Path, monkeypatch) -> None:
    """If owner.json cannot be written after mkdir, do not hold the lock anonymously."""
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    monkeypatch.setattr(locks_mod, "_write_owner", lambda *a, **k: False)

    with pytest.raises(OSError, match="owner metadata"):
        with graph_write_lock(db, purpose="test", timeout=1.0):
            pass

    assert not (db.parent / GRAPH_WRITE_LOCK_NAME).exists()


def test_graph_write_lock_held_false_after_dead_owner_reap(tmp_path: Path, monkeypatch) -> None:
    from agentscaffold.graph import locks as locks_mod

    db = tmp_path / "graph.duckdb"
    _plant_lock(db, pid=999_999_999, purpose="index")
    monkeypatch.setattr(locks_mod, "_pid_is_alive", lambda _pid: False)

    assert graph_write_lock_held(db, stale_after=600.0) is False
