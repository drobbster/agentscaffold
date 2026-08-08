"""Cross-process graph coordination helpers.

DuckDB allows only one process to hold the write-capable database lock. The
Cursor freshness hook, index pipeline, and MCP lifecycle writes can otherwise
race each other and surface transient ``graph_locked`` failures to agents. This
module provides a small filesystem lock that coordinates those AgentScaffold
writers before they contend on DuckDB itself.

Abandoned locks (holder crashed without cleanup) are reaped by reading the
``pid`` recorded in ``owner.json`` when present (Plan 254). That probe is
same-host by construction -- the lock lives beside the database -- and does not
replace the DuckDB-open liveness check in :mod:`agentscaffold.graph.liveness`,
which rejects pid-based probes for cross-host migration safety. Pid reuse is
possible; the mtime fallback remains for missing metadata and that rare case.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
    expires. Abandoned locks are removed when their recorded owner pid is dead;
    otherwise age against *stale_after* (mtime) is the fallback.
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
    local filesystems. ``owner.json`` records the holding pid for abandonment
    detection; lock ownership is still the directory itself.
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
                raise TimeoutError(lock_timeout_message(lock_path)) from None
            time.sleep(max(0.0, poll))

    try:
        if not _write_owner(lock_path, purpose):
            _release_lock_dir(lock_path)
            raise OSError(
                f"Could not write owner metadata for graph write lock at {lock_path}; "
                "released the anonymous lock."
            )
        yield lock_path
    finally:
        _release_lock_dir(lock_path)


def lock_timeout_message(lock_path: Path) -> str:
    """Build a timeout / wait-failed message that does not claim a dead owner lives."""
    owner = _read_owner(lock_path)
    parts = [f"Timed out waiting for graph write lock at {lock_path}."]
    if owner:
        pid = owner.get("pid")
        purpose = owner.get("purpose")
        alive = _pid_is_alive(int(pid)) if isinstance(pid, int) else None
        detail = []
        if purpose:
            detail.append(f"purpose={purpose}")
        if isinstance(pid, int):
            detail.append(f"pid={pid}")
        if alive is True:
            detail.append("owner appears alive")
        elif alive is False:
            detail.append("owner pid is dead but the lock could not be cleared")
        else:
            detail.append("owner liveness unknown")
        parts.append("(" + ", ".join(detail) + ").")
    else:
        parts.append("No owner metadata was present.")
    parts.append(f"If no AgentScaffold process holds the graph, remove `{lock_path}` and retry.")
    return " ".join(parts)


def open_graph_lock_message(db_path: Path | str) -> str:
    """Message for :class:`GraphLockError` when the write-lock wait expires."""
    lock_path = graph_write_lock_path(db_path)
    if lock_path is None:
        return f"Could not open the knowledge graph at {db_path}: write lock wait failed."
    owner = _read_owner(lock_path)
    parts = [f"Could not open the knowledge graph at {db_path}."]
    if lock_path.exists():
        parts.append(f"Write lock still present at {lock_path}.")
        if owner:
            pid = owner.get("pid")
            purpose = owner.get("purpose")
            alive = _pid_is_alive(int(pid)) if isinstance(pid, int) else None
            detail = []
            if purpose:
                detail.append(f"purpose={purpose}")
            if isinstance(pid, int):
                detail.append(f"pid={pid}")
            if alive is True:
                detail.append("owner appears alive")
            elif alive is False:
                detail.append("owner pid is dead but the lock could not be cleared")
            else:
                detail.append("owner liveness unknown")
            parts.append("(" + ", ".join(detail) + ").")
        parts.append(
            f"If no AgentScaffold process holds the graph, remove `{lock_path}` and retry."
        )
    else:
        parts.append("The write-lock wait expired; retry shortly.")
    return " ".join(parts)


def _pid_is_alive(pid: int) -> bool | None:
    """Return whether *pid* appears alive on this host.

    ``True`` / ``False`` when the platform can answer; ``None`` when it cannot
    (caller should fall through to the mtime gate). On POSIX, ``PermissionError``
    from ``os.kill(pid, 0)`` means the process exists but the checker lacks
    signal permission -- treat that as alive, never as dead.
    """
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _write_owner(lock_path: Path, purpose: str) -> bool:
    payload = {
        "pid": os.getpid(),
        "purpose": purpose,
        "created_at": time.time(),
    }
    try:
        (lock_path / "owner.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return True
    except OSError:
        logger.warning("Could not write graph write-lock owner metadata at %s", lock_path)
        return False


def _read_owner(lock_path: Path) -> dict[str, Any] | None:
    owner_path = lock_path / "owner.json"
    try:
        if not owner_path.is_file():
            return None
        data = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def _release_lock_dir(lock_path: Path) -> None:
    try:
        owner = lock_path / "owner.json"
        if owner.exists():
            owner.unlink()
        if lock_path.exists():
            lock_path.rmdir()
    except OSError:
        # Best effort: the next waiter will reap stale locks.
        pass


def _reap_stale_lock(lock_path: Path, *, stale_after: float) -> None:
    if not lock_path.exists():
        return

    owner = _read_owner(lock_path)
    if owner is not None and isinstance(owner.get("pid"), int):
        alive = _pid_is_alive(int(owner["pid"]))
        if alive is False:
            logger.warning(
                "Reaping abandoned graph write lock at %s (dead_owner pid=%s purpose=%s)",
                lock_path,
                owner.get("pid"),
                owner.get("purpose"),
            )
            _release_lock_dir(lock_path)
            return
        # alive True or None: do not reap on pid alone; fall through to mtime
        # (covers long-lived holders and the rare pid-reuse tail).

    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return
    if age <= stale_after:
        return
    logger.warning(
        "Reaping stale graph write lock at %s (mtime_expired age=%.0fs)",
        lock_path,
        age,
    )
    _release_lock_dir(lock_path)
