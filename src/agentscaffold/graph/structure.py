"""Phase 1: Directory structure processor.

Walks the file tree respecting .gitignore and scaffold.yaml ignore patterns,
creating Folder and File nodes with content hashes.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscaffold.config import GraphConfig
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

_PROGRESS_INTERVAL = 5000

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".R": "r",
    ".lua": "lua",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".sql": "sql",
}

DEFAULT_IGNORE = [
    "**/.git/**",
    "**/__pycache__/**",
    "**/node_modules/**",
    "**/.venv/**",
    "**/.venv-*/**",
    "**/venv/**",
    "**/.direnv/**",
    "**/.mypy_cache/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/.scaffold/**",
    ".scaffold/*",
    "**/dist/**",
    "**/build/**",
    "**/*.egg-info/**",
    "**/outputs/**",
    "**/mlruns/**",
    "**/.cursor/**",
    "**/.claude/**",
    "**/.hypothesis/**",
]


def _load_gitignore_patterns(root: Path) -> list[str]:
    """Load patterns from .gitignore if it exists."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    patterns = []
    for line in gitignore.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("**/") and not line.startswith("/"):
            patterns.append(f"**/{line}")
        else:
            patterns.append(line.lstrip("/"))
    return patterns


def _should_ignore(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any ignore pattern.

    Handles ``**/`` prefixes correctly: ``**`` can match zero path components,
    so ``**/.git/**`` also matches ``.git/HEAD`` at the repo root.
    """
    for pattern in patterns:
        # Build candidate patterns: original + **/-stripped variant
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])

        for pat in candidates:
            if fnmatch(rel_path, pat):
                return True
            if fnmatch(rel_path + "/", pat):
                return True
            parts = rel_path.split("/")
            for i in range(len(parts)):
                partial = "/".join(parts[: i + 1])
                if fnmatch(partial, pat) or fnmatch(partial + "/", pat):
                    return True
    return False


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


def _detect_language(path: Path) -> str:
    """Detect language from file extension."""
    return LANGUAGE_MAP.get(path.suffix.lower(), "unknown")


def collect_ignore_patterns(root: Path, graph_config: GraphConfig | None = None) -> list[str]:
    """Return DEFAULT_IGNORE plus .gitignore and graph.ignore patterns."""
    patterns = list(DEFAULT_IGNORE)
    patterns.extend(_load_gitignore_patterns(root))
    if graph_config is not None:
        patterns.extend(getattr(graph_config, "ignore", None) or [])
    return patterns


def _directory_ignored(rel_dir: str, patterns: list[str]) -> bool:
    """Return True if *rel_dir* or any child under it would be ignored."""
    return _should_ignore(rel_dir, patterns) or _should_ignore(f"{rel_dir}/_", patterns)


