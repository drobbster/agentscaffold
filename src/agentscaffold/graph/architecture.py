"""Parse ``system_architecture.md`` into ingestible architecture layers.

The architecture document is the human-owned, hard-gated baseline that assigns
source files to numbered layers. Each ``## Layer N: Name`` section carries a
free-text description (under ``### Current State``) and a set of path globs (the
``Paths`` column of its ``### Components`` table). This module turns that markdown
into structured layer records and provides the file->layer matcher used to build
``BELONGS_TO_LAYER`` edges.

Design notes:
- Placeholder layers left as ``## Layer N: [Name]`` (the un-populated template)
  are skipped so an un-filled doc ingests as a clean no-op.
- Matching is fragment/suffix-aware so a glob like ``agentscaffold/graph/parsing.py``
  matches whether the repo stores the file at the root or under ``src/``. When a
  file matches globs in more than one layer, the most specific (longest literal)
  glob wins; a file matching nothing is unassigned (a valid "unconfirmed" state).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

_LAYER_HEADING_RE = re.compile(r"^##\s+Layer\s+(\d+):\s*(.+?)\s*$", re.MULTILINE)
_PLACEHOLDER_NAME_RE = re.compile(r"^\[.*\]$")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_LABELED_PATHS_RE = re.compile(
    r"^\*\*(?:Paths|Location)\*\*:\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)
_URL_RE = re.compile(r"^[a-z]+://", re.IGNORECASE)


@dataclass
class ArchitectureLayerDef:
    """A single parsed architecture layer."""

    number: int
    name: str
    description: str = ""
    path_patterns: list[str] = field(default_factory=list)
    provenance: str = "empty"


def _clean_cell(cell: str) -> str:
    return cell.strip().strip("|").strip()


def _extract_paths_from_components(section: str) -> list[str]:
    """Pull backtick-wrapped globs from the ``Paths`` column of a Components table.

    Locates the ``### Components`` subsection, finds the ``Paths`` column by header
    position, and collects every backtick-wrapped token in that column. Falls back
    to an empty list when the table or column is absent.
    """
    comp_idx = section.find("### Components")
    if comp_idx == -1:
        return []
    # Bound to the Components subsection (up to the next '###' heading).
    rest = section[comp_idx + len("### Components") :]
    next_heading = rest.find("\n### ")
    if next_heading != -1:
        rest = rest[:next_heading]

    lines = [ln for ln in rest.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return []

    header_cells = [_clean_cell(c) for c in lines[0].strip().strip("|").split("|")]
    try:
        paths_col = next(i for i, h in enumerate(header_cells) if h.lower() == "paths")
    except StopIteration:
        return []

    patterns: list[str] = []
    seen: set[str] = set()
    # Skip header (0) and separator (1); data rows start at index 2.
    for row in lines[2:]:
        cells = row.strip().strip("|").split("|")
        if paths_col >= len(cells):
            continue
        for token in _BACKTICK_RE.findall(cells[paths_col]):
            for glob in token.split(","):
                g = glob.strip()
                if g and g not in seen:
                    seen.add(g)
                    patterns.append(g)
    return patterns


def _tokens_from_backticks(text: str) -> list[str]:
    patterns: list[str] = []
    seen: set[str] = set()
    for token in _BACKTICK_RE.findall(text):
        for glob in token.split(","):
            g = glob.strip()
            if g and g not in seen:
                seen.add(g)
                patterns.append(g)
    return patterns


def _extract_paths_from_labels(section: str) -> list[str]:
    """Pull backtick-wrapped globs from ``**Paths**:`` / ``**Location**:`` lines."""
    patterns: list[str] = []
    seen: set[str] = set()
    for m in _LABELED_PATHS_RE.finditer(section):
        for g in _tokens_from_backticks(m.group(1)):
            if g not in seen:
                seen.add(g)
                patterns.append(g)
    return patterns


def _looks_like_repo_path(token: str, known_top_level_dirs: list[str] | None) -> bool:
    t = token.strip().replace("\\", "/")
    if not t or " " in t or _URL_RE.match(t) or "/" not in t:
        return False
    if known_top_level_dirs:
        first = t.split("/", 1)[0]
        return first in known_top_level_dirs
    return True


def _extract_inline_paths(section: str, known_top_level_dirs: list[str] | None) -> list[str]:
    """Heuristic: backticked tokens that look like repo paths."""
    patterns: list[str] = []
    seen: set[str] = set()
    for token in _tokens_from_backticks(section):
        if not _looks_like_repo_path(token, known_top_level_dirs):
            continue
        if token not in seen:
            seen.add(token)
            patterns.append(token)
    return patterns


def extract_layer_path_patterns(
    section: str,
    known_top_level_dirs: list[str] | None = None,
) -> tuple[list[str], str]:
    """Return ``(patterns, provenance)`` using the Plan 261 priority order.

    Provenance is ``curated`` (Components table or labeled line), ``inferred``
    (inline path-like backticks), or ``empty``.
    """
    curated = _extract_paths_from_components(section)
    if curated:
        return curated, "curated"
    labeled = _extract_paths_from_labels(section)
    if labeled:
        return labeled, "curated"
    inferred = _extract_inline_paths(section, known_top_level_dirs)
    if inferred:
        return inferred, "inferred"
    return [], "empty"


def _extract_description(section: str) -> str:
    """Return the first paragraph under ``### Current State`` for a layer section."""
    cs_idx = section.find("### Current State")
    if cs_idx == -1:
        return ""
    rest = section[cs_idx + len("### Current State") :]
    next_heading = rest.find("\n### ")
    if next_heading != -1:
        rest = rest[:next_heading]
    # First non-empty paragraph.
    paragraph: list[str] = []
    for line in rest.splitlines():
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    return " ".join(paragraph).strip()


