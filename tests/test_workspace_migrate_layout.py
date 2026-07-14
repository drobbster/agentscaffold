"""Tests for ``scaffold workspace migrate-layout`` (Plan 234, Appendix E).

Covers dry-run non-mutation, identical promote+delete, diverged policy branches,
SoR-never-moved, the dirty-worktree guard, and idempotent re-runs.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from agentscaffold.workspace_migrate import run_migrate_layout


def _make_ws(tmp_path: Path, layout: str | None = None) -> Path:
    ws = tmp_path / "ws"
    for name in ("alpha", "beta"):
        (ws / name).mkdir(parents=True)
        (ws / name / "scaffold.yaml").write_text(f"framework:\n  project_name: {name}\n")
    manifest = "projects:\n  - name: alpha\n    path: alpha\n  - name: beta\n    path: beta\n"
    if layout:
        manifest += f"asset_layout:\n  layout: {layout}\n"
    (ws / "workspace.yaml").write_text(manifest)
    return ws


def _write(ws: Path, project: str, rel: str, content: str) -> Path:
    p = ws / project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_dry_run_is_non_mutating(tmp_path: Path):
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/standards/errors.md", "same")
    _write(ws, "beta", "docs/ai/standards/errors.md", "same")

    report = run_migrate_layout(ws, apply=False)

    assert report.exit_code == 0
    assert any(c.rel_path == "docs/ai/standards/errors.md" for c in report.identical)
    # Nothing moved or written.
    assert (ws / "alpha/docs/ai/standards/errors.md").exists()
    assert (ws / "beta/docs/ai/standards/errors.md").exists()
    assert not (ws / "docs/ai/standards/errors.md").exists()
    assert "shared_workspace" not in (ws / "workspace.yaml").read_text()


def test_identical_promote_and_delete(tmp_path: Path):
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/standards/errors.md", "same")
    _write(ws, "beta", "docs/ai/standards/errors.md", "same")
    _write(ws, "alpha", "docs/ai/commands.md", "cmd")
    _write(ws, "beta", "docs/ai/commands.md", "cmd")

    report = run_migrate_layout(ws, apply=True)

    assert report.exit_code == 0
    assert (ws / "docs/ai/standards/errors.md").read_text() == "same"
    assert (ws / "docs/ai/commands.md").read_text() == "cmd"
    assert not (ws / "alpha/docs/ai/standards/errors.md").exists()
    assert not (ws / "beta/docs/ai/standards/errors.md").exists()
    assert "shared_workspace" in (ws / "workspace.yaml").read_text()


def test_unique_asset_promoted(tmp_path: Path):
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/prompts/custom.md", "only-alpha")

    report = run_migrate_layout(ws, apply=True)

    assert report.exit_code == 0
    assert (ws / "docs/ai/prompts/custom.md").read_text() == "only-alpha"
    assert not (ws / "alpha/docs/ai/prompts/custom.md").exists()


def test_diverged_without_policy_refused(tmp_path: Path):
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/standards/errors.md", "alpha-version")
    _write(ws, "beta", "docs/ai/standards/errors.md", "beta-version")

    report = run_migrate_layout(ws, apply=True)

    assert report.exit_code == 2
    # Untouched.
    assert (ws / "alpha/docs/ai/standards/errors.md").exists()
    assert (ws / "beta/docs/ai/standards/errors.md").exists()
    assert "shared_workspace" not in (ws / "workspace.yaml").read_text()


def test_diverged_prefer_project(tmp_path: Path):
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/standards/errors.md", "alpha-version")
    _write(ws, "beta", "docs/ai/standards/errors.md", "beta-version")

    report = run_migrate_layout(ws, apply=True, prefer_project="alpha")

    assert report.exit_code == 0
    assert (ws / "docs/ai/standards/errors.md").read_text() == "alpha-version"
    assert not (ws / "alpha/docs/ai/standards/errors.md").exists()
    assert not (ws / "beta/docs/ai/standards/errors.md").exists()


def test_diverged_keep_diverged(tmp_path: Path):
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/standards/errors.md", "alpha-version")
    _write(ws, "beta", "docs/ai/standards/errors.md", "beta-version")

    report = run_migrate_layout(ws, apply=True, keep_diverged=True)

    assert report.exit_code == 0
    assert "docs/ai/standards/errors.md" in report.kept_diverged
    # Project copies preserved; no shared file written.
    assert (ws / "alpha/docs/ai/standards/errors.md").exists()
    assert (ws / "beta/docs/ai/standards/errors.md").exists()
    assert not (ws / "docs/ai/standards/errors.md").exists()


def test_sor_artifacts_never_moved(tmp_path: Path):
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/standards/errors.md", "same")
    _write(ws, "beta", "docs/ai/standards/errors.md", "same")
    # SoR artifacts in a project.
    plan = _write(ws, "alpha", "docs/ai/plans/001-thing.md", "plan body")
    backlog = _write(ws, "alpha", "docs/ai/backlog.md", "backlog body")

    report = run_migrate_layout(ws, apply=True)

    assert report.exit_code == 0
    assert plan.exists()
    assert backlog.exists()
    assert not (ws / "docs/ai/plans/001-thing.md").exists()
    assert not (ws / "docs/ai/backlog.md").exists()


def test_dirty_worktree_guard(tmp_path: Path):
    if shutil.which("git") is None:
        import pytest

        pytest.skip("git not available")
    ws = _make_ws(tmp_path)
    _write(ws, "alpha", "docs/ai/standards/errors.md", "same")
    _write(ws, "beta", "docs/ai/standards/errors.md", "same")
    subprocess.run(["git", "init"], cwd=str(ws), capture_output=True, check=True)

    # Untracked files make the worktree dirty -> apply refused without --force.
    report = run_migrate_layout(ws, apply=True)
    assert report.exit_code == 3
    assert (ws / "alpha/docs/ai/standards/errors.md").exists()

    # --force overrides the guard.
    forced = run_migrate_layout(ws, apply=True, force=True)
    assert forced.exit_code == 0


def test_idempotent_already_shared(tmp_path: Path):
    ws = _make_ws(tmp_path, layout="shared_workspace")
    report = run_migrate_layout(ws, apply=True)
    assert report.exit_code == 0
    assert report.already_shared is True
