"""Async embedding refresh coordinator for MCP-triggered retrieval freshness."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscaffold.config import ScaffoldConfig

_VALID_POLICIES = frozenset({"off", "idle", "interval", "commit"})


@dataclass
class _EmbeddingCoordinatorState:
    lock: threading.Lock
    running: bool = False
    pending: bool = False
    last_trigger_monotonic: float | None = None
    last_start_monotonic: float | None = None
    last_end_monotonic: float | None = None
    last_error: str | None = None
    last_result: str = "idle"
    last_reason: str | None = None
    pending_file_paths: set[str] = field(default_factory=set)


_STATE_LOCK = threading.Lock()
_COORDINATOR: dict[str, _EmbeddingCoordinatorState] = {}


def _workspace_key(root: Path) -> str:
    return str(root.resolve())


def _coordinator_state(root: Path) -> _EmbeddingCoordinatorState:
    key = _workspace_key(root)
    with _STATE_LOCK:
        state = _COORDINATOR.get(key)
        if state is None:
            state = _EmbeddingCoordinatorState(lock=threading.Lock())
            _COORDINATOR[key] = state
        return state


def _policy(config: ScaffoldConfig) -> str:
    policy = str(getattr(config.graph, "async_embeddings", "off") or "off").lower()
    return policy if policy in _VALID_POLICIES else "off"


def _debounce_seconds(config: ScaffoldConfig) -> int:
    return max(0, int(getattr(config.graph, "embedding_min_interval_seconds", 0) or 0))


def _db_path(root: Path, config: ScaffoldConfig) -> Path:
    from agentscaffold.paths import resolve_db_path

    return resolve_db_path(config, start=root)


def _structural_lock_path(root: Path, config: ScaffoldConfig) -> Path:
    return _db_path(root, config).parent / "index.lock"


def _structural_index_running(root: Path, config: ScaffoldConfig) -> bool:
    return _structural_lock_path(root, config).is_dir()


def embedding_runtime_state(root: Path, config: ScaffoldConfig) -> dict[str, Any]:
    """Return current async embedding lane state for MCP response metadata."""
    state = _coordinator_state(root)
    now = time.monotonic()
    debounce = _debounce_seconds(config)
    remaining = 0.0
    if state.last_trigger_monotonic is not None:
        remaining = max(0.0, debounce - (now - state.last_trigger_monotonic))
    return {
        "embedding_policy": _policy(config),
        "embedding_state": "running" if state.running else state.last_result,
        "embedding_pending": state.pending,
        "embedding_debounce_remaining_s": round(remaining, 1),
        "embedding_last_error": state.last_error,
        "embedding_last_reason": state.last_reason,
    }


def maybe_schedule_async_embeddings(
    root: Path,
    config: ScaffoldConfig,
    *,
    reason: str,
    file_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Schedule an async embedding refresh if the configured policy allows it.

    The worker uses the existing process-level model cache in
    ``graph.embeddings``. That makes the model resident only after a non-``off``
    policy schedules work; the default path imports no embedding model.
    """
    policy = _policy(config)
    if policy == "off":
        return {"embedding_triggered": False, "embedding_schedule_reason": "policy_off"}

    root = root.resolve()
    state = _coordinator_state(root)
    now = time.monotonic()
    debounce = _debounce_seconds(config)
    requested_paths = set(file_paths or set())

    with state.lock:
        if state.running:
            state.pending = True
            state.pending_file_paths.update(requested_paths)
            return {"embedding_triggered": False, "embedding_schedule_reason": "coalesced_running"}

        if _structural_index_running(root, config):
            state.last_result = "deferred"
            state.last_reason = "structural_index_lock"
            return {
                "embedding_triggered": False,
                "embedding_schedule_reason": "deferred_structural_lock",
            }

        if state.last_trigger_monotonic is not None and debounce > 0:
            elapsed = now - state.last_trigger_monotonic
            if elapsed < debounce:
                return {
                    "embedding_triggered": False,
                    "embedding_schedule_reason": "debounced",
                    "embedding_debounce_remaining_s": round(debounce - elapsed, 1),
                }

        state.running = True
        state.pending = False
        state.pending_file_paths = set()
        state.last_trigger_monotonic = now
        state.last_start_monotonic = now
        state.last_result = "scheduled"
        state.last_error = None
        state.last_reason = reason

    thread = threading.Thread(
        target=_embedding_worker,
        args=(root, config, reason, requested_paths or None),
        daemon=True,
        name="agentscaffold-embedding-refresh",
    )
    thread.start()
    return {"embedding_triggered": True, "embedding_schedule_reason": "scheduled"}


def _embedding_worker(
    root: Path,
    config: ScaffoldConfig,
    reason: str,
    file_paths: set[str] | None,
) -> None:
    """Run background incremental embedding refresh and update scheduler state."""
    from agentscaffold.graph import index

    state = _coordinator_state(root)

    while True:
        start = time.monotonic()
        with state.lock:
            state.last_result = "running"
            state.last_error = None
            state.last_start_monotonic = start
            state.last_reason = reason

        try:
            # ``index(... incremental=True, embeddings=True)`` uses Plan 231's
            # scoped embedding path when structure changed; when nothing changed
            # it performs a content-hash reconcile for missing/stale embeddings.
            _ = file_paths  # reserved for a future direct scoped embed request API
            index(path=root, config=config, incremental=True, embeddings=True, audit=False)
            with state.lock:
                state.last_result = "idle"
                state.last_end_monotonic = time.monotonic()
                state.running = False
                rerun = state.pending
                pending_paths = set(state.pending_file_paths)
                state.pending = False
                state.pending_file_paths = set()
                if rerun:
                    state.running = True
                    state.last_trigger_monotonic = time.monotonic()
            if not rerun:
                return
            file_paths = pending_paths or None
        except Exception as exc:  # pragma: no cover - defensive fallback
            with state.lock:
                state.last_result = "failed"
                state.last_error = str(exc)
                state.last_end_monotonic = time.monotonic()
                state.running = False
                state.pending = False
                state.pending_file_paths = set()
            return


def _reset_for_tests() -> None:
    """Clear module-level scheduler state for isolated unit tests."""
    with _STATE_LOCK:
        _COORDINATOR.clear()
