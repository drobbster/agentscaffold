"""Monorepo source roots: module prefixes (Plan 278) and extra paths (Plan 283).

A project registered at ``<repo>/company/team_x`` is imported as
``company.team_x.foo`` by code that runs from the repository root. The import
resolver works relative to the project root, so it needs to know that
``company.team_x`` names the project root itself. That prefix is inferred from
the project's path below its version-control root, and ``graph.module_prefixes``
adds further prefix-to-directory mappings.

``graph.extra_paths`` adds files outside the project folder (a team's Airflow
DAGs at ``<repo>/airflow/dags/team_x``), indexed as ``@repo/<path>``.
"""

from __future__ import annotations

import keyword
import logging
import os
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.paths import vcs_root
from agentscaffold.repo_paths import (
    compile_extra_glob,
    extra_glob_problem,
    literal_base,
    repo_node_path,
)

if TYPE_CHECKING:
    from agentscaffold.config import GraphConfig

logger = logging.getLogger(__name__)


def is_module_name(dotted: str) -> bool:
    """True when every dotted segment is a Python identifier and not a keyword."""
    segments = dotted.split(".")
    return all(seg.isidentifier() and not keyword.iskeyword(seg) for seg in segments)


def infer_module_prefix(project_root: Path) -> str | None:
    """Return the dotted path of *project_root* below its VCS root, or None.

    Nothing is inferred when there is no VCS root, when the project is the VCS
    root, or when any path segment could not appear in an import statement
    (``team-x``, ``class``).
    """
    root = project_root.resolve()
    repo = vcs_root(root)
    if repo is None or repo == root:
        return None
    parts = root.relative_to(repo).parts
    dotted = ".".join(parts)
    if not is_module_name(dotted):
        logger.debug("No module prefix inferred for %s: %r is not importable", root, dotted)
        return None
    return dotted


def effective_module_prefixes(project_root: Path, config: GraphConfig) -> dict[str, str]:
    """Merge the inferred prefix with ``graph.module_prefixes``.

    The inferred prefix maps to the project root (``"."``). An explicit entry
    for the same prefix replaces it.
    """
    prefixes: dict[str, str] = {}
    if config.infer_module_prefix:
        inferred = infer_module_prefix(project_root)
        if inferred:
            prefixes[inferred] = "."
    prefixes.update(config.module_prefixes)
    return prefixes


@dataclass(frozen=True)
class ExtraPathScan:
    """Extra-path files as ``@repo/`` File paths, and why any entry matched less."""

    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _OtherProject:
    name: str
    root: Path
    patterns: list[re.Pattern[str]]


def scan_extra_paths(
    project_root: Path,
    config: GraphConfig | None,
    *,
    allowed_languages: Collection[str] | None = None,
) -> ExtraPathScan:
    """Expand ``graph.extra_paths`` for the project at *project_root*.

    Files inside this project are left to the normal walk. Files inside another
    registered project, outside the VCS root (through ``..`` or a symlink),
    ignored at the VCS root, or matched by another registered project's
    ``extra_paths`` are skipped with a warning.
    """
    globs = list(dict.fromkeys(getattr(config, "extra_paths", None) or []))
    if not globs:
        return ExtraPathScan()
    root = project_root.resolve()
    found = vcs_root(root)
    if found is None:
        return ExtraPathScan(
            warnings=[f"graph.extra_paths ignored: {root} is not inside a git checkout"]
        )
    repo = found.resolve()
    if (root / "@repo").exists():
        return ExtraPathScan(
            warnings=[
                f"graph.extra_paths ignored: {root / '@repo'} exists, and its files "
                "would share ids with extra-path files"
            ]
        )

    from agentscaffold.graph.structure import collect_ignore_patterns  # noqa: PLC0415

    ignore = collect_ignore_patterns(repo)
    others = _other_projects(root)
    languages = set(allowed_languages) if allowed_languages else None
    files: set[str] = set()
    warnings: list[str] = []
    for glob in globs:
        problem = extra_glob_problem(glob)
        if problem:
            warnings.append(f"graph.extra_paths entry {glob!r} {problem}; skipped")
            continue
        matched, notes = _expand(glob, repo, root, ignore, others, languages)
        files.update(matched)
        warnings.extend(notes)
        if not matched and not notes:
            warnings.append(f"graph.extra_paths entry {glob!r} matches no files")
    return ExtraPathScan(files=sorted(files), warnings=warnings)


