"""Phase 1: Directory structure processor.

Walks the file tree respecting .gitignore and scaffold.yaml ignore patterns,
creating Folder and File nodes with content hashes.
"""

from __future__ import annotations

import hashlib
import logging
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscaffold.config import GraphConfig
    from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)

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
    "**/venv/**",
    "**/.mypy_cache/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/.scaffold/**",
    ".scaffold/*",
    "**/dist/**",
    "**/build/**",
    "**/*.egg-info/**",
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
    """Check if a relative path matches any ignore pattern."""
    for pattern in patterns:
        if fnmatch(rel_path, pattern):
            return True
        if fnmatch(rel_path + "/", pattern):
            return True
        parts = rel_path.split("/")
        for i in range(len(parts)):
            partial = "/".join(parts[: i + 1])
            if fnmatch(partial, pattern) or fnmatch(partial + "/", pattern):
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


def process_structure(
    store: GraphStore,
    root: Path,
    graph_config: GraphConfig | None = None,
) -> dict:
    """Walk directory tree and create Folder/File nodes.

    Returns a summary dict with counts.
    """
    ignore_patterns = list(DEFAULT_IGNORE)
    ignore_patterns.extend(_load_gitignore_patterns(root))
    if graph_config:
        ignore_patterns.extend(graph_config.ignore)

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

    for item in sorted(root.rglob("*")):
        try:
            rel = item.relative_to(root)
        except ValueError:
            continue

        rel_str = str(rel)

        if _should_ignore(rel_str, ignore_patterns):
            continue

        if item.is_dir():
            folder_id = f"folder::{rel_str}"
            store.create_node(
                "Folder",
                {
                    "id": folder_id,
                    "path": rel_str,
                    "name": item.name,
                    "depth": len(rel.parts),
                },
            )
            folder_ids[rel_str] = folder_id
            folder_count += 1

            parent_rel = str(rel.parent) if str(rel.parent) != "." else ""
            parent_id = folder_ids.get(parent_rel, root_id)
            store.create_edge("CONTAINS_FOLDER", "Folder", parent_id, "Folder", folder_id)

        elif item.is_file():
            language = _detect_language(item)

            if allowed_languages and language not in allowed_languages:
                skipped_count += 1
                continue

            try:
                stat = item.stat()
                line_count = item.read_text(errors="replace").count("\n") + 1
            except (OSError, PermissionError):
                skipped_count += 1
                continue

            content_hash = _file_hash(item)
            file_id = f"file::{rel_str}"

            store.create_node(
                "File",
                {
                    "id": file_id,
                    "path": rel_str,
                    "language": language,
                    "size": stat.st_size,
                    "lastModified": str(stat.st_mtime),
                    "lineCount": line_count,
                    "contentHash": content_hash,
                },
            )
            file_count += 1

            parent_rel = str(rel.parent) if str(rel.parent) != "." else ""
            parent_id = folder_ids.get(parent_rel, root_id)
            store.create_edge("CONTAINS", "Folder", parent_id, "File", file_id)

    return {
        "files": file_count,
        "folders": folder_count,
        "skipped": skipped_count,
    }
