"""Detect whether a graph database is in use, before migrating it (Plan 249, A9).

Threat model Vector 5 requires that relocation never race a live process: two live
databases, or an old one still readable after the move, is the failure mode. This
module supplies the detection that ``workspace migrate-state`` (Step B4) refuses on.

The mechanism was chosen by measurement rather than design, and the measurement is
what makes it this small. DuckDB locks the database file such that:

- while any process holds it **read/write**, every other process is locked out
  entirely, reads included;
- while any process holds it **read-only**, another read-only open still succeeds,
  but a read/write open fails.

An attempted read/write open is therefore a complete cross-process liveness probe.
It fails if anyone else holds the database at all -- an indexer mid-write, or an
idle MCP server holding a read-preferring handle (Plan 244). That second case is
the one worth having: such a server is not writing anything, so a "is anyone
writing?" check would wave the migration through, and on POSIX the old file would
unlink while that process kept its descriptor and went on serving content from a
database nobody can see any more. Which is exactly what Vector 5 describes.

The alternatives were all worse. A heartbeat or pid table adds state that goes
stale and has to be reaped, and pids are meaningless across containers and wrong
after reuse. ``lsof`` is not portable. The file lock is already there, maintained
by DuckDB, and cannot disagree with reality because it *is* the thing that would
block the migration.

**The one blind spot is deliberate and handled.** The lock is cross-process, so a
handle held by the calling process does not trip it -- a second open inside one
process simply succeeds. That case is real (the CLI running the migration may hold
a pooled handle), so the pool is consulted directly rather than inferred.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DatabaseInUseError(RuntimeError):
    """Raised when a migration would race a process holding the source database."""


@dataclass(frozen=True)
class LivenessReport:
    """Whether a database is held, and what to tell the user if it is."""

    in_use: bool
    #: Human-readable cause, empty when free. Distinguishes an index in flight
    #: from a plain open handle, because the two imply different waits.
    reason: str = ""
    #: What the user should do about it, empty when free.
    remediation: str = ""


def probe_database_in_use(
    db_path: Path | str,
    *,
    pool: Any | None = None,
    pool_key: str | None = None,
) -> LivenessReport:
    """Report whether *db_path* is held by any process, including this one.

    Args:
        db_path: The graph database about to be migrated.
        pool: Optional :class:`~agentscaffold.mcp.pool.GraphHandlePool` to check
            for a handle held by *this* process, which the file lock cannot see.
        pool_key: Workspace key to look for in *pool*.

    Never raises for an absent or unreadable database: nothing to race means
    nothing to refuse. Use :func:`require_database_idle` to turn a positive
    report into a refusal.
    """
    path = Path(db_path)

    if pool is not None and pool_key is not None and _pool_holds(pool, pool_key):
        return LivenessReport(
            in_use=True,
            reason=(
                f"This process still has {path} open through the graph handle pool "
                f"(workspace {pool_key!r})."
            ),
            remediation=(
                "Close the pooled handle before migrating. If this is the MCP server, "
                "run the migration from a separate `scaffold` invocation instead."
            ),
        )

    if not path.is_file():
        return LivenessReport(in_use=False)

    # A held write lock means an index run is in flight. Reported separately from
    # a bare open handle because it implies a different wait: an index finishes on
    # its own, whereas an idle server holds its handle indefinitely.
    lock_reason = _write_lock_reason(path)
    if lock_reason:
        return LivenessReport(
            in_use=True,
            reason=lock_reason,
            remediation="Wait for the index to finish, then retry.",
        )

    held_by = _exclusive_open_fails(path)
    if held_by is not None:
        return LivenessReport(
            in_use=True,
            reason=f"Another process currently holds {path} open ({held_by}).",
            remediation=(
                "Close or stop anything using this graph -- typically an MCP server in "
                "your editor, or a `scaffold index` run -- then retry."
            ),
        )

    return LivenessReport(in_use=False)


def require_database_idle(
    db_path: Path | str,
    *,
    pool: Any | None = None,
    pool_key: str | None = None,
) -> None:
    """Raise :class:`DatabaseInUseError` unless *db_path* is free.

    The refusal names the database and what to close, because a migration that
    refuses without saying why is a dead end the user will route around.
    """
    report = probe_database_in_use(db_path, pool=pool, pool_key=pool_key)
    if report.in_use:
        raise DatabaseInUseError(f"{report.reason} {report.remediation}".strip())


def _pool_holds(pool: Any, key: str) -> bool:
    """Return whether *pool* has an open handle for *key*.

    Deliberately not ``refcount(key) > 0``. The pool keeps handles open after a
    borrow is returned -- that is what makes it a pool -- so refcount falls to
    zero while the database stays held. Asking about outstanding borrows would
    report "free" for a database this process cannot release.
    """
    holds = getattr(pool, "holds", None)
    if callable(holds):
        try:
            return bool(holds(key))
        except Exception:  # noqa: BLE001 - liveness must not break on a pool quirk
            logger.debug("Pool holds() check failed for %s", key, exc_info=True)
    return False


def _write_lock_reason(path: Path) -> str:
    """Return a description if the AgentScaffold write lock is held, else ''."""
    try:
        from agentscaffold.graph.locks import graph_write_lock_held

        if graph_write_lock_held(path):
            return f"An AgentScaffold index run holds the write lock on {path}."
    except Exception:  # noqa: BLE001 - absence of the lock is not evidence of idleness
        logger.debug("Write-lock check failed for %s", path, exc_info=True)
    return ""


def _exclusive_open_fails(path: Path) -> str | None:
    """Attempt a read/write open; return a description if it is refused.

    The connection is closed immediately on success, so the probe never becomes
    the thing that blocks the migration it was called to protect.
    """
    try:
        import duckdb
    except ImportError:
        # Without duckdb we cannot probe. Report free rather than block: the
        # caller cannot be running a graph in this environment either.
        return None

    try:
        con = duckdb.connect(str(path))
    except Exception as exc:  # noqa: BLE001 - duckdb raises IOException for a held lock
        text = str(exc)
        if "lock" in text.lower():
            return "file lock held"
        # Some other failure -- corrupt file, bad permissions, version skew.
        # Fail closed: we could not establish that it is safe to migrate.
        return f"could not be opened for verification: {text.splitlines()[0][:120]}"

    try:
        con.close()
    except Exception:  # noqa: BLE001 - nothing actionable if closing a probe fails
        logger.debug("Closing liveness probe connection failed for %s", path, exc_info=True)
    return None
