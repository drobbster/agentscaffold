"""Git-backed governance serialization (Plan 222).

Agent-generated knowledge -- review findings, sessions, and backlog items --
historically lived only in the local DuckDB cache, invisible to teammates and
lost if the cache (or an ephemeral devbox) was deleted. This module serializes
that governance to a versioned, git-committed JSON artifact so it becomes the
durable *system of record*; the graph is then a derived index that
``scaffold index`` rebuilds from the artifact plus code.

The codec reuses the backend's ``export_governance``/``import_governance``
shapes (introduced in Plan 219 for schema-migration safety), promoting them from
a migration-only mechanism into the durable store.

Format: a single JSON object with a top-level ``governance_artifact_version``.
Rows are emitted in a stable order (nodes by ``id``, edges by ``src``/``dst``)
so re-serializing an unchanged graph produces an identical file -- minimizing
spurious git diffs and merge churn. Writes are atomic (temp file + ``os.replace``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

GOVERNANCE_ARTIFACT_VERSION = 1

# Attribute name used to opt a backend instance into write-through serialization.
# ``open_graph`` sets it; raw backends (e.g. in-memory test stores) leave it
# unset, so write-through is inert unless explicitly enabled.
_ARTIFACT_ATTR = "_governance_artifact"
_LOCK_ATTR = "_governance_write_lock"
_FS_LOCK_DEPTH_ATTR = "_governance_fs_lock_depth"


class GovernanceArtifactError(Exception):
    """Raised when a governance artifact exists but cannot be parsed."""


def resolve_governance_artifact(config: ScaffoldConfig | None, start: Path | None = None) -> Path:
    """Resolve the governance artifact path against the project root."""
    from agentscaffold.config import GraphConfig
    from agentscaffold.paths import resolve_root

    raw = GraphConfig().governance_artifact
    if config is not None and hasattr(config, "graph"):
        raw = config.graph.governance_artifact or raw
    p = Path(raw)
    if p.is_absolute():
        return p
    return resolve_root(start) / p


def _stable(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of an export payload with rows in a deterministic order."""
    nodes = {}
    for table, payload in data.get("nodes", {}).items():
        rows = sorted(payload.get("rows", []), key=lambda r: str(r.get("id", "")))
        nodes[table] = {"columns": payload.get("columns", []), "rows": rows}
    edges = {}
    for table, payload in data.get("edges", {}).items():
        rows = sorted(
            payload.get("rows", []),
            key=lambda r: (str(r.get("src", "")), str(r.get("dst", ""))),
        )
        edges[table] = {"columns": payload.get("columns", []), "rows": rows}
    return {"nodes": nodes, "edges": edges}


def serialize_governance(store: GraphBackend, artifact_path: Path) -> Path:
    """Export preserved governance from *store* to a versioned JSON artifact.

    Atomic: writes a sibling ``.tmp`` file then ``os.replace`` over the target.
    """
    if not hasattr(store, "export_governance"):
        raise GovernanceArtifactError("backend does not support governance export")

    data = store.export_governance()
    payload = {
        "governance_artifact_version": GOVERNANCE_ARTIFACT_VERSION,
        "export_schema_version": data.get("export_schema_version"),
        **_stable(data),
    }

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, artifact_path)
    return artifact_path


def load_governance(artifact_path: Path) -> dict[str, Any] | None:
    """Load a governance artifact. Returns None if it does not exist.

    Raises :class:`GovernanceArtifactError` if the file exists but is not valid
    JSON or is not a JSON object -- the knowledge is reported as unreadable
    rather than silently ignored.
    """
    if not artifact_path.is_file():
        return None
    try:
        raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise GovernanceArtifactError(
            f"governance artifact at {artifact_path} is not readable JSON: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise GovernanceArtifactError(
            f"governance artifact at {artifact_path} is not a JSON object"
        )
    return raw


def ingest_governance(store: GraphBackend, artifact_path: Path) -> dict[str, Any]:
    """Ingest a governance artifact into *store* (idempotent).

    Returns the ``import_governance`` summary, or an empty summary when no
    artifact is present. Re-import is idempotent (nodes ON CONFLICT DO NOTHING;
    edges WHERE NOT EXISTS), so re-running over an existing graph is safe.
    """
    data = load_governance(artifact_path)
    if data is None:
        return {"imported": {}, "skipped": {}, "compatible": True, "present": False}
    if not hasattr(store, "import_governance"):
        raise GovernanceArtifactError("backend does not support governance import")
    result: dict[str, Any] = store.import_governance(data)
    result["present"] = True
    return result


def enable_write_through(store: GraphBackend, artifact_path: Path) -> None:
    """Mark *store* so governance mutations re-serialize to *artifact_path*."""
    setattr(store, _ARTIFACT_ATTR, artifact_path)
    _lock_for(store)


def _lock_for(store: GraphBackend) -> threading.RLock:
    lock = getattr(store, _LOCK_ATTR, None)
    if lock is None:
        lock = threading.RLock()
        setattr(store, _LOCK_ATTR, lock)
    return lock


@contextmanager
def governance_write_lock(store: GraphBackend) -> Iterator[None]:
    """Serialize governance mutations that share one backend connection.

    DuckDB connections are not safe to drive concurrently from multiple Python
    threads while write-through export is reading the same preserved governance
    tables. The lock is per backend instance and re-entrant so mutation helpers
    can wrap their full write+sync sequence while ``sync_if_enabled`` also
    protects direct serialization calls.
    """
    with _lock_for(store):
        db_path = getattr(store, "_db_path", None)
        already_index_locked = bool(getattr(store, "_graph_write_lock_active", False))
        depth = int(getattr(store, _FS_LOCK_DEPTH_ATTR, 0) or 0)
        if db_path is None or already_index_locked or depth > 0:
            setattr(store, _FS_LOCK_DEPTH_ATTR, depth + 1)
            try:
                yield
            finally:
                setattr(store, _FS_LOCK_DEPTH_ATTR, depth)
            return

        from agentscaffold.graph.locks import graph_write_lock  # noqa: PLC0415

        with graph_write_lock(db_path, purpose="governance_write", timeout=8.0):
            setattr(store, _FS_LOCK_DEPTH_ATTR, 1)
            try:
                yield
            finally:
                setattr(store, _FS_LOCK_DEPTH_ATTR, 0)


def sync_if_enabled(store: GraphBackend) -> None:
    """Re-serialize governance if *store* has write-through enabled.

    Called at the end of runtime governance mutations (record/resolve finding,
    session start/modify/end, backlog record/resolve). Best-effort: a
    serialization failure is logged but does not break the in-graph write that
    already succeeded.
    """
    artifact_path = getattr(store, _ARTIFACT_ATTR, None)
    if artifact_path is None:
        return
    try:
        with governance_write_lock(store):
            serialize_governance(store, artifact_path)
    except Exception as exc:  # noqa: BLE001 - write-through must not break the write
        logger.warning("Governance write-through to %s failed: %s", artifact_path, exc)
