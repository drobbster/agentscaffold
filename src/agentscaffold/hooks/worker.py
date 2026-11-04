"""Background work behind the edit and commit hooks (Plan 277).

The router (:mod:`agentscaffold.hooks.router`) answers the editor in a few tens
of milliseconds and starts ``scaffold hook-worker`` detached. The worker does
the slow part: it loads the project's configuration, finds the state directory
the indexer writes to (``resolve_db_path(...).parent``, which for a registered
workspace is under the user state directory, not the project's ``.scaffold/``),
and runs the incremental index under a single-flight lock.

Single-flight and coalescing replace the shell hook's: at most one index runs
per database; an edit that arrives while it runs records a request, and the
running worker indexes once more afterwards so the last edit of a burst is
never left out. Lock age is read with ``os.stat`` so macOS and Linux agree.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentscaffold.graph.locks import GRAPH_WRITE_LOCK_NAME
from agentscaffold.hooks.router import HOOK_LAST_RUN_FILE, scaffold_command

#: A lock older than this was left by a killed worker.
LOCK_STALE_SECONDS = 600.0

INDEX_LOCK = "index.lock"
INDEX_REQUEST = "index.request"
INDEX_LAST_SUCCESS = "index.last_success"
INDEX_LOG = "index-hook.log"

EMBED_LOCK = "embedding.lock"
EMBED_LAST_SUCCESS = "embedding.last_success"
EMBED_LOG = "embedding-hook.log"

Runner = Callable[..., Any]


def project_state(project_root: Path) -> tuple[Path, Any]:
    """Return ``(state_dir, config)`` for *project_root*; config is None without one."""
    from agentscaffold.config import load_config
    from agentscaffold.paths import resolve_db_path

    config_path = project_root / "scaffold.yaml"
    config = load_config(config_path) if config_path.is_file() else None
    return resolve_db_path(config, start=project_root).parent, config


def record_last_run(state_dir: Path, event: str, *, now: float | None = None) -> None:
    """Note that a hook fired. Event name and time only: payloads are never logged."""
    payload = {"event": event, "at": time.time() if now is None else now}
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / HOOK_LAST_RUN_FILE).write_text(json.dumps(payload) + "\n", encoding="utf-8")
    except OSError:
        pass


def read_last_run(state_dir: Path) -> dict[str, Any] | None:
    """Return the last recorded hook run in *state_dir*, or None."""
    try:
        data = json.loads((state_dir / HOOK_LAST_RUN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def reap_stale_lock(lock: Path, *, now: float, stale_after: float = LOCK_STALE_SECONDS) -> bool:
    """Remove *lock* when its ``os.stat`` mtime is older than *stale_after*."""
    try:
        age = now - lock.stat().st_mtime
    except OSError:
        return False
    if age <= stale_after:
        return False
    try:
        (lock / "owner.json").unlink(missing_ok=True)
        lock.rmdir()
    except OSError:
        return False
    return True


def _interval(config: Any, field: str) -> int:
    """A ``graph.*_min_interval_seconds`` value; 0 (no throttle) without a config."""
    return max(0, int(getattr(getattr(config, "graph", None), field, 0) or 0))


def _read_float(path: Path) -> float:
    try:
        return float(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0.0


def wait_for_graph_writer(
    state_dir: Path,
    *,
    timeout: float = LOCK_STALE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Wait while another process (the MCP server's refresh) holds the graph write lock.

    Returns False when the lock is still held after *timeout*.
    """
    lock = state_dir / GRAPH_WRITE_LOCK_NAME
    deadline = clock() + timeout
    while lock.exists():
        if clock() >= deadline:
            return False
        sleep(1.0)
    return True


def _run_scaffold(args: list[str], project_root: Path, log: Path, run: Runner) -> None:
    command = scaffold_command()
    if command is None:
        return
    with log.open("a", encoding="utf-8") as handle:
        run(
            [*command, *args],
            cwd=str(project_root),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )


def run_index_worker(
    project_root: Path,
    *,
    event: str = "",
    run: Runner = subprocess.run,
    clock: Callable[[], float] = time.time,
) -> str:
    """Run (or coalesce into) an incremental index for *project_root*.

    Returns what happened: ``throttled``, ``busy``, or ``indexed``.
    """
    state_dir, config = project_state(project_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    now = clock()
    record_last_run(state_dir, event or "index", now=now)

    lock = state_dir / INDEX_LOCK
    request = state_dir / INDEX_REQUEST
    last_success = state_dir / INDEX_LAST_SUCCESS
    min_interval = _interval(config, "incremental_min_interval_seconds")

    if min_interval > 0 and not lock.is_dir() and last_success.is_file():
        if now - _read_float(last_success) < min_interval:
            return "throttled"

    request.write_text(f"{now}\n", encoding="utf-8")
    reap_stale_lock(lock, now=now)
    try:
        lock.mkdir()
    except FileExistsError:
        return "busy"

    try:
        while True:
            wait_for_graph_writer(state_dir)
            started = clock()
            _run_scaffold(["index", "--incremental"], project_root, state_dir / INDEX_LOG, run)
            last_success.write_text(f"{clock()}\n", encoding="utf-8")
            if _read_float(request) <= started:
                break
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass
    return "indexed"


def run_embed_worker(
    project_root: Path,
    *,
    event: str = "",
    run: Runner = subprocess.run,
    clock: Callable[[], float] = time.time,
) -> str:
    """Refresh embeddings after a commit unless a structural index is running.

    Returns ``deferred``, ``throttled``, ``busy``, or ``embedded``.
    """
    state_dir, config = project_state(project_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    now = clock()
    log = state_dir / EMBED_LOG

    if (state_dir / INDEX_LOCK).is_dir():
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{int(now)} deferred: structural index lock active\n")
        return "deferred"

    last_success = state_dir / EMBED_LAST_SUCCESS
    min_interval = _interval(config, "embedding_min_interval_seconds")
    if min_interval > 0 and last_success.is_file():
        if now - _read_float(last_success) < min_interval:
            return "throttled"

    lock = state_dir / EMBED_LOCK
    reap_stale_lock(lock, now=now)
    try:
        lock.mkdir()
    except FileExistsError:
        return "busy"
    try:
        _run_scaffold(["index", "--incremental", "--embeddings"], project_root, log, run)
        last_success.write_text(f"{clock()}\n", encoding="utf-8")
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass
    return "embedded"
