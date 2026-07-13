"""Cross-process graph coordination helpers.

DuckDB allows only one process to hold the write-capable database lock. The
Cursor freshness hook, index pipeline, and MCP lifecycle writes can otherwise
race each other and surface transient ``graph_locked`` failures to agents. This
module provides a small filesystem lock that coordinates those AgentScaffold
writers before they contend on DuckDB itself.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_GRAPH_WRITE_LOCK_TIMEOUT_SECONDS = 8.0
DEFAULT_GRAPH_WRITE_LOCK_POLL_SECONDS = 0.2
DEFAULT_GRAPH_WRITE_LOCK_STALE_SECONDS = 600.0
GRAPH_WRITE_LOCK_NAME = "graph.write.lock"


def graph_write_lock_path(db_path: Path | str) -> Path | None:
    """Return the filesystem lock path for a graph database.

    In-memory graphs do not need cross-process coordination and return ``None``.
    """
    p = Path(db_path)
    if str(p) == ":memory:":
        return None
    return p.parent / GRAPH_WRITE_LOCK_NAME


def wait_for_graph_write_lock_clear(
    db_path: Path | str,
    *,
    timeout: float = DEFAULT_GRAPH_WRITE_LOCK_TIMEOUT_SECONDS,
    poll: float = DEFAULT_GRAPH_WRITE_LOCK_POLL_SECONDS,
    stale_after: float = DEFAULT_GRAPH_WRITE_LOCK_STALE_SECONDS,
) -> bool:
    """Wait until no AgentScaffold graph write lock is present.

    Returns ``True`` when the path is clear, ``False`` when the bounded wait
    expires. Stale lock directories are removed conservatively by mtime.
    """
    lock_path = graph_write_lock_path(db_path)
    if lock_path is None:
        return True

    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        _reap_stale_lock(lock_path, stale_after=stale_after)
        if not lock_path.exists():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0.0, poll))


def graph_write_lock_held(
    db_path: Path | str,
    *,
    stale_after: float = DEFAULT_GRAPH_WRITE_LOCK_STALE_SECONDS,
) -> bool:
    """Return True if an AgentScaffold graph write lock is currently held.

    Used by read-preferring open paths (Plan 244) to label responses without
    blocking on the exclusive writer.
    """
    lock_path = graph_write_lock_path(db_path)
    if lock_path is None:
        return False
    _reap_stale_lock(lock_path, stale_after=stale_after)
    return lock_path.exists()


@contextmanager
def graph_write_lock(
    db_path: Path | str,
    *,
    purpose: str,
    timeout: float = DEFAULT_GRAPH_WRITE_LOCK_TIMEOUT_SECONDS,
    poll: float = DEFAULT_GRAPH_WRITE_LOCK_POLL_SECONDS,
    stale_after: float = DEFAULT_GRAPH_WRITE_LOCK_STALE_SECONDS,
) -> Iterator[Path | None]:
    """Acquire the shared AgentScaffold graph write lock.

    The lock is a directory so acquisition is atomic across processes on common
    local filesystems. A small ``owner.json`` file is best-effort diagnostic
    metadata only; lock ownership is the directory itself.
    """
    lock_path = graph_write_lock_path(db_path)
    if lock_path is None:
        yield None
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout)
    acquired = False
    while not acquired:
        _reap_stale_lock(lock_path, stale_after=stale_after)
        try:
            lock_path.mkdir()
            acquired = True
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for graph write lock at {lock_path}")
            time.sleep(max(0.0, poll))

    try:
        _write_owner(lock_path, purpose)
        yield lock_path
    finally:
        try:
            owner = lock_path / "owner.json"
            if owner.exists():
                owner.unlink()
            lock_path.rmdir()
        except OSError:
            # Best effort: the next waiter will reap stale locks by mtime.
            pass


def _write_owner(lock_path: Path, purpose: str) -> None:
    payload = {
        "pid": os.getpid(),
        "purpose": purpose,
        "created_at": time.time(),
    }
    try:
        (lock_path / "owner.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def _reap_stale_lock(lock_path: Path, *, stale_after: float) -> None:
    if not lock_path.exists():
        return
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return
    if age <= stale_after:
        return
    try:
        owner = lock_path / "owner.json"
        if owner.exists():
            owner.unlink()
        lock_path.rmdir()
    except OSError:
        pass
