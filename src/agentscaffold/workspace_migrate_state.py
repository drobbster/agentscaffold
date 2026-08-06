"""Relocate graph state out of the source tree (Plan 249, Step B4).

Sibling of :mod:`agentscaffold.workspace_migrate`, which owns Plan 234's asset
layout migration. This one moves the graph database and the files that live
beside it from the in-tree ``.scaffold/`` directory to the platform state
directory keyed by workspace id.

**Copy, verify, then remove -- never move in place.** The graph is derived data,
so the worst case is a re-index, but Section 3 still forbids leaving two
divergent live databases behind. Every ordering here follows from that: nothing
is deleted that was not first confirmed to have arrived intact, a failed copy
cleans up after itself rather than leaving a plausible-looking partial file, and
the whole operation refuses to start while another process holds the source
(Step A9's liveness probe, threat model Vector 5).

Dry run is the default. ``--apply`` is the deliberate act.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Files that live beside the database and must travel with it. The freshness
#: watermark is the one that matters: left behind, a perfectly good migrated
#: graph looks stale and triggers a full re-index on first use.
_SIDECAR_NAMES = ("freshness.json", "graph_meta.json")

_HASH_CHUNK = 1024 * 1024


class StateMigrationError(RuntimeError):
    """Raised when a state migration cannot be completed safely."""


@dataclass
class StateMigrationResult:
    """What a migration did, or would do.

    *needed* is False both when there is nothing in the tree to move and when the
    move has already happened, because neither is an error and both should read
    the same to a caller deciding whether to act.
    """

    source: Path
    destination: Path
    needed: bool
    applied: bool = False
    reason: str = ""
    copied: list[Path] = field(default_factory=list)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path) -> None:
    """Copy *source* to *destination*, or raise leaving no partial file behind.

    Verification is a content hash rather than a size check: a truncated or
    partially flushed copy can match on size and still be unusable, and the cost
    of reading the file twice is nothing against the cost of deleting the only
    good copy of a graph.
    """
    from agentscaffold.paths import ensure_parent_dir  # noqa: PLC0415

    ensure_parent_dir(destination)
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise StateMigrationError(f"Could not copy {source} to {destination}: {exc}") from exc

    if _hash_file(source) != _hash_file(destination):
        destination.unlink(missing_ok=True)
        raise StateMigrationError(
            f"Copy of {source} did not verify against {destination}; source left in place."
        )


def _resolve_ends(start: Path | None, restore: bool) -> tuple[Path, Path] | None:
    """Return (source, destination) for the migration, or None if not applicable."""
    from agentscaffold.paths import (
        _DEFAULT_DB_PATH,
        _STATE_DB_FILENAME,
        resolve_user_state_dir,
        resolve_workspace_root,
        resolve_workspace_state_id,
    )

    workspace_id = resolve_workspace_state_id(start)
    if workspace_id is None:
        return None

    in_tree = resolve_workspace_root(start) / _DEFAULT_DB_PATH
    relocated = resolve_user_state_dir() / workspace_id / _STATE_DB_FILENAME
    return (relocated, in_tree) if restore else (in_tree, relocated)


def migrate_state(
    start: Path | None = None,
    *,
    apply: bool = False,
    restore: bool = False,
) -> StateMigrationResult:
    """Move this workspace's graph state, or report what moving it would do.

    With *apply* false (the default) nothing is written and the returned result
    names both ends so the user can see the move before consenting to it.
    """
    ends = _resolve_ends(start, restore)
    if ends is None:
        from agentscaffold.paths import _DEFAULT_DB_PATH, resolve_workspace_root  # noqa: PLC0415

        in_tree = resolve_workspace_root(start) / _DEFAULT_DB_PATH
        return StateMigrationResult(
            source=in_tree,
            destination=in_tree,
            needed=False,
            reason=(
                "This workspace has no stable id, so its graph stays in the tree. "
                "Run 'scaffold project register' to opt into managed state."
            ),
        )

    source, destination = ends

    if not source.is_file():
        return StateMigrationResult(
            source=source,
            destination=destination,
            needed=False,
            reason=(
                f"Already migrated: {destination}"
                if destination.is_file()
                else f"Nothing to migrate: no database at {source}"
            ),
        )

    result = StateMigrationResult(
        source=source,
        destination=destination,
        needed=True,
        reason=f"Would move {source} to {destination}",
    )
    if not apply:
        return result

    from agentscaffold.graph.liveness import DatabaseInUseError, require_database_idle

    try:
        require_database_idle(source)
    except DatabaseInUseError as exc:
        raise StateMigrationError(f"Cannot migrate while the database is in use. {exc}") from exc

    # Copy everything and verify it all before removing anything: a sidecar that
    # fails to arrive after the database has been deleted leaves the user with a
    # graph that works but re-indexes itself, and no way back.
    moves = [(source, destination)]
    for name in _SIDECAR_NAMES:
        sidecar = source.parent / name
        if sidecar.is_file():
            moves.append((sidecar, destination.parent / name))

    for src, dst in moves:
        _copy_verified(src, dst)
        result.copied.append(dst)

    for src, _dst in moves:
        src.unlink(missing_ok=True)

    _prune_empty_dir(source.parent)

    result.applied = True
    result.reason = f"Moved {source} to {destination}"
    logger.info("Migrated graph state from %s to %s", source, destination)
    return result


def _prune_empty_dir(path: Path) -> None:
    """Remove *path* if the migration emptied it, ignoring any other case."""
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:  # pragma: no cover - the directory is not ours to insist on
        logger.debug("Left %s in place after migration", path)
