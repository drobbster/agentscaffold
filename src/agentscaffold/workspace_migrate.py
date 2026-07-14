"""Brownfield workspace asset-layout migrator (Plan 234).

``scaffold workspace migrate-layout`` promotes duplicated reusable *process*
assets (prompts, standards, templates, collaboration protocol, commands, shared
security templates) from per-project ``docs/ai`` trees up to a single committed
copy at the workspace root, then writes ``asset_layout: shared_workspace`` into
``workspace.yaml``.

Design invariants:

- **Never** move project system-of-record artifacts (plans, ADRs, contracts,
  spikes, state, backlog, architecture, vision, roadmap, studies, runbook).
- Dry-run is non-mutating and the default posture; ``--apply`` mutates.
- Identical copies promote safely; diverged copies require an explicit policy
  (``--prefer-project`` or ``--keep-diverged``) or the apply is refused.
- A dirty git worktree refuses a destructive ``--apply`` unless ``--force``.
- Re-running on an already ``shared_workspace`` workspace is a no-op.

Exit codes (Appendix E): ``0`` success / already migrated; ``2`` diverged
conflicts unresolved on apply without policy; ``3`` dirty worktree without
``--force``.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agentscaffold.config import (
    AssetLayoutConfig,
    WorkspaceConfig,
    find_workspace_config,
    load_workspace_manifest,
)

# Process-asset roots eligible for promotion, relative to each project root.
# Directories are scanned recursively; files are matched exactly. Security is
# handled specially (templates only) so real threat models are never promoted.
_ELIGIBLE_DIRS: tuple[str, ...] = (
    "docs/ai/prompts",
    "docs/ai/standards",
    "docs/ai/templates",
)
_ELIGIBLE_FILES: tuple[str, ...] = (
    "docs/ai/collaboration_protocol.md",
    "docs/ai/commands.md",
)
_SECURITY_DIR = "docs/security"

# Project system-of-record roots that migrate-layout must NEVER move.
SOR_PROTECTED: tuple[str, ...] = (
    "docs/ai/plans",
    "docs/ai/adrs",
    "docs/ai/contracts",
    "docs/ai/spikes",
    "docs/ai/state",
    "docs/studies",
    "docs/runbook",
    "docs/ai/backlog.md",
    "docs/ai/backlog_archive.md",
    "docs/ai/product_vision.md",
    "docs/ai/strategy_roadmap.md",
    "docs/ai/system_architecture.md",
    "docs/ai/architectural_design_changelog.md",
)


@dataclass
class AssetCandidate:
    """One eligible process-asset relative path found in one or more projects."""

    rel_path: str
    klass: str  # "identical" | "diverged" | "unique"
    projects: list[str]  # project names that contain this file
    hashes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "class": self.klass,
            "projects": self.projects,
            "hashes": self.hashes,
        }


@dataclass
class MigrationReport:
    """Machine-readable + human-readable result of a migrate-layout run."""

    workspace_root: str
    applied: bool
    already_shared: bool = False
    identical: list[AssetCandidate] = field(default_factory=list)
    diverged: list[AssetCandidate] = field(default_factory=list)
    unique: list[AssetCandidate] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    kept_diverged: list[str] = field(default_factory=list)
    sor_protected: list[str] = field(default_factory=lambda: list(SOR_PROTECTED))
    exit_code: int = 0
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "applied": self.applied,
            "already_shared": self.already_shared,
            "identical": [c.to_dict() for c in self.identical],
            "diverged": [c.to_dict() for c in self.diverged],
            "unique": [c.to_dict() for c in self.unique],
            "promoted": self.promoted,
            "deleted": self.deleted,
            "kept_diverged": self.kept_diverged,
            "sor_protected": self.sor_protected,
            "exit_code": self.exit_code,
            "messages": self.messages,
        }


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_roots(workspace_root: Path, workspace: WorkspaceConfig) -> dict[str, Path]:
    """Map project name -> resolved project root within the workspace."""
    roots: dict[str, Path] = {}
    for entry in workspace.projects:
        p = Path(entry.path)
        if not p.is_absolute():
            p = workspace_root / p
        roots[entry.name] = p.resolve()
    return roots


def _eligible_rel_paths(project_root: Path) -> list[str]:
    """Return eligible process-asset rel paths present under *project_root*."""
    rels: list[str] = []
    for d in _ELIGIBLE_DIRS:
        base = project_root / d
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    rels.append(f.relative_to(project_root).as_posix())
    for f_rel in _ELIGIBLE_FILES:
        if (project_root / f_rel).is_file():
            rels.append(f_rel)
    sec = project_root / _SECURITY_DIR
    if sec.is_dir():
        for f in sorted(sec.rglob("*")):
            # Only shared *templates*, never real threat models / findings.
            if f.is_file() and f.name.endswith("_template.md"):
                rels.append(f.relative_to(project_root).as_posix())
    return rels


def classify_assets(
    workspace_root: Path, workspace: WorkspaceConfig
) -> list[AssetCandidate]:
    """Classify every eligible process asset across all registered projects."""
    roots = _project_roots(workspace_root, workspace)
    # rel_path -> {project_name: hash}
    seen: dict[str, dict[str, str]] = {}
    for name, root in roots.items():
        for rel in _eligible_rel_paths(root):
            seen.setdefault(rel, {})[name] = _hash_file(root / rel)

    candidates: list[AssetCandidate] = []
    for rel in sorted(seen):
        by_project = seen[rel]
        names = sorted(by_project)
        if len(names) == 1:
            klass = "unique"
        elif len({by_project[n] for n in names}) == 1:
            klass = "identical"
        else:
            klass = "diverged"
        candidates.append(
            AssetCandidate(rel_path=rel, klass=klass, projects=names, hashes=by_project)
        )
    return candidates


def _git_dirty(workspace_root: Path) -> bool:
    """Return True if the git worktree at *workspace_root* has changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def _write_asset_layout(manifest_path: Path, workspace: WorkspaceConfig) -> None:
    """Merge ``asset_layout: shared_workspace`` into workspace.yaml, keep projects."""
    raw: dict[str, Any] = {}
    if manifest_path.is_file():
        raw = yaml.safe_load(manifest_path.read_text()) or {}
    raw["projects"] = [{"name": p.name, "path": p.path} for p in workspace.projects]
    layout = AssetLayoutConfig(layout="shared_workspace")
    raw["asset_layout"] = layout.model_dump()
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False))