def walk_indexable(
    root: Path,
    ignore_patterns: list[str],
    *,
    on_visit: Callable[[str], None] | None = None,
) -> list[tuple[str, bool]]:
    """Walk *root*, pruning ignored directories before descending.

    Returns ``(rel_posix, is_dir)`` for non-ignored entries. ``on_visit`` is
    called for directory names considered for descent and for files seen;
    it is never called for paths inside a pruned directory.
    """
    root = root.resolve()
    entries: list[tuple[str, bool]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        try:
            rel_dir_path = Path(dirpath).resolve().relative_to(root)
        except ValueError:
            dirnames[:] = []
            continue
        rel_dir = rel_dir_path.as_posix()
        if rel_dir == ".":
            rel_dir = ""

        keep: list[str] = []
        for name in dirnames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if on_visit is not None:
                on_visit(rel)
            if _directory_ignored(rel, ignore_patterns):
                continue
            keep.append(name)
        dirnames[:] = sorted(keep)

        if rel_dir:
            entries.append((rel_dir, True))

        for name in sorted(filenames):
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if on_visit is not None:
                on_visit(rel)
            if _should_ignore(rel, ignore_patterns):
                continue
            entries.append((rel, False))
    return entries


def scan_indexable_files(
    root: Path,
    ignore_patterns: list[str],
    *,
    allowed_languages: set[str] | None = None,
    on_visit: Callable[[str], None] | None = None,
) -> list[str]:
    """Return relative file paths the indexer should consider."""
    files: list[str] = []
    for rel, is_dir in walk_indexable(root, ignore_patterns, on_visit=on_visit):
        if is_dir:
            continue
        if allowed_languages is not None:
            language = _detect_language(Path(rel))
            if language not in allowed_languages:
                continue
        files.append(rel)
    return files


def create_file_node(store: GraphBackend, full_path: Path, node_path: str) -> bool:
    """Create the File node for *full_path* under *node_path*; False if unreadable."""
    try:
        stat = full_path.stat()
        line_count = full_path.read_text(errors="replace").count("\n") + 1
    except (OSError, PermissionError):
        return False
    store.create_node(
        "File",
        {
            "id": f"file::{node_path}",
            "path": node_path,
            "language": _detect_language(full_path),
            "size": stat.st_size,
            "lastModified": str(stat.st_mtime),
            "lineCount": line_count,
            "contentHash": _file_hash(full_path),
        },
    )
    return True


def ensure_folder_chain(
    store: GraphBackend, folder_path: str, known: dict[str, str] | None = None
) -> str:
    """Create missing Folder nodes for *folder_path* and its ancestors; return its id.

    *known* maps folder paths already in the graph to their ids and is updated.
    Without it, existence is checked in the graph.
    """
    from agentscaffold.graph.query_compat import ql_scalar  # noqa: PLC0415

    known = known if known is not None else {}
    parent_id = "folder::"
    parts = [p for p in folder_path.split("/") if p]
    for depth in range(1, len(parts) + 1):
        path = "/".join(parts[:depth])
        folder_id = f"folder::{path}"
        if path not in known:
            exists = ql_scalar(store, sql=f"SELECT COUNT(*) FROM Folder WHERE id = '{folder_id}'")
            if not exists or int(exists) == 0:
                store.create_node(
                    "Folder",
                    {"id": folder_id, "path": path, "name": parts[depth - 1], "depth": depth},
                )
                store.create_edge("CONTAINS_FOLDER", "Folder", parent_id, "Folder", folder_id)
            known[path] = folder_id
        parent_id = known[path]
    return parent_id


def _process_extra_paths(
    store: GraphBackend,
    root: Path,
    graph_config: GraphConfig | None,
    allowed_languages: set[str] | None,
    folder_ids: dict[str, str],
) -> dict[str, int]:
    """Index ``graph.extra_paths`` files (Plan 283) under an ``@repo`` folder."""
    from agentscaffold.graph.source_roots import scan_extra_paths  # noqa: PLC0415
    from agentscaffold.paths import resolve_node_path  # noqa: PLC0415

    counts = {"files": 0, "folders": 0, "skipped": 0}
    scan = scan_extra_paths(root, graph_config, allowed_languages=allowed_languages)
    for index, warning in enumerate(scan.warnings):
        logger.warning("%s", warning)
        store.add_parsing_warning(
            f"pw::extra_paths::{index}", "", "extra_paths", warning, "warning"
        )
    before = len(folder_ids)
    for node_path in scan.files:
        full = resolve_node_path(root, node_path)
        if full is None or not create_file_node(store, full, node_path):
            counts["skipped"] += 1
            continue
        parent_id = ensure_folder_chain(store, node_path.rsplit("/", 1)[0], folder_ids)
        store.create_edge("CONTAINS", "Folder", parent_id, "File", f"file::{node_path}")
        counts["files"] += 1
    counts["folders"] = len(folder_ids) - before
    return counts


def process_structure(
    store: GraphBackend,
    root: Path,
    graph_config: GraphConfig | None = None,
) -> dict:
    """Walk directory tree and create Folder/File nodes.

    Returns a summary dict with counts.
    """
    ignore_patterns = collect_ignore_patterns(root, graph_config)

    allowed_languages: set[str] | None = None
    if graph_config and graph_config.languages:
        allowed_languages = set(graph_config.languages)

    file_count = 0
    folder_count = 0
    skipped_count = 0

    root = root.resolve()

    root_id = "folder::"
    store.create_node("Folder", {"id": root_id, "path": ".", "name": root.name, "depth": 0})
    folder_count += 1
    folder_ids: dict[str, str] = {"": root_id}
    items_seen = 0

    for rel_str, is_dir in walk_indexable(root, ignore_patterns):
        items_seen += 1
        if items_seen % _PROGRESS_INTERVAL == 0:
            sys.stdout.write(
                f"\r  scanning... {file_count:,} files, "
                f"{folder_count:,} folders ({items_seen:,} entries processed)"
            )
            sys.stdout.flush()

        rel = Path(rel_str)
        if is_dir:
            folder_id = f"folder::{rel_str}"
            store.create_node(
                "Folder",
                {
                    "id": folder_id,
                    "path": rel_str,
                    "name": rel.name,
                    "depth": len(rel.parts),
                },
            )
            folder_ids[rel_str] = folder_id
            folder_count += 1

            parent_rel = rel.parent.as_posix() if rel.parent.as_posix() != "." else ""
            parent_id = folder_ids.get(parent_rel, root_id)
            store.create_edge("CONTAINS_FOLDER", "Folder", parent_id, "Folder", folder_id)
            continue

        item = root / rel_str
        if allowed_languages and _detect_language(item) not in allowed_languages:
            skipped_count += 1
            continue
        if not create_file_node(store, item, rel_str):
            skipped_count += 1
            continue
        file_count += 1

        parent_rel = rel.parent.as_posix() if rel.parent.as_posix() != "." else ""
        parent_id = folder_ids.get(parent_rel, root_id)
        store.create_edge("CONTAINS", "Folder", parent_id, "File", f"file::{rel_str}")

    if items_seen >= _PROGRESS_INTERVAL:
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

    extra = _process_extra_paths(store, root, graph_config, allowed_languages, folder_ids)
    file_count += extra["files"]
    folder_count += extra["folders"]
    skipped_count += extra["skipped"]

    return {
        "files": file_count,
        "folders": folder_count,
        "skipped": skipped_count,
    }
