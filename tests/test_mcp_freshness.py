"""Tests for MCP freshness oracle and async refresh coordinator."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig
from agentscaffold.mcp import freshness


def _config(async_enabled: bool = True) -> ScaffoldConfig:
    cfg = ScaffoldConfig()
    cfg.freshness.async_enabled = async_enabled
    cfg.freshness.debounce_seconds = 120
    cfg.freshness.background_queue_enabled = True
    cfg.graph.db_path = ".scaffold/graph.db"
    return cfg


@pytest.fixture(autouse=True)
def _reset_coordinator_state() -> None:
    freshness._COORDINATOR.clear()
    yield
    freshness._COORDINATOR.clear()


def test_evaluate_freshness_missing_watermark(tmp_path: Path, monkeypatch) -> None:
    """Missing watermark should return unknown status."""
    cfg = _config()
    monkeypatch.setattr(
        freshness,
        "_current_git_signals",
        lambda _root: {
            "ok": True,
            "head_sha": "abc",
            "index_mtime_ns": 1,
            "dirty_worktree": False,
            "dirty_index": False,
        },
    )
    result = freshness.evaluate_freshness(tmp_path, cfg)
    assert result["freshness_status"] == "unknown"
    assert result["freshness_reason"] == "missing_watermark"
    assert result["oracle_latency_ms"] >= 0


def test_evaluate_freshness_fresh_and_stale(tmp_path: Path, monkeypatch) -> None:
    """Watermark/signal match is fresh, mismatch is stale."""
    cfg = _config()
    wm_path = freshness._watermark_path(tmp_path, cfg)
    wm_path.parent.mkdir(parents=True, exist_ok=True)
    wm = {
        "head_sha": "abc",
        "index_mtime_ns": 7,
        "dirty_worktree": False,
        "dirty_index": False,
    }
    wm_path.write_text(json.dumps(wm))

    monkeypatch.setattr(
        freshness,
        "_current_git_signals",
        lambda _root: {
            "ok": True,
            "head_sha": "abc",
            "index_mtime_ns": 7,
            "dirty_worktree": False,
            "dirty_index": False,
        },
    )
    fresh = freshness.evaluate_freshness(tmp_path, cfg)
    assert fresh["freshness_status"] == "fresh"

    monkeypatch.setattr(
        freshness,
        "_current_git_signals",
        lambda _root: {
            "ok": True,
            "head_sha": "def",
            "index_mtime_ns": 7,
            "dirty_worktree": False,
            "dirty_index": False,
        },
    )
    stale = freshness.evaluate_freshness(tmp_path, cfg)
    assert stale["freshness_status"] == "stale"


def test_maybe_schedule_refresh_debounces(tmp_path: Path, monkeypatch) -> None:
    """Second eligible trigger inside window should debounce."""
    cfg = _config()

    class _InlineThread:
        def __init__(self, *, target, args, daemon, name):
            self._target = target
            self._args = args

        def start(self) -> None:
            self._target(*self._args)

    def _fake_worker(root: Path, _cfg: ScaffoldConfig, _reason: str) -> None:
        state = freshness._coordinator_state(root)
        with state.lock:
            state.running = False
            state.last_result = "idle"
            state.pending = False

    monkeypatch.setattr(freshness.threading, "Thread", _InlineThread)
    monkeypatch.setattr(freshness, "_refresh_worker", _fake_worker)

    first = freshness.maybe_schedule_async_refresh(
        tmp_path,
        cfg,
        tool_name="scaffold_prepare_review",
        reason="test",
    )
    second = freshness.maybe_schedule_async_refresh(
        tmp_path,
        cfg,
        tool_name="scaffold_prepare_review",
        reason="test",
    )

    assert first["refresh_triggered"] is True
    assert second["refresh_triggered"] is False
    assert second["refresh_schedule_reason"] == "debounced"


def test_maybe_schedule_refresh_coalesces_while_running(tmp_path: Path) -> None:
    """When running, additional trigger is coalesced into pending."""
    cfg = _config()
    state = freshness._coordinator_state(tmp_path)
    with state.lock:
        state.running = True
        state.pending = False
        state.last_result = "running"

    result = freshness.maybe_schedule_async_refresh(
        tmp_path,
        cfg,
        tool_name="scaffold_prepare_review",
        reason="test",
    )

    assert result["refresh_triggered"] is False
    assert result["refresh_schedule_reason"] == "coalesced_running"
    assert state.pending is True


def test_single_flight_parallel_triggers(tmp_path: Path, monkeypatch) -> None:
    """Parallel eligible triggers should schedule exactly one refresh."""
    cfg = _config()
    real_thread = threading.Thread

    class _NoopThread:
        def __init__(self, *, target, args, daemon, name):
            self._target = target
            self._args = args

        def start(self) -> None:
            # Keep state.running=True so parallel calls coalesce.
            return None

    monkeypatch.setattr(freshness.threading, "Thread", _NoopThread)

    results: list[dict] = []
    res_lock = threading.Lock()

    def _call() -> None:
        out = freshness.maybe_schedule_async_refresh(
            tmp_path,
            cfg,
            tool_name="scaffold_prepare_review",
            reason="parallel_test",
        )
        with res_lock:
            results.append(out)

    workers = [real_thread(target=_call) for _ in range(10)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    triggered = sum(1 for r in results if r.get("refresh_triggered"))
    coalesced = sum(1 for r in results if r.get("refresh_schedule_reason") == "coalesced_running")
    assert triggered == 1
    assert coalesced >= 1


def test_running_no_queue_mode(tmp_path: Path) -> None:
    """If queue is disabled, in-flight refresh should not set pending."""
    cfg = _config()
    cfg.freshness.background_queue_enabled = False

    state = freshness._coordinator_state(tmp_path)
    with state.lock:
        state.running = True
        state.pending = False
        state.last_result = "running"

    out = freshness.maybe_schedule_async_refresh(
        tmp_path,
        cfg,
        tool_name="scaffold_prepare_review",
        reason="running_no_queue",
    )
    assert out["refresh_triggered"] is False
    assert out["refresh_schedule_reason"] == "running_no_queue"
    assert state.pending is False
