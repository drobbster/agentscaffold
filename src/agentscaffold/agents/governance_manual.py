"""The project's governance manual, parsed into sections addressed by heading.

The manual is the project-owned part of ``AGENTS.md`` (everything outside the
managed block). This module only reads it. Sections are addressed by
heading path, ``"Plan Lifecycle / Gate: Ready -> In Progress"``, and lookup is
tolerant of case, spacing, a leading ``Gate:`` and a trailing qualifier such as
``(Mandatory)``, so a mapping written against the shipped template keeps
working on a manual whose headings carry those decorations.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscaffold.agents.manual_diff import parse_heading_paths, project_owned_text

logger = logging.getLogger(__name__)

DEFAULT_MANUAL_PATH = "AGENTS.md"
PATH_SEPARATOR = " / "

_GATE_PREFIX_RE = re.compile(r"^gate:\s*", re.IGNORECASE)
_QUALIFIER_RE = re.compile(r"\s*\([^()]*\)\s*$")

_CACHE: dict[str, tuple[tuple[int, int], GovernanceManual]] = {}


def normalize_heading(segment: str) -> str:
    """Comparison key for one heading segment."""
    text = " ".join(segment.split())
    text = _GATE_PREFIX_RE.sub("", text)
    text = _QUALIFIER_RE.sub("", text)
    return text.casefold()


def _split_path(name: str) -> tuple[str, ...]:
    return tuple(normalize_heading(part) for part in name.split(PATH_SEPARATOR) if part.strip())


def governance_protected_headings(config: Any) -> set[str]:
    """Normalized `##` headings the governance mapping reads from.

    ``scaffold agents repair --prefer-managed`` must never drop these, even when
    one shares a heading with the managed routing block.
    """
    governance = config.agents.governance
    names = list(governance.orient) + list(governance.optional)
    for step in type(governance.steps).model_fields:
        names += list(getattr(governance.steps, step))
    return {parts[0] for parts in map(_split_path, names) if parts}


@dataclass(frozen=True, eq=False)
class GovernanceManual:
    """A parsed manual. ``headings`` lists every `##` and `###` path in order."""

    path: str
    sha256: str
    headings: tuple[str, ...]
    _texts: dict[str, str] = field(repr=False)
    _by_path: dict[tuple[str, ...], str] = field(repr=False)
    _by_last: dict[str, str] = field(repr=False)

    @property
    def top_headings(self) -> list[str]:
        """The `##` headings, in document order."""
        return [heading for heading in self.headings if PATH_SEPARATOR not in heading]

    def resolve(self, name: str) -> str | None:
        """Canonical heading path for *name*, or ``None`` when nothing matches.

        A single segment matches a `##` heading first, then the first `###`
        heading with that name.
        """
        key = _split_path(name)
        if not key:
            return None
        found = self._by_path.get(key)
        if found is None and len(key) == 1:
            found = self._by_last.get(key[0])
        return found

    def section(self, name: str) -> str | None:
        """Text of the section *name*; a `##` section includes its `###` subsections."""
        canonical = self.resolve(name)
        return None if canonical is None else self._texts[canonical]

    def suggestions(self, name: str, limit: int = 3) -> list[str]:
        """The *limit* headings closest to *name*, best first."""
        query = PATH_SEPARATOR.join(_split_path(name))
        last = query.rsplit(PATH_SEPARATOR, 1)[-1]

        def score(heading: str) -> float:
            key = _split_path(heading)
            full = difflib.SequenceMatcher(None, query, PATH_SEPARATOR.join(key)).ratio()
            tail = difflib.SequenceMatcher(None, last, key[-1]).ratio() if key else 0.0
            return max(full, tail)

        ranked = sorted(self.headings, key=lambda heading: (-score(heading), heading))
        return ranked[:limit]


def parse_manual(text: str, *, path: str = DEFAULT_MANUAL_PATH) -> GovernanceManual:
    """Parse the project-owned region of *text*."""
    owned = project_owned_text(text)
    sections = parse_heading_paths(owned)

    headings: list[str] = []
    texts: dict[str, str] = {}
    by_path: dict[tuple[str, ...], str] = {}
    by_last: dict[str, str] = {}
    for section in sections:
        canonical = PATH_SEPARATOR.join(part for part in section.path if part)
        if canonical in texts:
            continue
        headings.append(canonical)
        texts[canonical] = section.body
        by_path.setdefault(_split_path(canonical), canonical)
        if section.level == 3:
            by_last.setdefault(normalize_heading(section.path[-1]), canonical)
            parent = section.path[0]
            if parent in texts:
                child = f"### {section.path[-1]}\n{section.body}".rstrip()
                texts[parent] = f"{texts[parent]}\n\n{child}".strip("\n")

    return GovernanceManual(
        path=path,
        sha256=hashlib.sha256(owned.encode("utf-8")).hexdigest(),
        headings=tuple(headings),
        _texts=texts,
        _by_path=by_path,
        _by_last=by_last,
    )


def load_manual(
    project_root: Path, manual_path: str = DEFAULT_MANUAL_PATH
) -> GovernanceManual | None:
    """Read and parse the manual at *manual_path* under *project_root*.

    Returns ``None`` when the file is missing, unreadable, or resolves outside
    the project root. Parsed manuals are cached per file until its modification
    time or size changes.
    """
    root = project_root.resolve()
    target = (root / manual_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    try:
        stat = target.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = _CACHE.get(str(target))
        if cached is not None and cached[0] == stamp:
            return cached[1]
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("governance manual unreadable at %s: %s", target, exc)
        return None
    manual = parse_manual(text, path=Path(manual_path).as_posix())
    _CACHE[str(target)] = (stamp, manual)
    return manual
