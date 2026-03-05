"""Incremental indexing support.

Compares content hashes of files on disk against those stored in the graph
to determine which files need re-processing. Handles three cases:

1. New files: added since last index
2. Modified files: content hash differs
3. Deleted files: exist in graph but not on disk

Only changed files go through the full parse/resolve pipeline, dramatically
reducing re-index time on large codebases.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.config import GraphConfig
    from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except (OSError, PermissionError):
        return ""
    return h.hexdigest()


def compute_changeset(
    store: GraphStore,
    root: Path,
    graph_config: GraphConfig | None = None,
) -> dict[str, Any]:
    """Compare on-disk files with graph state and return a changeset.

    Returns:
        {
            "added": [rel_path, ...],
            "modified": [rel_path, ...],
            "deleted": [rel_path, ...],
            "unchanged": int,
        }
    """
    from agentscaffold.graph.structure import (
        DEFAULT_IGNORE,
        _detect_language,
        _load_gitignore_patterns,
        _should_ignore,
    )

    ignore_patterns = list(DEFAULT_IGNORE)
    ignore_patterns.extend(_load_gitignore_patterns(root))
    if graph_config:
        ignore_patterns.extend(graph_config.ignore)

    allowed_languages: set[str] | None = None
    if graph_config and graph_config.languages:
        allowed_languages = set(graph_config.languages)

    # Build map of graph files: path -> contentHash
    graph_files: dict[str, str] = {}
    for row in store.query("MATCH (f:File) RETURN f.path, f.contentHash"):
        graph_files[row["f.path"]] = row["f.contentHash"]

    # Walk disk
    disk_files: dict[str, str] = {}
    root = root.resolve()
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        try:
            rel = str(item.relative_to(root))
        except ValueError:
            continue
        if _should_ignore(rel, ignore_patterns):
            continue

        language = _detect_language(item)
        if allowed_languages and language not in allowed_languages:
            continue

        disk_files[rel] = _file_hash(item)

    added: list[str] = []
    modified: list[str] = []
    unchanged = 0

    for path, disk_hash in disk_files.items():
        if path not in graph_files:
            added.append(path)
        elif graph_files[path] != disk_hash:
            modified.append(path)
        else:
            unchanged += 1

    deleted = [p for p in graph_files if p not in disk_files]

    return {
        "added": sorted(added),
        "modified": sorted(modified),
        "deleted": sorted(deleted),
        "unchanged": unchanged,
    }


def remove_file_nodes(store: GraphStore, file_paths: list[str]) -> int:
    """Remove File nodes and all associated definitions for deleted files.

    Cascades: removes Function, Class, Method, Interface nodes defined
    in these files, plus all edges.

    Returns number of files removed.
    """
    removed = 0
    for path in file_paths:
        file_id = f"file::{path}"

        # Remove functions defined in this file
        store.execute(
            f"MATCH (f:File)-[:DEFINES_FUNCTION]->(fn:Function) "
            f"WHERE f.id = '{file_id}' DETACH DELETE fn"
        )
        # Remove methods defined via classes in this file
        store.execute(
            f"MATCH (f:File)-[:DEFINES_CLASS]->(c:Class)-[:HAS_METHOD]->(m:Method) "
            f"WHERE f.id = '{file_id}' DETACH DELETE m"
        )
        # Remove classes defined in this file
        store.execute(
            f"MATCH (f:File)-[:DEFINES_CLASS]->(c:Class) "
            f"WHERE f.id = '{file_id}' DETACH DELETE c"
        )
        # Remove interfaces defined in this file
        store.execute(
            f"MATCH (f:File)-[:DEFINES_INTERFACE]->(i:Interface) "
            f"WHERE f.id = '{file_id}' DETACH DELETE i"
        )
        # Remove the file node itself (and its edges)
        store.execute(f"MATCH (f:File) WHERE f.id = '{file_id}' DETACH DELETE f")
        removed += 1
        logger.debug("Removed file node: %s", path)

    return removed


def update_file_node(
    store: GraphStore,
    root: Path,
    rel_path: str,
) -> bool:
    """Update an existing File node with new metadata and content hash.

    Returns True if the file was updated successfully.
    """
    full_path = root / rel_path
    if not full_path.is_file():
        return False

    from agentscaffold.graph.structure import _detect_language

    try:
        stat = full_path.stat()
        line_count = full_path.read_text(errors="replace").count("\n") + 1
    except (OSError, PermissionError):
        return False

    content_hash = _file_hash(full_path)
    file_id = f"file::{rel_path}"

    store.execute(
        f"MATCH (f:File) WHERE f.id = '{file_id}' "
        f"SET f.size = {stat.st_size}, "
        f"f.lastModified = '{stat.st_mtime}', "
        f"f.lineCount = {line_count}, "
        f"f.contentHash = '{content_hash}', "
        f"f.language = '{_detect_language(full_path)}'"
    )
    return True


def add_file_node(
    store: GraphStore,
    root: Path,
    rel_path: str,
) -> bool:
    """Create a new File node for a newly discovered file.

    Also creates the Folder -> File edge.
    Returns True if created successfully.
    """
    full_path = root / rel_path
    if not full_path.is_file():
        return False

    from agentscaffold.graph.structure import _detect_language

    try:
        stat = full_path.stat()
        line_count = full_path.read_text(errors="replace").count("\n") + 1
    except (OSError, PermissionError):
        return False

    content_hash = _file_hash(full_path)
    language = _detect_language(full_path)
    file_id = f"file::{rel_path}"

    store.create_node(
        "File",
        {
            "id": file_id,
            "path": rel_path,
            "language": language,
            "size": stat.st_size,
            "lastModified": str(stat.st_mtime),
            "lineCount": line_count,
            "contentHash": content_hash,
        },
    )

    # Link to parent folder
    parent_rel = str(Path(rel_path).parent)
    if parent_rel == ".":
        parent_rel = ""
    parent_id = f"folder::{parent_rel}" if parent_rel else "folder::"

    # Check if parent folder exists; create if not
    existing = store.query_scalar(f"MATCH (d:Folder) WHERE d.id = '{parent_id}' RETURN count(d)")
    if existing and int(existing) > 0:
        store.create_edge("CONTAINS", "Folder", parent_id, "File", file_id)

    return True
