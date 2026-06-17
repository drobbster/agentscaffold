"""Async embedding scheduler tests for Plan 232."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.graph import embedding_scheduler


def _config(tmp_path: Path, *, policy: str = "idle", debounce: int = 0) -> ScaffoldConfig:
    cfg = ScaffoldConfig()
    cfg.graph = GraphConfig(
        db_path=str(tmp_path / ".scaffold" / "graph.duckdb"),
        async_embeddings=policy,
        embedding_min_interval_seconds=debounce,
    )
    return cfg


def test_policy_off_does_not_schedule_or_start_worker(monkeypatch, tmp_path: Path) -> None:
    embedding_scheduler._reset_for_tests()
    started = False

    def _start(*_args, **_kwargs) -> None:
        nonlocal started
        started = True

    monkeypatch.setattr(embedding_scheduler.threading.Thread, "start", _start)

    result = embedding_scheduler.maybe_schedule_async_embeddings(
        tmp_path,
        _config(tmp_path, policy="off"),
        reason="no embeddings indexed",
    )

    assert result == {"embedding_triggered": False, "embedding_schedule_reason": "policy_off"}
    assert started is False
    assert (
        embedding_scheduler.embedding_runtime_state(tmp_path, _config(tmp_path, policy="off"))[
            "embedding_policy"
        ]
        == "off"
    )


def test_scheduler_defers_while_structural_index_lock_exists(tmp_path: Path) -> None:
    embedding_scheduler._reset_for_tests()
    cfg = _config(tmp_path, policy="idle")
    lock_dir = tmp_path / ".scaffold" / "index.lock"
    lock_dir.mkdir(parents=True)

    result = embedding_scheduler.maybe_schedule_async_embeddings(
        tmp_path,
        cfg,
        reason="retrieval degraded",
    )

    assert result == {
        "embedding_triggered": False,
        "embedding_schedule_reason": "deferred_structural_lock",
    }
    assert (
        embedding_scheduler.embedding_runtime_state(tmp_path, cfg)["embedding_state"] == "deferred"
    )


def test_scheduler_debounces_back_to_back_requests(monkeypatch, tmp_path: Path) -> None:
    embedding_scheduler._reset_for_tests()
    cfg = _config(tmp_path, policy="interval", debounce=60)
    starts = 0

    class _Thread:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def start(self) -> None:
            nonlocal starts
            starts += 1

    monkeypatch.setattr(embedding_scheduler.threading, "Thread", _Thread)

    first = embedding_scheduler.maybe_schedule_async_embeddings(
        tmp_path,
        cfg,
        reason="first",
    )
    # Simulate the background worker completing so debounce, not running state,
    # is what suppresses the second request.
    state = embedding_scheduler._coordinator_state(tmp_path)
    with state.lock:
        state.running = False
        state.last_result = "idle"

    second = embedding_scheduler.maybe_schedule_async_embeddings(
        tmp_path,
        cfg,
        reason="second",
    )

    assert first["embedding_schedule_reason"] == "scheduled"
    assert second["embedding_schedule_reason"] == "debounced"
    assert starts == 1


def test_worker_records_embedding_errors_without_raising(monkeypatch, tmp_path: Path) -> None:
    embedding_scheduler._reset_for_tests()
    cfg = _config(tmp_path, policy="idle")

    def _raise_missing_search_extra(*_args, **_kwargs):
        raise ImportError("sentence-transformers missing")

    monkeypatch.setattr("agentscaffold.graph.index", _raise_missing_search_extra)

    embedding_scheduler._embedding_worker(tmp_path, cfg, "missing embeddings", None)

    state = embedding_scheduler.embedding_runtime_state(tmp_path, cfg)
    assert state["embedding_state"] == "failed"
    assert state["embedding_last_error"] == "sentence-transformers missing"
