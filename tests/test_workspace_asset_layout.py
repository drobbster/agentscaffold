"""Tests for the workspace asset-layout schema + path resolution (Plan 234).

Covers the ``asset_layout`` config models, ``effective_asset_layout`` defaulting,
and the ``ResolvedPaths`` shared/project dual-anchor behavior (including the
project-local ``graph.*`` escape hatch and backward compatibility).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.config import (
    AssetLayoutConfig,
    ProjectEntry,
    ScaffoldConfig,
    WorkspaceConfig,
    effective_asset_layout,
)
from agentscaffold.paths import ResolvedPaths

# ---------------------------------------------------------------------------
# Schema defaults + validation
# ---------------------------------------------------------------------------


def test_asset_layout_defaults_project_local():
    layout = AssetLayoutConfig()
    assert layout.layout == "project_local"
    assert layout.shared.prompts_dir == "docs/ai/prompts/"
    assert layout.project.plans_dir == "docs/ai/plans/"


def test_workspace_asset_layout_optional_defaults_none():
    ws = WorkspaceConfig(projects=[ProjectEntry(name="a", path="a")])
    assert ws.asset_layout is None
    assert ws.is_shared_workspace is False


def test_effective_asset_layout_defaults_when_none():
    ws = WorkspaceConfig(projects=[ProjectEntry(name="a", path="a")])
    layout = effective_asset_layout(ws)
    assert layout.layout == "project_local"


def test_effective_asset_layout_returns_configured():
    ws = WorkspaceConfig(
        projects=[ProjectEntry(name="a", path="a")],
        asset_layout=AssetLayoutConfig(layout="shared_workspace"),
    )
    assert ws.is_shared_workspace is True
    assert effective_asset_layout(ws).layout == "shared_workspace"


def test_invalid_layout_rejected():
    with pytest.raises(ValueError):
        AssetLayoutConfig(layout="bogus")


def test_workspace_manifest_parses_asset_layout(tmp_path: Path):
    from agentscaffold.config import load_workspace_manifest

    manifest = tmp_path / "workspace.yaml"
    manifest.write_text(
        "projects:\n"
        "  - name: a\n    path: a\n"
        "  - name: b\n    path: b\n"
        "asset_layout:\n"
        "  layout: shared_workspace\n"
    )
    ws = load_workspace_manifest(manifest)
    assert ws.is_shared_workspace is True


# ---------------------------------------------------------------------------
# ResolvedPaths dual-anchor resolution
# ---------------------------------------------------------------------------


def _shared_workspace(project_name: str = "alpha") -> WorkspaceConfig:
    return WorkspaceConfig(
        projects=[
            ProjectEntry(name=project_name, path=project_name),
            ProjectEntry(name="beta", path="beta"),
        ],
        asset_layout=AssetLayoutConfig(layout="shared_workspace"),
    )


def test_shared_workspace_resolves_process_assets_at_workspace_root(tmp_path: Path):
    ws_root = tmp_path / "ws"
    project_root = ws_root / "alpha"
    paths = ResolvedPaths(
        ScaffoldConfig(),
        project_root,
        workspace=_shared_workspace(),
        workspace_root=ws_root,
    )
    assert paths.prompts_dir == ws_root / "docs/ai/prompts/"
    assert paths.standards_dir == ws_root / "docs/ai/standards/"
    assert paths.templates_dir == ws_root / "docs/ai/templates/"
    assert paths.security_dir == ws_root / "docs/security/"
    assert paths.collaboration_protocol_file == ws_root / "docs/ai/collaboration_protocol.md"
    assert paths.commands_file == ws_root / "docs/ai/commands.md"


def test_shared_workspace_keeps_sor_project_local(tmp_path: Path):
    ws_root = tmp_path / "ws"
    project_root = ws_root / "alpha"
    paths = ResolvedPaths(
        ScaffoldConfig(),
        project_root,
        workspace=_shared_workspace(),
        workspace_root=ws_root,
    )
    assert paths.plans_dir == project_root.resolve() / "docs/ai/plans/"
    assert paths.contracts_dir == project_root.resolve() / "docs/ai/contracts/"
    assert paths.adrs_dir == project_root.resolve() / "docs/ai/adrs/"
    assert paths.backlog_file == project_root.resolve() / "docs/ai/backlog.md"


def test_project_local_resolves_everything_at_project_root(tmp_path: Path):
    ws_root = tmp_path / "ws"
    project_root = ws_root / "alpha"
    ws = WorkspaceConfig(projects=[ProjectEntry(name="alpha", path="alpha")])
    paths = ResolvedPaths(ScaffoldConfig(), project_root, workspace=ws, workspace_root=ws_root)
    assert paths.prompts_dir == project_root.resolve() / "docs/ai/prompts/"
    assert paths.standards_dir == project_root.resolve() / "docs/ai/standards/"


def test_no_workspace_is_backward_compatible(tmp_path: Path):
    project_root = tmp_path / "proj"
    paths = ResolvedPaths(ScaffoldConfig(), project_root)
    assert paths.prompts_dir == project_root.resolve() / "docs/ai/prompts/"
    assert paths.standards_dir == project_root.resolve() / "docs/ai/standards/"


def test_customized_graph_dir_is_escape_hatch(tmp_path: Path):
    """A project that customized graph.standards_dir stays project-local even shared."""
    ws_root = tmp_path / "ws"
    project_root = ws_root / "alpha"
    config = ScaffoldConfig()
    config.graph.standards_dir = "custom/standards/"
    paths = ResolvedPaths(
        config,
        project_root,
        workspace=_shared_workspace(),
        workspace_root=ws_root,
    )
    # Customized field honored at the project root; the escape hatch wins.
    assert paths.standards_dir == project_root.resolve() / "custom/standards/"
    # A non-customized field still resolves to the shared workspace root.
    assert paths.prompts_dir == ws_root / "docs/ai/prompts/"
