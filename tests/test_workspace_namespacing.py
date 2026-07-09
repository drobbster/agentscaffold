"""Tests for workspace resolution + project-name validation (Plan 225, Phase 2).

Covers Step 3: workspace config, ``resolve_workspace_root()``, single-project
default (today's behavior), multi-project manifest, and the unique/delimiter-safe
project-name validation. ID-prefixing, scoping, and per-project governance ingest
are exercised in later phases (test_graph_scoping / test_multiproject_safety).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.config import (
    ConfigError,
    ProjectEntry,
    WorkspaceConfig,
    derive_project_name,
    find_workspace_config,
    load_workspace_manifest,
    validate_project_name,
    validate_workspace,
)
from agentscaffold.paths import load_workspace, resolve_workspace_root


def _make_project(root: Path) -> Path:
    """A minimal project dir with a scaffold.yaml + .git marker."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
    (root / ".git").mkdir(exist_ok=True)
    return root


def _make_workspace(root: Path, names: list[str]) -> Path:
    """A workspace.yaml listing *names*, each with a sibling project dir."""
    root.mkdir(parents=True, exist_ok=True)
    lines = ["projects:"]
    for name in names:
        (root / name).mkdir(exist_ok=True)
        lines.append(f"  - name: {name}")
        lines.append(f"    path: {name}")
    (root / "workspace.yaml").write_text("\n".join(lines) + "\n")
    return root


# ---------------------------------------------------------------------------
# Single-project default (backward compatibility)
# ---------------------------------------------------------------------------


def test_single_project_workspace_root_is_project_root(tmp_path):
    proj = _make_project(tmp_path / "myproj")
    assert resolve_workspace_root(proj) == proj.resolve()


def test_single_project_synthesized_workspace(tmp_path):
    proj = _make_project(tmp_path / "myproj")
    ws = load_workspace(proj)
    assert ws.is_multi_project is False
    assert ws.project_names() == ["myproj"]
    assert ws.projects[0].path == str(proj.resolve())


def test_no_workspace_manifest_found(tmp_path):
    proj = _make_project(tmp_path / "myproj")
    assert find_workspace_config(proj) is None


# ---------------------------------------------------------------------------
# Multi-project workspace manifest
# ---------------------------------------------------------------------------


def test_workspace_root_resolves_to_manifest_dir(tmp_path):
    ws_root = _make_workspace(tmp_path / "ws", ["alpha", "beta"])
    # From inside a member project, the workspace root is the manifest dir.
    assert resolve_workspace_root(ws_root / "alpha") == ws_root.resolve()


def test_workspace_manifest_lists_projects(tmp_path):
    ws_root = _make_workspace(tmp_path / "ws", ["alpha", "beta"])
    ws = load_workspace(ws_root / "alpha")
    assert ws.is_multi_project is True
    assert ws.project_names() == ["alpha", "beta"]
    assert ws.find_by_name("beta") is not None
    assert ws.find_by_name("missing") is None


def test_manifest_takes_precedence_over_inner_scaffold(tmp_path):
    ws_root = _make_workspace(tmp_path / "ws", ["alpha"])
    # An inner project also has a scaffold.yaml, but the outer workspace.yaml wins.
    _make_project(ws_root / "alpha")
    assert resolve_workspace_root(ws_root / "alpha") == ws_root.resolve()


# ---------------------------------------------------------------------------
# Project-name validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "  ", "a::b", "has space", "tab\tname", "a'b", 'a"b', "a/b"])
def test_validate_project_name_rejects_invalid(bad):
    with pytest.raises(ConfigError):
        validate_project_name(bad)


@pytest.mark.parametrize("good", ["alpha", "my-project", "svc_api", "p123"])
def test_validate_project_name_accepts_valid(good):
    assert validate_project_name(good) == good


def test_validate_workspace_rejects_duplicate_names(tmp_path):
    ws = WorkspaceConfig(
        projects=[
            ProjectEntry(name="api", path="a/api"),
            ProjectEntry(name="api", path="b/api"),
        ]
    )
    with pytest.raises(ConfigError, match="Duplicate project name"):
        validate_workspace(ws)


def test_validate_workspace_rejects_delimiter_in_name():
    ws = WorkspaceConfig(projects=[ProjectEntry(name="a::b", path="x")])
    with pytest.raises(ConfigError):
        validate_workspace(ws)


def test_load_workspace_manifest_validates(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "workspace.yaml").write_text("projects:\n  - name: a::bad\n    path: x\n")
    with pytest.raises(ConfigError):
        load_workspace_manifest(root / "workspace.yaml")


# ---------------------------------------------------------------------------
# derive_project_name
# ---------------------------------------------------------------------------


def test_derive_project_name_from_basename(tmp_path):
    proj = tmp_path / "rebellion-trading-system"
    proj.mkdir()
    assert derive_project_name(proj) == "rebellion-trading-system"


def test_derive_project_name_explicit_wins(tmp_path):
    proj = tmp_path / "whatever"
    proj.mkdir()
    assert derive_project_name(proj, explicit="custom") == "custom"


def test_derive_project_name_normalizes_whitespace(tmp_path):
    proj = tmp_path / "My Project"
    proj.mkdir()
    assert derive_project_name(proj) == "My-Project"


def test_derive_project_name_rejects_bad_explicit(tmp_path):
    proj = tmp_path / "whatever"
    proj.mkdir()
    with pytest.raises(ConfigError):
        derive_project_name(proj, explicit="a::b")