def has_real_layer_headings(text: str) -> bool:
    """True when the doc names at least one non-placeholder layer."""
    for match in _LAYER_HEADING_RE.finditer(text):
        if not _PLACEHOLDER_NAME_RE.match(match.group(2).strip()):
            return True
    return False


def parse_architecture_layers(
    text: str,
    known_top_level_dirs: list[str] | None = None,
) -> list[ArchitectureLayerDef]:
    """Parse an architecture-doc markdown string into layer definitions.

    Placeholder layers (name still ``[Name]``) are skipped. Layers with neither a
    real name nor path patterns contribute nothing to file mapping but are still
    returned when they carry a description, so callers can surface layer coverage.
    """
    layers: list[ArchitectureLayerDef] = []
    matches = list(_LAYER_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(2).strip()
        if _PLACEHOLDER_NAME_RE.match(name):
            continue
        number = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]
        patterns, provenance = extract_layer_path_patterns(section, known_top_level_dirs)
        layers.append(
            ArchitectureLayerDef(
                number=number,
                name=name,
                description=_extract_description(section),
                path_patterns=patterns,
                provenance=provenance,
            )
        )
    return layers


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip()


def _glob_matches(path: str, glob: str) -> bool:
    """Return True if ``glob`` matches ``path`` (fragment/suffix-aware)."""
    p = _normalize(path)
    g = _normalize(glob)
    if not g:
        return False
    if g.endswith("/"):
        # Directory pattern: match any file inside that directory segment.
        return f"/{p}".find(f"/{g}") != -1 or p.startswith(g)
    if p == g or p.endswith("/" + g):
        return True
    return fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p, f"*/{g}")


def _specificity(glob: str) -> int:
    """Rank a glob by literal specificity (longer, wildcard-free wins)."""
    g = _normalize(glob)
    return len(g) - g.count("*") * 100


def match_layer_for_file(
    path: str, layers: list[ArchitectureLayerDef]
) -> ArchitectureLayerDef | None:
    """Return the single best-matching layer for ``path``, or None.

    The layer owning the most specific matching glob wins; ties break toward the
    lower layer number (closer to the top of the dataflow) for determinism.
    """
    best: tuple[int, int, ArchitectureLayerDef] | None = None
    for layer in layers:
        for glob in layer.path_patterns:
            if _glob_matches(path, glob):
                spec = _specificity(glob)
                if best is None or spec > best[0] or (spec == best[0] and layer.number < best[1]):
                    best = (spec, layer.number, layer)
    return best[2] if best else None