def _expand(
    glob: str,
    repo: Path,
    root: Path,
    ignore: list[str],
    others: list[_OtherProject],
    languages: set[str] | None,
) -> tuple[list[str], list[str]]:
    from agentscaffold.graph.structure import (  # noqa: PLC0415
        _detect_language,
        _directory_ignored,
        _should_ignore,
    )

    label = f"graph.extra_paths entry {glob!r}"
    try:
        base = (repo / literal_base(glob)).resolve()
        base.relative_to(repo)
    except (OSError, ValueError):
        return [], [f"{label} resolves outside the VCS root {repo}; skipped"]
    if not base.is_dir():
        return [], []
    blocked = _owner(base, root, others)
    if blocked:
        return [], [f"{label} lies inside {blocked}; skipped"]

    pattern = compile_extra_glob(glob)
    matched: list[str] = []
    notes: list[str] = []
    refused: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        here = Path(dirpath)
        rel_dir = here.relative_to(repo).as_posix()
        keep: list[str] = []
        for name in dirnames:
            owner = _owner(here / name, root, others)
            if owner:
                refused.add(owner)
            elif not _directory_ignored(f"{rel_dir}/{name}", ignore):
                keep.append(name)
        dirnames[:] = sorted(keep)
        for name in sorted(filenames):
            rel = f"{rel_dir}/{name}"
            if not pattern.fullmatch(rel) or _should_ignore(rel, ignore):
                continue
            full = here / name
            if full.is_symlink() and not _inside(full.resolve(), repo):
                notes.append(f"{label}: {rel} links outside the VCS root; skipped")
                continue
            if languages is not None and _detect_language(full) not in languages:
                continue
            claimed = [o.name for o in others if any(p.fullmatch(rel) for p in o.patterns)]
            if claimed:
                notes.append(
                    f"{label}: {rel} is also in graph.extra_paths of project "
                    f"{', '.join(claimed)}; indexed by neither"
                )
                continue
            matched.append(repo_node_path(rel))
    notes.extend(
        f"{label} reaches into {owner}; those files are skipped" for owner in sorted(refused)
    )
    return matched, notes


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _owner(path: Path, root: Path, others: list[_OtherProject]) -> str | None:
    """Who owns *path* instead of extra paths: this project or another registered one."""
    if _inside(path, root):
        return f"this project ({root})"
    for other in others:
        if _inside(path, other.root):
            return f"registered project {other.name}"
    return None


def _other_projects(root: Path) -> list[_OtherProject]:
    """Every registered project except the one at *root*, with its extra-path globs."""
    try:
        from agentscaffold.workspace_registry import load_registry  # noqa: PLC0415

        registry = load_registry()
    except Exception as exc:  # noqa: BLE001 - a broken registry must not stop indexing
        logger.debug("extra paths: registry unreadable: %s", exc)
        return []
    out: list[_OtherProject] = []
    for workspace in registry.workspaces:
        for project in workspace.projects:
            other_root = workspace.project_root(project)
            if other_root == root:
                continue
            globs = [g for g in configured_extra_paths(other_root) if not extra_glob_problem(g)]
            patterns = [compile_extra_glob(g) for g in globs]
            out.append(_OtherProject(project.name, other_root, patterns))
    return out


def configured_extra_paths(project_root: Path) -> list[str]:
    """``graph.extra_paths`` from *project_root*'s ``scaffold.yaml``, read without validation."""
    import yaml  # noqa: PLC0415

    try:
        raw: Any = yaml.safe_load((project_root / "scaffold.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    graph = raw.get("graph") if isinstance(raw, dict) else None
    entries = graph.get("extra_paths") if isinstance(graph, dict) else None
    return [e for e in entries if isinstance(e, str)] if isinstance(entries, list) else []


def extra_path_files(
    project_root: Path, config: GraphConfig | None, allowed_languages: Collection[str] | None
) -> list[str]:
    """The ``@repo/`` File paths a walk adds for *config*; warnings go to the debug log."""
    scan = scan_extra_paths(project_root, config, allowed_languages=allowed_languages)
    for warning in scan.warnings:
        logger.debug("%s", warning)
    return scan.files
