"""Freshness oracle and async refresh coordinator for MCP tools."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentscaffold.config import ScaffoldConfig

_GIT_TIMEOUT_S = 2.0
_WATERMARK_FILE = "freshness_watermark.json"

# Tools that can trigger background refresh scheduling.
ELIGIBLE_REFRESH_TOOLS = {
    "scaffold_prepare_review",
    "scaffold_prepare_implementation",
    "scaffold_compare_plans",
    "scaffold_staleness_check",
    "scaffold_prepare_rewrite",
    "scaffold_prepare_retro",
    "scaffold_orient",
    "scaffold_next_action",
    "scaffold_diff_plan_vs_code",
    "scaffold_why_empty",
}


@dataclass
class _CoordinatorState:
    lock: threading.Lock
    running: bool = False
    pending: bool = False
    last_trigger_monotonic: float | None = None
    last_start_monotonic: float | None = None
    last_end_monotonic: float | None = None
    last_error: str | None = None
    last_result: str = "idle"


_STATE_LOCK = threading.Lock()
_COORDINATOR: dict[str, _CoordinatorState] = {}


def _workspace_key(root: Path) -> str:
    return str(root.resolve())


def _coordinator_state(root: Path) -> _CoordinatorState:
    key = _workspace_key(root)
    with _STATE_LOCK:
        state = _COORDINATOR.get(key)
        if state is None:
            state = _CoordinatorState(lock=threading.Lock())
            _COORDINATOR[key] = state
        return state


def _db_path(root: Path, config: ScaffoldConfig) -> Path:
    p = Path(config.graph.db_path)
    if not p.is_absolute():
        p = root / p
    return p


def _watermark_path(root: Path, config: ScaffoldConfig) -> Path:
    db = _db_path(root, config)
    return db.parent / _WATERMARK_FILE


def _run_git(root: Path, args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except Exception:
        return 2, ""


def _current_git_signals(root: Path) -> dict[str, Any]:
    code_head, out_head = _run_git(root, ["rev-parse", "HEAD"])
    if code_head != 0 or not out_head:
        return {"ok": False, "reason": "git_unavailable"}

    idx_path = root / ".git" / "index"
    index_mtime_ns = idx_path.stat().st_mtime_ns if idx_path.is_file() else None

    code_dirty, _ = _run_git(root, ["diff", "--quiet"])
    code_cached, _ = _run_git(root, ["diff", "--cached", "--quiet"])

    dirty_worktree = code_dirty == 1
    dirty_index = code_cached == 1

    return {
        "ok": True,
        "head_sha": out_head,
        "index_mtime_ns": index_mtime_ns,
        "dirty_worktree": dirty_worktree,
        "dirty_index": dirty_index,
    }


def _load_watermark(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
        if isinstance(raw, dict):
            return raw
    except Exception:
        return None
    return None


def write_watermark(root: Path, config: ScaffoldConfig) -> None:
    """Persist freshness watermark after successful async refresh."""
    signals = _current_git_signals(root)
    if not signals.get("ok"):
        return
    payload = {
        "head_sha": signals.get("head_sha"),
        "index_mtime_ns": signals.get("index_mtime_ns"),
        "dirty_worktree": signals.get("dirty_worktree"),
        "dirty_index": signals.get("dirty_index"),
        "updated_at": time.time(),
    }
    p = _watermark_path(root, config)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2))


def evaluate_freshness(root: Path, config: ScaffoldConfig) -> dict[str, Any]:
    """Evaluate graph freshness using cheap git signals + persisted watermark."""
    t0 = time.perf_counter()
    state = _coordinator_state(root)
    wm = _load_watermark(_watermark_path(root, config))
    signals = _current_git_signals(root)

    if state.running:
        status = "refreshing"
        reason = "refresh_in_progress"
    elif not signals.get("ok"):
        status = "unknown"
        reason = str(signals.get("reason", "signal_unavailable"))
    elif wm is None:
        status = "unknown"
        reason = "missing_watermark"
    else:
        changed = (
            wm.get("head_sha") != signals.get("head_sha")
            or wm.get("index_mtime_ns") != signals.get("index_mtime_ns")
            or wm.get("dirty_worktree") != signals.get("dirty_worktree")
            or wm.get("dirty_index") != signals.get("dirty_index")
        )
        if changed:
            status = "stale"
            reason = "repo_signals_changed_since_last_refresh"
        else:
            status = "fresh"
            reason = "signals_match_watermark"

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "freshness_status": status,
        "freshness_reason": reason,
        "oracle_latency_ms": round(elapsed_ms, 2),
    }


def refresh_runtime_state(root: Path, config: ScaffoldConfig) -> dict[str, Any]:
    """Return coordinator runtime state for response metadata."""
    state = _coordinator_state(root)
    now = time.monotonic()
    debounce = max(1, int(config.freshness.debounce_seconds))
    remaining = 0.0
    if state.last_trigger_monotonic is not None:
        remaining = max(0.0, debounce - (now - state.last_trigger_monotonic))
    refresh_state = "running" if state.running else state.last_result
    return {
        "refresh_state": refresh_state,
        "refresh_debounce_remaining_s": round(remaining, 1),
        "refresh_last_error": state.last_error,
    }


def maybe_schedule_async_refresh(
    root: Path,
    config: ScaffoldConfig,
    *,
    tool_name: str,
    reason: str,
) -> dict[str, Any]:
    """Schedule background incremental refresh with debounce + single-flight lock."""
    if not config.freshness.async_enabled:
        return {"refresh_triggered": False, "refresh_schedule_reason": "feature_disabled"}
    if tool_name not in ELIGIBLE_REFRESH_TOOLS:
        return {"refresh_triggered": False, "refresh_schedule_reason": "tool_not_eligible"}

    state = _coordinator_state(root)
    now = time.monotonic()
    debounce = max(1, int(config.freshness.debounce_seconds))

    with state.lock:
        if state.running:
            if config.freshness.background_queue_enabled:
                state.pending = True
                return {"refresh_triggered": False, "refresh_schedule_reason": "coalesced_running"}
            return {"refresh_triggered": False, "refresh_schedule_reason": "running_no_queue"}

        if state.last_trigger_monotonic is not None:
            elapsed = now - state.last_trigger_monotonic
            if elapsed < debounce:
                return {
                    "refresh_triggered": False,
                    "refresh_schedule_reason": "debounced",
                    "refresh_debounce_remaining_s": round(debounce - elapsed, 1),
                }

        state.running = True
        state.pending = False
        state.last_trigger_monotonic = now
        state.last_start_monotonic = now
        state.last_result = "scheduled"
        state.last_error = None

    thread = threading.Thread(
        target=_refresh_worker,
        args=(root.resolve(), config, reason),
        daemon=True,
        name="agentscaffold-freshness-refresh",
    )
    thread.start()
    return {"refresh_triggered": True, "refresh_schedule_reason": "scheduled"}


def _refresh_worker(root: Path, config: ScaffoldConfig, reason: str) -> None:
    """Run background incremental refresh and update coordinator state."""
    from agentscaffold.graph import index

    state = _coordinator_state(root)

    while True:
        start = time.monotonic()
        with state.lock:
            state.last_result = "running"
            state.last_error = None
            state.last_start_monotonic = start

        try:
            _ = reason  # reserved for future telemetry routing context
            # quiet=True: this runs inside the MCP stdio process; Rich progress
            # on stdout would break Cursor's JSON-RPC transport (Plan 242).
            index(
                path=root,
                config=config,
                incremental=True,
                embeddings=False,
                audit=False,
                quiet=True,
            )
            write_watermark(root, config)
            with state.lock:
                state.last_result = "idle"
                state.last_end_monotonic = time.monotonic()
                state.running = False
                rerun = state.pending and config.freshness.background_queue_enabled
                state.pending = False
                if rerun:
                    state.running = True
                    state.last_trigger_monotonic = time.monotonic()
            if not rerun:
                return
        except Exception as exc:  # pragma: no cover - defensive fallback
            with state.lock:
                state.last_result = "failed"
                state.last_error = str(exc)
                state.last_end_monotonic = time.monotonic()
                state.running = False
                state.pending = False
            return
