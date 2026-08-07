"""Tests for the multi-workspace graph handle pool (Plan 249, Step A5/A6).

The Step A0 spike validated that one process can hold DuckDB handles for several
workspaces safely, and produced two mandatory design corrections that these tests
exist to hold in place:

The Plan 235 filesystem lock is a ``mkdir`` lock. It is neither thread-aware nor
reentrant, so two threads in one process contending for the same workspace get a
``TimeoutError`` instead of queueing. An in-process per-workspace mutex has to sit
above it, leaving the filesystem lock to mediate across processes only.

Eviction must respect outstanding borrows. The spike showed that a plain LRU
which closes on eviction breaks an in-flight reader with
``ConnectionException: Connection already closed!``, so handles are leased and
evictable only at refcount zero.

Handles are faked here. The point under test is the pool's lifecycle arithmetic,
not DuckDB.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agentscaffold.mcp.pool import GraphHandlePool


class FakeHandle:
    """Stands in for a graph backend, recording whether it was closed."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def pool() -> GraphHandlePool:
    """A pool with a small ceiling so eviction is easy to provoke."""
    return GraphHandlePool(max_handles=2, opener=FakeHandle)


# --------------------------------------------------------------------------
# Pooling and identity
# --------------------------------------------------------------------------


def test_same_workspace_reuses_one_handle(pool: GraphHandlePool) -> None:
    """Repeat borrows share a handle rather than reopening the database."""
    with pool.borrow("ws-a") as first:
        pass
    with pool.borrow("ws-a") as second:
        pass

    assert first is second
    assert not first.closed


def test_different_workspaces_get_different_handles(pool: GraphHandlePool) -> None:
    """Cross-workspace isolation: one handle per workspace, never shared."""
    with pool.borrow("ws-a") as a, pool.borrow("ws-b") as b:
        assert a is not b
        assert a.key == "ws-a"
        assert b.key == "ws-b"


# --------------------------------------------------------------------------
# Lease and refcount semantics
# --------------------------------------------------------------------------


def test_in_use_handle_survives_pressure_that_would_evict_it(
    pool: GraphHandlePool,
) -> None:
    """A borrowed handle is never closed underneath its reader.

    This is the spike's ConnectionException failure: a plain LRU that closes on
    eviction breaks an in-flight reader. The pool may exceed its ceiling rather
    than close a leased handle.
    """
    with pool.borrow("ws-a") as held:
        with pool.borrow("ws-b"):
            pass
        with pool.borrow("ws-c"):
            pass

        assert not held.closed, "evicted a handle that was still borrowed"

    assert not held.closed


def test_eviction_happens_once_the_lease_is_released(pool: GraphHandlePool) -> None:
    """Past the ceiling, an idle handle is closed -- but only when idle."""
    with pool.borrow("ws-a") as a:
        pass
    with pool.borrow("ws-b"):
        pass
    with pool.borrow("ws-c"):
        pass

    assert a.closed, "idle handle should be evicted once the ceiling is exceeded"


def test_nested_borrows_release_only_at_the_outermost_exit(
    pool: GraphHandlePool,
) -> None:
    """Refcounting, not a boolean: an inner release must not free the handle."""
    with pool.borrow("ws-a") as outer:
        with pool.borrow("ws-a") as inner:
            assert inner is outer
            assert pool.refcount("ws-a") == 2
        assert pool.refcount("ws-a") == 1
        assert not outer.closed

    assert pool.refcount("ws-a") == 0


def test_exception_inside_a_borrow_still_releases_the_lease(
    pool: GraphHandlePool,
) -> None:
    """A raising caller must not leak a lease and pin the handle forever."""
    with pytest.raises(RuntimeError):
        with pool.borrow("ws-a"):
            raise RuntimeError("boom")

    assert pool.refcount("ws-a") == 0


def test_concurrent_borrows_of_one_workspace_both_succeed(
    pool: GraphHandlePool,
) -> None:
    """Two threads reading the same workspace share the handle without error."""
    seen: list[FakeHandle] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        with pool.borrow("ws-a") as handle:
            barrier.wait(timeout=5)
            seen.append(handle)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(seen) == 2
    assert seen[0] is seen[1]
    assert pool.refcount("ws-a") == 0


def test_close_all_closes_every_pooled_handle(pool: GraphHandlePool) -> None:
    """Shutdown releases resources rather than relying on interpreter exit."""
    with pool.borrow("ws-a") as a:
        pass
    with pool.borrow("ws-b") as b:
        pass

    pool.close_all()

    assert a.closed and b.closed
    assert pool.size == 0


# --------------------------------------------------------------------------
# In-process write lock above the Plan 235 filesystem lock
# --------------------------------------------------------------------------


def test_same_process_threads_queue_instead_of_timing_out(
    pool: GraphHandlePool, tmp_path: Path
) -> None:
    """Two threads locking one workspace serialise rather than raising.

    Without the in-process mutex this is the spike's TimeoutError: the Plan 235
    mkdir lock is not thread-aware, so the second thread fails outright instead
    of waiting its turn.

    ``lock_timeout=0`` is what gives this test teeth. It leaves the filesystem
    lock no room to paper over the problem by retrying, so the test can only
    pass if the mutex serialised the two threads before either reached it.
    """
    db_path = tmp_path / "graph.duckdb"
    order: list[str] = []
    errors: list[BaseException] = []

    def worker(tag: str) -> None:
        try:
            with pool.write_lock("ws-a", db_path, timeout=5.0, lock_timeout=0.0):
                order.append(f"{tag}-enter")
                time.sleep(0.05)
                order.append(f"{tag}-exit")
        except BaseException as exc:  # noqa: BLE001 - surfaced via assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == [], f"contending threads raised instead of queueing: {errors}"
    assert len(order) == 4
    # Strict alternation would mean interleaving; each pair must be adjacent.
    assert order[0].endswith("-enter") and order[1].endswith("-exit")
    assert order[0].split("-")[0] == order[1].split("-")[0], "lock did not serialise"


def test_different_workspaces_do_not_contend(pool: GraphHandlePool, tmp_path: Path) -> None:
    """Cross-workspace writes proceed in parallel.

    DuckDB's single-writer constraint is per database file, which is what makes
    one server process viable for several workspaces at all.
    """
    a_db = tmp_path / "a" / "graph.duckdb"
    b_db = tmp_path / "b" / "graph.duckdb"
    a_db.parent.mkdir()
    b_db.parent.mkdir()

    acquired = threading.Event()
    released = threading.Event()
    errors: list[BaseException] = []

    def holder() -> None:
        try:
            with pool.write_lock("ws-a", a_db, timeout=5.0):
                acquired.set()
                released.wait(timeout=5)
        except BaseException as exc:  # noqa: BLE001 - surfaced via assertion below
            errors.append(exc)

    thread = threading.Thread(target=holder)
    thread.start()
    assert acquired.wait(timeout=5), "holder never acquired the lock"

    # Must not block on the unrelated workspace while ws-a is held.
    with pool.write_lock("ws-b", b_db, timeout=2.0):
        pass

    released.set()
    thread.join(timeout=5)
    assert errors == []


def test_write_lock_is_released_when_the_body_raises(pool: GraphHandlePool, tmp_path: Path) -> None:
    """A failure inside the critical section must not wedge the workspace."""
    db_path = tmp_path / "graph.duckdb"

    with pytest.raises(RuntimeError):
        with pool.write_lock("ws-a", db_path, timeout=5.0):
            raise RuntimeError("boom")

    # Re-acquiring proves the mutex and the filesystem lock were both released.
    with pool.write_lock("ws-a", db_path, timeout=2.0):
        pass
