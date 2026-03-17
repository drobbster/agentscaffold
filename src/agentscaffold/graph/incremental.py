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
    from agentscaffold.graph.backend import GraphBackend

from agentscaffold.graph.query_compat import is_duckpgq, ql, ql_execute, ql_scalar

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
    store: GraphBackend,
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
    for row in ql(
        store,
        cypher="MATCH (f:File) RETURN f.path, f.contentHash",
        sql='SELECT path AS "f.path", contentHash AS "f.contentHash" FROM File',
    ):
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


def remove_file_nodes(store: GraphBackend, file_paths: list[str]) -> int:
    """Remove File nodes and all associated definitions for deleted files.

    Cascades: removes Function, Class, Method, Interface nodes defined
    in these files, plus all edges.

    Returns number of files removed.
    """
    removed = 0
    for path in file_paths:
        file_id = f"file::{path}"

        if is_duckpgq(store):
            # DuckDB: cascade via SQL DELETE on edge and node tables
            # Remove methods first (deepest level)
            method_ids = [
                r["m_id"]
                for r in store.query(
                    f"SELECT t.m_id FROM GRAPH_TABLE(agentscaffold_graph"
                    f"  MATCH (f:File)-[d:DEFINES_CLASS]->(c:Class)-[h:HAS_METHOD]->(m:Method)"
                    f"  WHERE f.id = '{file_id}'"
                    f"  COLUMNS (m.id AS m_id)"
                    f") t"
                )
            ]
            if method_ids:
                ids_lit = ", ".join(f"'{i}'" for i in method_ids)
                for et in ("CALLS", "METHOD_CALLS"):
                    store.execute(
                        f"DELETE FROM {et} WHERE src IN ({ids_lit}) OR dst IN ({ids_lit})"
                    )
                store.execute(f"DELETE FROM HAS_METHOD WHERE dst IN ({ids_lit})")
                store.execute(f"DELETE FROM Method WHERE id IN ({ids_lit})")
            # Remove functions
            fn_ids = [
                r["fn_id"]
                for r in store.query(
                    f"SELECT t.fn_id FROM GRAPH_TABLE(agentscaffold_graph"
                    f"  MATCH (f:File)-[d:DEFINES_FUNCTION]->(fn:Function)"
                    f"  WHERE f.id = '{file_id}'"
                    f"  COLUMNS (fn.id AS fn_id)"
                    f") t"
                )
            ]
            if fn_ids:
                ids_lit = ", ".join(f"'{i}'" for i in fn_ids)
                for et in ("CALLS", "METHOD_CALLS"):
                    store.execute(
                        f"DELETE FROM {et} WHERE src IN ({ids_lit}) OR dst IN ({ids_lit})"
                    )
                store.execute(f"DELETE FROM DEFINES_FUNCTION WHERE src = '{file_id}'")
                store.execute(f"DELETE FROM Function WHERE id IN ({ids_lit})")
            # Remove classes
            cls_ids = [
                r["c_id"]
                for r in store.query(
                    f"SELECT t.c_id FROM GRAPH_TABLE(agentscaffold_graph"
                    f"  MATCH (f:File)-[d:DEFINES_CLASS]->(c:Class)"
                    f"  WHERE f.id = '{file_id}'"
                    f"  COLUMNS (c.id AS c_id)"
                    f") t"
                )
            ]
            if cls_ids:
                ids_lit = ", ".join(f"'{i}'" for i in cls_ids)
                for et in ("EXTENDS", "IMPLEMENTS", "HAS_METHOD"):
                    store.execute(
                        f"DELETE FROM {et} WHERE src IN ({ids_lit}) OR dst IN ({ids_lit})"
                    )
                store.execute(f"DELETE FROM DEFINES_CLASS WHERE src = '{file_id}'")
                store.execute(f"DELETE FROM Class WHERE id IN ({ids_lit})")
            # Remove interfaces
            if_ids = [
                r["i_id"]
                for r in store.query(
                    f"SELECT t.i_id FROM GRAPH_TABLE(agentscaffold_graph"
                    f"  MATCH (f:File)-[d:DEFINES_INTERFACE]->(i:Interface)"
                    f"  WHERE f.id = '{file_id}'"
                    f"  COLUMNS (i.id AS i_id)"
                    f") t"
                )
            ]
            if if_ids:
                ids_lit = ", ".join(f"'{i}'" for i in if_ids)
                store.execute(f"DELETE FROM IMPLEMENTS WHERE dst IN ({ids_lit})")
                store.execute(f"DELETE FROM DEFINES_INTERFACE WHERE src = '{file_id}'")
                store.execute(f"DELETE FROM Interface WHERE id IN ({ids_lit})")
            # Remove the file itself and its direct edges
            for et in (
                "IMPORTS",
                "CONTAINS",
                "CONTAINS_FOLDER",
                "FINDING_ABOUT_FILE",
                "PLAN_IMPACTS",
                "CONTRACT_GOVERNS",
            ):
                try:
                    store.execute(f"DELETE FROM {et} WHERE src = '{file_id}' OR dst = '{file_id}'")
                except Exception:
                    pass  # Edge table may not reference File
            store.execute(f"DELETE FROM File WHERE id = '{file_id}'")
        else:
            # Cypher path (legacy)
            store.execute(
                f"MATCH (f:File)-[:DEFINES_FUNCTION]->(fn:Function) "
                f"WHERE f.id = '{file_id}' DETACH DELETE fn"
            )
            store.execute(
                f"MATCH (f:File)-[:DEFINES_CLASS]->(c:Class)-[:HAS_METHOD]->(m:Method) "
                f"WHERE f.id = '{file_id}' DETACH DELETE m"
            )
            store.execute(
                f"MATCH (f:File)-[:DEFINES_CLASS]->(c:Class) "
                f"WHERE f.id = '{file_id}' DETACH DELETE c"
            )
            store.execute(
                f"MATCH (f:File)-[:DEFINES_INTERFACE]->(i:Interface) "
                f"WHERE f.id = '{file_id}' DETACH DELETE i"
            )
            store.execute(f"MATCH (f:File) WHERE f.id = '{file_id}' DETACH DELETE f")

        removed += 1
        logger.debug("Removed file node: %s", path)

    return removed


def update_file_node(
    store: GraphBackend,
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

    language = _detect_language(full_path)
    ql_execute(
        store,
        cypher=(
            f"MATCH (f:File) WHERE f.id = '{file_id}' "
            f"SET f.size = {stat.st_size}, "
            f"f.lastModified = '{stat.st_mtime}', "
            f"f.lineCount = {line_count}, "
            f"f.contentHash = '{content_hash}', "
            f"f.language = '{language}'"
        ),
        sql=(
            f"UPDATE File SET size = {stat.st_size},"
            f" lastModified = '{stat.st_mtime}',"
            f" lineCount = {line_count},"
            f" contentHash = '{content_hash}',"
            f" language = '{language}'"
            f" WHERE id = '{file_id}'"
        ),
    )
    return True


def add_file_node(
    store: GraphBackend,
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
    existing = ql_scalar(
        store,
        cypher=f"MATCH (d:Folder) WHERE d.id = '{parent_id}' RETURN count(d)",
        sql=f"SELECT COUNT(*) FROM Folder WHERE id = '{parent_id}'",
    )
    if existing and int(existing) > 0:
        store.create_edge("CONTAINS", "Folder", parent_id, "File", file_id)

    return True
