"""C3 guidance stamp (Plan 251). Built from the already-resolved project root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentscaffold.rendering import (
    GUIDANCE_COPY_RELPATHS,
    GUIDANCE_STAMP_KEY,
    MANAGED_BLOCK_BEGIN,
    canonical_guidance_path,
)

_GENERATED_MARKERS = (MANAGED_BLOCK_BEGIN, GUIDANCE_STAMP_KEY, "@generated")


def compact_guidance_stamp(project_root: Path) -> dict[str, Any]:
    """Fields every tool ``meta`` carries. No diary keys.

    Keys are always present so C3 can assert a stamp even when this project
    has not generated a rule file yet. ``guidance_rule_path`` is None then,
    never an absolute home path.
    """
    rule = _guidance_rule_file(project_root)
    rel = _workspace_relative(project_root, rule) if rule is not None else None
    stamp: dict[str, Any] = {
        "guidance_rule_path": rel,
        "guidance_is_generated": _is_generated(rule) if rule is not None else False,
    }
    canonical = canonical_guidance_path(project_root)
    if canonical is not None:
        can_rel = _workspace_relative(project_root, canonical)
        if can_rel and can_rel != rel:
            stamp["guidance_canonical_path"] = can_rel
    return stamp


def full_guidance_stamp(project_root: Path) -> dict[str, Any]:
    """Larger guidance object for orient/projects. Still not a diary dump."""
    compact = compact_guidance_stamp(project_root)
    copies: list[str] = []
    for rel in GUIDANCE_COPY_RELPATHS:
        path = project_root / rel
        if path.is_file():
            copies.append(rel.as_posix())
    agents = project_root / "AGENTS.md"
    if agents.is_file() and "AGENTS.md" not in copies:
        copies.append("AGENTS.md")
    return {**compact, "guidance_copies": copies}


def _guidance_rule_file(project_root: Path) -> Path | None:
    """The routing file that most likely governed this project."""
    candidates: list[Path] = []
    canonical = canonical_guidance_path(project_root)
    if canonical is not None:
        candidates.append(canonical)
    candidates.extend(project_root / rel for rel in GUIDANCE_COPY_RELPATHS)
    candidates.append(project_root / "AGENTS.md")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _is_generated(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    return any(marker in head for marker in _GENERATED_MARKERS)


def _workspace_relative(project_root: Path, path: Path) -> str | None:
    """Workspace-relative posix path. Never leak an absolute home path."""
    resolved = path.resolve()
    roots = [project_root.resolve()]
    try:
        from agentscaffold.paths import resolve_workspace_root

        roots.append(resolve_workspace_root(project_root).resolve())
    except Exception:
        pass
    for root in roots:
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.name
