"""Paths to project files outside the project folder (Plan 283).

``graph.extra_paths`` lists globs, relative to the version-control root, of
files that belong to a project but live elsewhere in its repository. Their
File nodes use the path ``@repo/<path relative to the VCS root>``.

Standard library only: the editor hook router imports this module on every
edit, where pydantic and the configuration must not load.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_PREFIX = "@repo/"

_WILDCARDS = frozenset("*?[")


def is_repo_path(path: str) -> bool:
    """True for a File path in the ``@repo/`` form."""
    return path.startswith(REPO_PREFIX)


def repo_node_path(vcs_relative: str) -> str:
    """The File path for a file at *vcs_relative* below the VCS root."""
    return REPO_PREFIX + vcs_relative.lstrip("/")


def vcs_relative(path: str) -> str:
    """The path below the VCS root that an ``@repo/`` File path names."""
    return path[len(REPO_PREFIX) :] if is_repo_path(path) else path


def path_spellings(path: str) -> list[str]:
    """*path* and, for an ``@repo/`` path, the VCS-relative form text readers store."""
    return [path, vcs_relative(path)] if is_repo_path(path) else [path]


def find_vcs_root(start: Path) -> Path | None:
    """The nearest ancestor of *start* holding a ``.git`` entry, or None."""
    current = Path(os.path.realpath(start))
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return None


def extra_glob_problem(glob: str) -> str | None:
    """Why *glob* cannot be an ``extra_paths`` entry, or None when it can.

    An entry is relative to the VCS root and starts with a literal directory,
    so expanding it walks only below that directory.
    """
    if not glob or not glob.strip():
        return "is empty"
    if glob.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", glob) or "\\" in glob:
        return "must be a POSIX path relative to the VCS root"
    segments = glob.split("/")
    if ".." in segments:
        return "must not contain '..'"
    if segments[0] == REPO_PREFIX.rstrip("/"):
        return "is written without the @repo/ prefix"
    if len(segments) < 2 or _WILDCARDS & set(segments[0]):
        return "must start with a literal directory, such as airflow/dags/**/*.py"
    return None


def literal_base(glob: str) -> str:
    """The leading directories of *glob* that contain no wildcard."""
    base: list[str] = []
    for segment in glob.split("/")[:-1]:
        if _WILDCARDS & set(segment):
            break
        base.append(segment)
    return "/".join(base)


def compile_extra_glob(glob: str) -> re.Pattern[str]:
    """A pattern matching VCS-relative POSIX paths against *glob*.

    ``*`` and ``?`` stay within one path segment; a ``**`` segment matches
    zero or more whole segments.
    """
    segments = glob.split("/")
    out: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            out.append("(?:[^/]+/)*[^/]+" if last else "(?:[^/]+/)*")
            continue
        out.append(_segment_regex(segment) + ("" if last else "/"))
    return re.compile("".join(out))


def _segment_regex(segment: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(segment):
        char = segment[i]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and segment.find("]", i + 2) != -1:
            end = segment.find("]", i + 2)
            body = segment[i + 1 : end].replace("\\", "\\\\")
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append(f"[{body}]")
            i = end
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


def matches_any(vcs_rel: str, globs: list[str]) -> bool:
    """True when *vcs_rel* matches one of *globs* that is a valid entry."""
    return any(
        extra_glob_problem(g) is None and compile_extra_glob(g).fullmatch(vcs_rel) for g in globs
    )
