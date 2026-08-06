"""Per-workspace graph handle pool for the single MCP server (Plan 249, Step A6).

One server process now serves every registered workspace, so it holds several
DuckDB connections at once. The Step A0 spike confirmed that is safe and turned
up two constraints that shape this module.

The Plan 235 write lock is a ``mkdir`` directory lock. It is atomic across
processes but knows nothing about threads and is not reentrant, so two threads in
one process contending for the same workspace get a ``TimeoutError`` rather than
queueing. :meth:`GraphHandlePool.write_lock` puts an in-process mutex above it,
leaving the filesystem lock to do only the job it is good at: mediating between
processes.

Handles are leased, not merely cached. A plain LRU that closes on eviction will
close a connection out from under an in-flight reader, which surfaces as
``ConnectionException: Connection already closed!``. Every handle carries a
refcount and is evictable only at zero; under pressure the pool would rather
exceed its ceiling than break a live reader.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MAX_HANDLES = 8


@dataclass
class _Entry:
    """A pooled handle and the number of borrows currently outstanding."""

    handle: Any
    refs: int = field(default=0)


class GraphHandlePool:
    """Leased, size-bounded pool of graph handles keyed by workspace.

    Thread-safe. The MCP server is long-lived and single-instance, so a pool
    instance is expected to live for the life of the process.
    """

    def __init__(
        self,
        max_handles: int = DEFAULT_MAX_HANDLES,
        opener: Callable[[str], Any] | None = None,
    ) -> None:
        """Create a pool.

        Args:
            max_handles: Soft ceiling on open handles. Soft because a leased
                handle is never closed to satisfy it.
            opener: Default factory called with the pool key when a handle is
                not already open. Callers that hold richer context (a resolved
                config, say) can instead pass a factory per borrow.
        """
        self._max_handles = max(1, max_handles)
        self._opener = opener
        # Guards _handles and _mutexes. Distinct from the per-workspace write
        # mutexes below, which are held across user code and must never be
        # confused with this short-lived bookkeeping lock.
        self._lock = threading.RLock()
        self._handles: OrderedDict[str, _Entry] = OrderedDict()
        self._mutexes: dict[str, threading.Lock] = {}

    # -- leasing ---------------------------------------------------------

    @contextmanager
    def borrow(self, key: str, factory: Callable[[], Any] | None = None) -> Iterator[Any]:
        """Lease the handle for *key*, opening it if needed.

        The handle is guaranteed not to be closed by the pool for the duration
        of the ``with`` block, including under eviction pressure.

        Args:
            key: Workspace pool key (see ``ResolvedProject.pool_key``).
            factory: Zero-arg callable to open the handle, overriding the
                pool-level opener.
        """
        with self._lock:
            entry = self._handles.get(key)
            if entry is None:
                entry = _Entry(handle=self._open(key, factory))
                self._handles[key] = entry
            entry.refs += 1
            self._handles.move_to_end(key)

        try:
            yield entry.handle
        finally:
            with self._lock:
                entry.refs -= 1
                self._evict()

    def refcount(self, key: str) -> int:
        """Number of outstanding borrows for *key*. Zero if not pooled."""
        with self._lock:
            entry = self._handles.get(key)
            return entry.refs if entry else 0

    def holds(self, key: str) -> bool:
        """Whether a handle for *key* is open, leased or not.

        Distinct from ``refcount(key) > 0``, and the distinction matters to
        anything asking "can this database be moved?". A returned lease drops the
        refcount to zero but leaves the handle open -- that is what makes this a
        pool -- so the database stays held. See ``graph/liveness.py``.
        """
        with self._lock:
            return key in self._handles

    @property
    def size(self) -> int:
        """Number of open handles, leased or idle."""
        with self._lock:
            return len(self._handles)

    def close_all(self) -> None:
        """Close every pooled handle, including leased ones.

        Shutdown only. Unlike eviction this ignores refcounts, so callers must
        be certain no tool call is in flight.
        """
        with self._lock:
            for entry in self._handles.values():
                _close(entry.handle)
            self._handles.clear()

    # -- write locking ---------------------------------------------------

    @contextmanager
    def write_lock(
        self,
        key: str,
        db_path: Path | str,
        *,
        timeout: float = 8.0,
        lock_timeout: float | None = None,
        purpose: str = "mcp",
    ) -> Iterator[None]:
        """Hold the write lock for *key* against threads and other processes.

        Acquires the in-process mutex first, then the Plan 235 filesystem lock.
        Ordering matters: taking the filesystem lock first would let sibling
        threads pile onto a lock that cannot queue them, which is the
        ``TimeoutError`` the spike hit.

        Args:
            timeout: How long to wait for the in-process mutex, which is where
                same-process contention now queues.
            lock_timeout: How long to wait for the filesystem lock. Defaults to
                *timeout*. Because the mutex has already serialised this
                process, any remaining wait is another process holding the lock.
        """
        from agentscaffold.graph.locks import graph_write_lock

        mutex = self._mutex_for(key)
        if not mutex.acquire(timeout=timeout):
            raise TimeoutError(
                f"Timed out waiting for the in-process write lock for workspace '{key}'."
            )
        try:
            fs_timeout = timeout if lock_timeout is None else lock_timeout
            with graph_write_lock(db_path, purpose=purpose, timeout=fs_timeout):
                yield
        finally:
            mutex.release()

    # -- internals -------------------------------------------------------

    def _open(self, key: str, factory: Callable[[], Any] | None) -> Any:
        if factory is not None:
            return factory()
        if self._opener is None:
            raise ValueError(
                f"No opener configured for the handle pool and none passed for '{key}'."
            )
        return self._opener(key)

    def _mutex_for(self, key: str) -> threading.Lock:
        with self._lock:
            mutex = self._mutexes.get(key)
            if mutex is None:
                mutex = threading.Lock()
                self._mutexes[key] = mutex
            return mutex

    def _evict(self) -> None:
        """Close idle handles until the ceiling is met, oldest first.

        Caller must hold ``self._lock``. Stops when only leased handles remain,
        deliberately leaving the pool over its ceiling rather than closing a
        connection a reader is still using.
        """
        while len(self._handles) > self._max_handles:
            victim = next((k for k, e in self._handles.items() if e.refs == 0), None)
            if victim is None:
                return
            _close(self._handles.pop(victim).handle)


def _close(handle: Any) -> None:
    """Close a handle, tolerating one that is already closed or has no close."""
    close = getattr(handle, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:  # noqa: BLE001 - shutdown must not mask the real error
        pass
