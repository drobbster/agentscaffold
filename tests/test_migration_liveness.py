"""Tests for source-database liveness detection before migration (Plan 249, A9).

Written before the probe exists. It closes review finding ``rf::2a657859c475`` and
implements the outstanding control in threat model Vector 5: *detect a live process
holding the source database and refuse rather than racing it*.

The mechanism was chosen empirically rather than designed on paper, and the
measurement is worth restating because it is what makes the simple implementation
sufficient. DuckDB takes a lock on the database file with these properties:

- while any process holds the file **read/write**, every other process is locked
  out entirely, for reading as well as writing;
- while any process holds it **read-only**, another process can still open it
  read-only, but a read/write open fails.

So an attempted **read/write** open is a complete liveness probe: it fails if any
other process holds the database at all, whether that holder is an indexer writing
or an idle MCP server with a read-preferring handle (Plan 244). No heartbeat file,
no pid table, no ``lsof`` -- and nothing to go stale.

The one thing it does not see is a handle held by the *calling* process, because
the lock is cross-process: a second open inside one process succeeds. That case is
real, since the CLI doing the migration may itself have a pooled handle open, so it
is checked separately against the pool rather than assumed away.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.liveness import (  # noqa: E402
    DatabaseInUseError,
    probe_database_in_use,
    require_database_idle,
)


def _seed(db: Path) -> Path:
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.duckpgq_schema import init_schema

    db.parent.mkdir(parents=True, exist_ok=True)
    store = DuckPGQBackend(db)
    init_schema(store._conn)
    store.close()
    return db


_HOLDER = textwrap.dedent(
    """
    import sys, time
    import duckdb

    con = duckdb.connect(sys.argv[1], read_only=(sys.argv[2] == "ro"))
    print("HELD", flush=True)
    time.sleep(float(sys.argv[3]))
    con.close()
    """
)


def _hold(db: Path, script: Path, mode: str, seconds: float = 30.0):
    """Start a subprocess holding *db* and wait until it confirms it has it."""
    proc = subprocess.Popen(
        [sys.executable, str(script), str(db), mode, str(seconds)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline().strip()
    assert line == "HELD", f"holder failed to start: {line} {proc.stderr.read()[:400]}"
    return proc


@pytest.fixture()
def holder_script(tmp_path: Path) -> Path:
    script = tmp_path / "holder.py"
    script.write_text(_HOLDER)
    return script


# --------------------------------------------------------------------------
# The free case
# --------------------------------------------------------------------------


def test_an_unheld_database_reports_free(tmp_path):
    db = _seed(tmp_path / "graph.duckdb")

    report = probe_database_in_use(db)

    assert report.in_use is False


def test_probing_does_not_leave_the_database_held(tmp_path):
    """The probe must not become the thing that blocks the migration.

    It opens read/write to test the lock, so failing to close would make the
    very next check report the database busy -- with the probe itself as the
    culprit.
    """
    db = _seed(tmp_path / "graph.duckdb")

    assert probe_database_in_use(db).in_use is False
    assert probe_database_in_use(db).in_use is False

    require_database_idle(db)  # must not raise


def test_a_missing_database_is_not_in_use(tmp_path):
    """Nothing to race for a database that was never created."""
    report = probe_database_in_use(tmp_path / "absent.duckdb")

    assert report.in_use is False


# --------------------------------------------------------------------------
# The cases that must refuse
# --------------------------------------------------------------------------


def test_a_writer_in_another_process_is_detected(tmp_path, holder_script):
    db = _seed(tmp_path / "graph.duckdb")
    proc = _hold(db, holder_script, "rw")
    try:
        report = probe_database_in_use(db)

        assert report.in_use is True
        assert report.reason
        assert report.remediation
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_a_read_only_holder_in_another_process_is_also_detected(tmp_path, holder_script):
    """The case a naive "is anyone writing?" check would miss.

    An idle MCP server holds a read-preferring handle (Plan 244) and is not
    writing anything. Migrating out from under it is still wrong: on POSIX the
    old file unlinks while that process keeps its descriptor, so it goes on
    serving stale content from a database nobody can see any more. That is
    precisely the "divergent or orphaned state" Vector 5 describes.
    """
    db = _seed(tmp_path / "graph.duckdb")
    proc = _hold(db, holder_script, "ro")
    try:
        report = probe_database_in_use(db)

        assert report.in_use is True, "a read-only holder must still block migration"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_require_database_idle_raises_an_actionable_message(tmp_path, holder_script):
    db = _seed(tmp_path / "graph.duckdb")
    proc = _hold(db, holder_script, "rw")
    try:
        with pytest.raises(DatabaseInUseError) as excinfo:
            require_database_idle(db)

        message = str(excinfo.value)
        assert str(db) in message
        # Refusing without saying what to close is just a dead end.
        assert "close" in message.lower() or "stop" in message.lower()
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_the_database_is_usable_again_once_the_holder_exits(tmp_path, holder_script):
    """Refusal must be transient, not sticky.

    A probe that stayed "in use" after the holder left would make migration
    impossible to complete without a restart, and would train users to bypass it.
    """
    db = _seed(tmp_path / "graph.duckdb")
    proc = _hold(db, holder_script, "rw", seconds=0.5)
    assert probe_database_in_use(db).in_use is True
    proc.wait(timeout=20)

    assert probe_database_in_use(db).in_use is False


# --------------------------------------------------------------------------
# The blind spot: a handle held by this very process
# --------------------------------------------------------------------------


def test_a_handle_held_by_this_process_is_reported(tmp_path):
    """DuckDB's lock is cross-process, so our own handle does not trip it.

    A second open inside one process succeeds, which means the probe alone would
    cheerfully report "free" while this very process has the database open --
    exactly the situation when the CLI running the migration has a pooled handle.
    The pool is therefore consulted directly rather than inferred from the lock.
    """
    from agentscaffold.mcp.pool import GraphHandlePool

    db = _seed(tmp_path / "graph.duckdb")
    pool = GraphHandlePool(max_handles=2)

    def _open():
        from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

        return DuckPGQBackend(db)

    try:
        with pool.borrow("ws-1", _open):
            report = probe_database_in_use(db, pool=pool, pool_key="ws-1")
            assert report.in_use is True, "a handle held by this process must be reported"
            assert "process" in report.reason.lower()
    finally:
        pool.close_all()


def test_an_idle_pooled_handle_still_counts_as_in_use(tmp_path):
    """Leaving the ``with`` block returns the lease but does not close the handle.

    This is the subtle one. The pool keeps handles open after the borrow ends --
    that is the point of pooling -- so refcount drops to zero while the database
    stays firmly held. A liveness check keyed on outstanding borrows would report
    "free" for a database this process cannot actually release.
    """
    from agentscaffold.mcp.pool import GraphHandlePool

    db = _seed(tmp_path / "graph.duckdb")
    pool = GraphHandlePool(max_handles=2)

    def _open():
        from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

        return DuckPGQBackend(db)

    try:
        with pool.borrow("ws-1", _open):
            pass

        assert pool.refcount("ws-1") == 0, "precondition: the lease was returned"
        assert probe_database_in_use(db, pool=pool, pool_key="ws-1").in_use is True
    finally:
        pool.close_all()


def test_the_pool_check_is_scoped_to_the_database_being_migrated(tmp_path):
    """Holding some *other* workspace open must not block this migration."""
    from agentscaffold.mcp.pool import GraphHandlePool

    db = _seed(tmp_path / "graph.duckdb")
    other = _seed(tmp_path / "other" / "graph.duckdb")
    pool = GraphHandlePool(max_handles=2)

    def _open():
        from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

        return DuckPGQBackend(other)

    try:
        with pool.borrow("other-ws", _open):
            report = probe_database_in_use(db, pool=pool, pool_key="ws-1")
            assert report.in_use is False
    finally:
        pool.close_all()


# --------------------------------------------------------------------------
# Interaction with the AgentScaffold write lock
# --------------------------------------------------------------------------


def test_a_held_write_lock_is_reported_with_a_specific_reason(tmp_path):
    """An index in flight should say so, not just "busy".

    The AgentScaffold write lock is held across a whole index run, which is a
    long and recognisable operation. Naming it turns "try again" into "wait for
    the index to finish".
    """
    from agentscaffold.graph.locks import graph_write_lock

    db = _seed(tmp_path / "graph.duckdb")

    with graph_write_lock(db, purpose="index", timeout=5.0):
        report = probe_database_in_use(db)

        assert report.in_use is True
        assert "index" in report.reason.lower() or "lock" in report.reason.lower()