def _regenerate_agents(workspace_root: Path, workspace: WorkspaceConfig) -> None:
    """Best-effort regeneration of the workspace router + project stub AGENTS."""
    try:
        from agentscaffold.agents.generate import write_workspace_agents_router

        write_workspace_agents_router(workspace_root, workspace)
    except Exception:
        pass


def run_migrate_layout(
    start: Path | None = None,
    *,
    apply: bool = False,
    prefer_project: str | None = None,
    keep_diverged: bool = False,
    force: bool = False,
) -> MigrationReport:
    """Run (or dry-run) the workspace asset-layout migration.

    Returns a :class:`MigrationReport` whose ``exit_code`` the CLI propagates.
    Dry-run (``apply=False``) never mutates the filesystem.
    """
    ws_path = find_workspace_config(start)
    if ws_path is None:
        return MigrationReport(
            workspace_root=str((start or Path.cwd()).resolve()),
            applied=apply,
            exit_code=1,
            messages=[
                "No workspace.yaml found. Run 'scaffold workspace onboard' to "
                "create a multi-project workspace first."
            ],
        )
    workspace_root = ws_path.parent.resolve()
    workspace = load_workspace_manifest(ws_path)

    report = MigrationReport(workspace_root=str(workspace_root), applied=apply)

    if not workspace.is_multi_project:
        report.exit_code = 1
        report.messages.append(
            "Workspace has fewer than two registered projects; migrate-layout is "
            "for multi-project workspaces. Use 'scaffold workspace onboard' first."
        )
        return report

    if workspace.is_shared_workspace:
        report.already_shared = True
        report.messages.append("Workspace is already shared_workspace; nothing to do.")
        return report

    candidates = classify_assets(workspace_root, workspace)
    report.identical = [c for c in candidates if c.klass == "identical"]
    report.diverged = [c for c in candidates if c.klass == "diverged"]
    report.unique = [c for c in candidates if c.klass == "unique"]

    unresolved = [
        c
        for c in report.diverged
        if not keep_diverged
        and (prefer_project is None or prefer_project not in c.projects)
    ]

    if not apply:
        report.messages.append(
            f"Dry-run: {len(report.identical)} identical, {len(report.diverged)} "
            f"diverged, {len(report.unique)} unique process assets. No files changed."
        )
        if unresolved:
            report.messages.append(
                f"{len(unresolved)} diverged path(s) need a policy "
                "(--prefer-project NAME or --keep-diverged) before --apply."
            )
        return report

    # -- Apply path ---------------------------------------------------------
    if _git_dirty(workspace_root) and not force:
        report.exit_code = 3
        report.messages.append(
            "Refusing to apply on a dirty git worktree. Commit/stash first or "
            "pass --force."
        )
        return report

    if unresolved:
        report.exit_code = 2
        report.messages.append(
            f"Refusing to apply: {len(unresolved)} diverged path(s) have no policy. "
            "Pass --prefer-project NAME or --keep-diverged."
        )
        return report

    roots = _project_roots(workspace_root, workspace)

    def _promote(rel: str, source_project: str, all_projects: list[str]) -> None:
        src = roots[source_project] / rel
        dest = workspace_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(src, dest)
            report.promoted.append(rel)
        for name in all_projects:
            proj_copy = roots[name] / rel
            if proj_copy.exists():
                proj_copy.unlink()
                report.deleted.append(f"{name}:{rel}")

    for cand in report.identical:
        _promote(cand.rel_path, cand.projects[0], cand.projects)

    for cand in report.unique:
        _promote(cand.rel_path, cand.projects[0], cand.projects)

    for cand in report.diverged:
        if keep_diverged and prefer_project is None:
            report.kept_diverged.append(cand.rel_path)
            continue
        # prefer_project resolved (unresolved list is empty here).
        assert prefer_project is not None
        _promote(cand.rel_path, prefer_project, cand.projects)

    _write_asset_layout(ws_path, workspace)
    workspace = load_workspace_manifest(ws_path)
    _regenerate_agents(workspace_root, workspace)

    report.messages.append(
        f"Applied: promoted {len(report.promoted)}, deleted "
        f"{len(report.deleted)} redundant copies, kept {len(report.kept_diverged)} "
        "diverged. Wrote asset_layout: shared_workspace."
    )
    return report
