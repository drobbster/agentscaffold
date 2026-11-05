"""Inventory paths (contract v1, Paths section).

A path is relative to the project root, or to the version-control root when it
starts with ``@repo/`` (Plan 283). Absolute paths, ``..`` and a leading ``//``
are invalid. Resolution goes through :func:`agentscaffold.paths.resolve_node_path`,
which fails closed outside the version-control root; this module adds no second
resolver.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from agentscaffold.paths import resolve_node_path, vcs_root
from agentscaffold.repo_paths import REPO_PREFIX, is_repo_path, repo_node_path, vcs_relative

_DRIVE = re.compile(r"^[A-Za-z]:")
#: Suffixes that make a slash-free entrypoint a file; ``pkg.cli:main`` is a module.
_FILE_SUFFIXES = frozenset(
    {
        ".py", ".ipynb", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".go", ".rb", ".r",
        ".sql", ".yaml", ".yml", ".json", ".toml", ".java", ".scala", ".rs", ".ps1",
    }
)  # fmt: skip


def path_problem(path: str) -> str | None:
    """Why *path* is not a valid inventory path, or None when it is."""
    if not path or not path.strip():
        return "is empty"
    if path.startswith("//"):
        return "starts with '//'; use @repo/ for the version-control root"
    if path.startswith(("/", "\\")) or _DRIVE.match(path):
        return "is absolute"
    if "\\" in path:
        return "uses backslashes"
    body = vcs_relative(path) if is_repo_path(path) else path
    if is_repo_path(path) and (not body or body.startswith("/")):
        return "is a malformed @repo/ path"
    if ".." in body.rstrip("/").split("/"):
        return "contains '..'"
    return None


def is_dir_path(path: str) -> bool:
    """A ``reads`` entry naming a directory ends with ``/``."""
    return path.endswith("/")


def entrypoint_path(entrypoint: str | None) -> str | None:
    """The file part of ``path:symbol`` or of a bare file path; None for a command.

    A command (``uvicorn app:app --port 80``), an image (``postgres:16``) or a
    module (``pkg.cli:main``) is not a path: the part before the colon must
    contain ``/`` or end in a known file suffix.
    """
    if not entrypoint or any(ch.isspace() for ch in entrypoint.strip()):
        return None
    head = entrypoint.strip()
    if ":" in head:
        head = head.rsplit(":", 1)[0]
    if "/" in head or Path(head).suffix.lower() in _FILE_SUFFIXES:
        return head
    return None


def resolve(root: Path, path: str) -> Path | None:
    """The file *path* names, or None when invalid or outside the VCS root."""
    if path_problem(path) is not None:
        return None
    return resolve_node_path(root, path.rstrip("/") or ".")


def graph_path(root: Path, path: str) -> str | None:
    """*path* in the form the graph names files: project-relative, else ``@repo/``.

    ``@repo/x`` names the same file as ``x`` when the project is the VCS root,
    and as ``sub/x``'s project-relative form when the project is ``sub/``. A
    trailing ``/`` (a directory) is kept. None for an invalid path or one that
    resolves outside the VCS root.
    """
    if path_problem(path) is not None:
        return None
    if not is_repo_path(path):
        while path.startswith("./"):
            path = path[2:]
        return "" if path in ("", ".") else path
    disk = resolve(root, path)
    if disk is None:
        return None
    suffix = "/" if is_dir_path(path) else ""
    project = Path(os.path.realpath(root))
    target = Path(os.path.realpath(disk))
    try:
        rel = target.relative_to(project).as_posix()
    except ValueError:
        return path
    return (rel + suffix) if rel != "." else ""


def to_inventory_path(root: Path, disk: Path) -> str | None:
    """The inventory form of a file on disk: project-relative, else ``@repo/``."""
    project = Path(os.path.realpath(root))
    target = Path(os.path.realpath(disk))
    try:
        return target.relative_to(project).as_posix()
    except ValueError:
        pass
    repo = vcs_root(project)
    if repo is None:
        return None
    try:
        return repo_node_path(target.relative_to(Path(os.path.realpath(repo))).as_posix())
    except ValueError:
        return None


def covers(read: str, path: str) -> bool:
    """True when the graph path *path* is the file *read* names or lies under it."""
    if not read:
        return True
    if is_dir_path(read):
        return path.startswith(read) or path == read.rstrip("/")
    return path == read


def touches(read: str, path: str) -> bool:
    """True when editing *path* (a file or a ``/``-terminated directory) touches *read*."""
    if covers(read, path):
        return True
    return is_dir_path(path) and read.startswith(path)


__all__ = [
    "REPO_PREFIX",
    "covers",
    "entrypoint_path",
    "graph_path",
    "is_dir_path",
    "path_problem",
    "resolve",
    "to_inventory_path",
    "touches",
]
