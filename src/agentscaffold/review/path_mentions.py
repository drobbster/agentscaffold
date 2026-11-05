"""Path mentions in review text, normalized to project-relative form (Plan 281).

Findings and learnings name the files they are about in free text
(``src/agentscaffold/mcp/server.py:1870``) as well as in explicit
``file_paths``. Both are kept, so precedent can later find every finding about
a file even when no File node for it exists in the recording project's graph
(the governance and code split).

Normalization accepts the three forms paths arrive in: project-relative,
relative to the version-control root (a project inside a monorepo), and
absolute. A path that belongs to a sibling folder or lies outside the project
is kept as given and reported as foreign.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

#: Most paths extracted from one text; longer lists are noise, not precedent.
MAX_MENTIONS = 20

_EXTENSIONS = frozenset(
    {
        "bash", "c", "cc", "cfg", "cjs", "cpp", "cs", "css", "csv", "go", "graphql",
        "h", "hpp", "html", "ini", "ipynb", "java", "js", "json", "jsonl", "jsx", "kt",
        "lock", "md", "mdc", "mjs", "php", "proto", "py", "pyi", "rb", "rs", "rst",
        "scss", "sh", "sql", "toml", "ts", "tsx", "txt", "yaml", "yml", "zsh",
    }
)  # fmt: skip

_TOP_LEVEL_DIRS = frozenset(
    {
        ".cursor", ".github", "apps", "bin", "cmd", "config", "configs", "data", "docs",
        "eval", "examples", "internal", "lib", "libs", "outputs", "packages", "pkg",
        "scripts", "services", "src", "test", "tests", "tools",
    }
)  # fmt: skip

_URL_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://\S+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./@+-]+")
_TRAILING_PUNCT = ".,;:)]}'\"`"


def _clean(raw: str) -> str:
    """Strip quoting, a ``:line[:col]`` suffix and a leading ``./``."""
    text = raw.strip().strip("`'\"").replace("\\", "/")
    text = re.sub(r"(:\d+)+$", "", text)
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _looks_like_path(token: str) -> bool:
    if not token or "//" in token or ".." in token.split("/")[-1]:
        return False
    segments = [s for s in token.split("/") if s]
    if not segments:
        return False
    last = segments[-1]
    if "." in last.strip("."):
        ext = last.rsplit(".", 1)[1].lower()
        if ext in _EXTENSIONS:
            return True
    first = segments[0] if not token.startswith("/") else ""
    return len(segments) > 1 and first in _TOP_LEVEL_DIRS


def extract_paths(text: str | None, limit: int = MAX_MENTIONS) -> list[str]:
    """Return the distinct file and directory paths mentioned in *text*, in order."""
    if not text:
        return []
    found: list[str] = []
    for match in _TOKEN_RE.finditer(_URL_RE.sub(" ", text)):
        token = _clean(match.group(0).rstrip(_TRAILING_PUNCT))
        if _looks_like_path(token) and token not in found:
            found.append(token)
            if len(found) >= limit:
                break
    return found


def _relative_to(child: str, parent: Path) -> str | None:
    """POSIX path of *child* under *parent*, or None; tolerant of symlinked roots."""
    for c, p in (
        (os.path.normpath(child), os.path.normpath(str(parent))),
        (str(Path(child).resolve()), str(parent.resolve())),
    ):
        if c == p:
            return ""
        if c.startswith(p.rstrip(os.sep) + os.sep):
            return Path(os.path.relpath(c, p)).as_posix()
    return None


def to_project_relative(
    path: str, project_root: Path, vcs_root: Path | None = None
) -> tuple[str, bool]:
    """Normalize *path* against *project_root*; return ``(path, foreign)``.

    A foreign path (a sibling folder in the same repository, or anywhere
    outside the project) is returned as given, cleaned of quoting and line
    suffixes.
    """
    cleaned = _clean(path)
    if not cleaned:
        return "", False

    if os.path.isabs(cleaned) or cleaned.split("/", 1)[0] == "..":
        absolute = cleaned if os.path.isabs(cleaned) else str(project_root / cleaned)
        rel = _relative_to(absolute, project_root)
        return (rel, False) if rel else (cleaned, True)

    if vcs_root is not None:
        prefix = _relative_to(str(project_root), vcs_root)
        if prefix:
            if cleaned == prefix or cleaned.startswith(prefix + "/"):
                return cleaned[len(prefix) + 1 :], False
            first = cleaned.split("/", 1)[0]
            if (vcs_root / first).exists() and not (project_root / first).exists():
                return cleaned, True
    return cleaned, False


def collect_paths(
    explicit: Iterable[str] | None,
    texts: Iterable[str | None] = (),
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Explicit paths plus paths mentioned in *texts*, normalized and deduplicated.

    Without *project_root* paths are only cleaned, not re-rooted.
    """
    candidates = [p for p in (explicit or []) if isinstance(p, str)]
    for text in texts:
        candidates.extend(extract_paths(text))

    vcs: Path | None = None
    if project_root is not None:
        from agentscaffold.paths import vcs_root  # noqa: PLC0415

        vcs = vcs_root(project_root)

    out: list[str] = []
    for raw in candidates:
        if project_root is not None:
            norm, _foreign = to_project_relative(raw, project_root, vcs)
        else:
            norm = _clean(raw)
        if norm and norm not in out:
            out.append(norm)
    # A bare file name usually abbreviates a fuller path already collected.
    return [p for p in out if "/" in p or not any(o.endswith("/" + p) for o in out)]
