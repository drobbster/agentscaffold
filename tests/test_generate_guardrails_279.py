"""Plan 279: generators stop writing files the project does not own.

A project registered inside a company monorepo shares its workspace root with
other teams. The root ``AGENTS.md`` there belongs to whoever owns the monorepo,
so the workspace router is written only where AgentScaffold already manages it
or when the user asks for it. The rest of this file covers the smaller
generator fixes from the same field report: the legacy-routing hint, the empty
security line, and ``agents.claude_md: import``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agentscaffold.config import ScaffoldConfig
from agentscaffold.rendering import MANAGED_BLOCK_BEGIN, MANAGED_BLOCK_END, render_managed_block

TEAM_AGENTS = "# Monorepo agent rules\n\nOwned by the platform team.\n"


def _shared_ws(tmp_path: Path, *, security_dir: str | None = None) -> Path:
    ws = tmp_path / "ws"
    for name in ("alpha", "beta"):
        (ws / name).mkdir(parents=True)
        (ws / name / "scaffold.yaml").write_text(f"framework:\n  project_name: {name}\n")
    layout: dict = {"layout": "shared_workspace"}
    if security_dir is not None:
        layout["shared"] = {"security_dir": security_dir}
    (ws / "workspace.yaml").write_text(
        yaml.safe_dump(
            {
                "projects": [
                    {"name": "alpha", "path": "alpha"},
                    {"name": "beta", "path": "beta"},
                ],
                "asset_layout": layout,
            },
            sort_keys=False,
        )
    )
    return ws


def _generate_all(config: ScaffoldConfig, project_root: Path, **kwargs) -> None:
    from agentscaffold.agents.generate import run_agents_generate_all_platforms

    with patch(
        "agentscaffold.agents.claude.generate_claude_rules",
        return_value="# CLAUDE.md (generated)",
    ):
        run_agents_generate_all_platforms(config, project_root, dry_run=False, **kwargs)


def _managed_inner(text: str) -> list[str]:
    """Non-comment lines inside the managed block."""
    begin = text.index(MANAGED_BLOCK_BEGIN) + len(MANAGED_BLOCK_BEGIN)
    end = text.index(MANAGED_BLOCK_END)
    inner = text[begin:end]
    if "-->" in inner:
        inner = inner[inner.index("-->") + 3 :]
    return [
        line.strip()
        for line in inner.splitlines()
        if line.strip() and not line.strip().startswith("<!--")
    ]


# ---------------------------------------------------------------------------
# Workspace router: written only where AgentScaffold already owns it
# ---------------------------------------------------------------------------


def test_root_agents_owned_by_another_team_is_left_byte_identical(tmp_path: Path):
    ws = _shared_ws(tmp_path)
    (ws / "AGENTS.md").write_text(TEAM_AGENTS)

    _generate_all(ScaffoldConfig(), ws / "alpha")

    assert (ws / "AGENTS.md").read_text() == TEAM_AGENTS
    assert (ws / "alpha" / "AGENTS.md").is_file()


def test_missing_root_agents_is_not_created_by_default(tmp_path: Path):
    ws = _shared_ws(tmp_path)

    _generate_all(ScaffoldConfig(), ws / "alpha")

    assert not (ws / "AGENTS.md").exists()


def test_include_workspace_writes_the_router(tmp_path: Path):
    ws = _shared_ws(tmp_path)
    (ws / "AGENTS.md").write_text(TEAM_AGENTS)

    _generate_all(ScaffoldConfig(), ws / "alpha", include_workspace=True)

    text = (ws / "AGENTS.md").read_text()
    assert text.startswith(TEAM_AGENTS)
    assert "Workspace Router" in text


def test_root_agents_with_our_managed_block_is_still_updated(tmp_path: Path):
    ws = _shared_ws(tmp_path)
    (ws / "AGENTS.md").write_text(
        "# Our workspace\n\nKept.\n\n" + render_managed_block("# Workspace Router (stale)\n")
    )

    _generate_all(ScaffoldConfig(), ws / "alpha")

    text = (ws / "AGENTS.md").read_text()
    assert text.startswith("# Our workspace\n\nKept.\n")
    assert "(stale)" not in text
    assert "alpha" in text and "beta" in text


def test_lone_repo_generate_all_never_touches_a_parent_agents(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text(TEAM_AGENTS)
    project = tmp_path / "solo"
    project.mkdir()
    (project / "scaffold.yaml").write_text("framework:\n  project_name: solo\n")

    _generate_all(ScaffoldConfig(), project)

    assert (tmp_path / "AGENTS.md").read_text() == TEAM_AGENTS


def test_workspace_migrate_skips_a_root_it_does_not_own(tmp_path: Path):
    from agentscaffold.paths import load_workspace
    from agentscaffold.workspace_migrate import _regenerate_agents

    ws = _shared_ws(tmp_path)
    (ws / "AGENTS.md").write_text(TEAM_AGENTS)

    message = _regenerate_agents(ws, load_workspace(ws / "alpha"))

    assert (ws / "AGENTS.md").read_text() == TEAM_AGENTS
    assert message is not None and "--include-workspace" in message


def test_workspace_migrate_updates_a_root_it_owns(tmp_path: Path):
    from agentscaffold.paths import load_workspace
    from agentscaffold.workspace_migrate import _regenerate_agents

    ws = _shared_ws(tmp_path)
    (ws / "AGENTS.md").write_text(render_managed_block("# Workspace Router (stale)\n"))

    _regenerate_agents(ws, load_workspace(ws / "alpha"))

    assert "(stale)" not in (ws / "AGENTS.md").read_text()


def test_workspace_migrate_reports_a_failed_router_write(tmp_path: Path):
    from agentscaffold.paths import load_workspace
    from agentscaffold.workspace_migrate import _regenerate_agents

    ws = _shared_ws(tmp_path)
    (ws / "AGENTS.md").write_text(render_managed_block("# Workspace Router (stale)\n"))

    with patch(
        "agentscaffold.agents.generate.write_workspace_agents_router",
        side_effect=OSError("read-only file system"),
    ):
        message = _regenerate_agents(ws, load_workspace(ws / "alpha"))

    assert message is not None and "read-only file system" in message


# ---------------------------------------------------------------------------
# Legacy unmarked routing: point at repair, not at a third copy
# ---------------------------------------------------------------------------


def test_legacy_unmarked_routing_suggests_repair_prefer_managed(tmp_path: Path):
    from agentscaffold.agents.generate import _render_project_agents_md
    from agentscaffold.rendering import ManagedBlockAppendRefusedError, get_default_context

    project = tmp_path / "solo"
    project.mkdir()
    (project / "scaffold.yaml").write_text("framework:\n  project_name: solo\n")
    config = ScaffoldConfig()
    routing = _render_project_agents_md(config, project, get_default_context(config))
    (project / "AGENTS.md").write_text("## Planning Rules\n\nOurs.\n\n" + routing + "\nEdited.\n")

    with pytest.raises(ManagedBlockAppendRefusedError) as excinfo:
        _generate_all(config, project)

    message = str(excinfo.value)
    assert "repair --prefer-managed" in message
    assert "--allow-append" not in message


# ---------------------------------------------------------------------------
# Empty security_dir renders no security line
# ---------------------------------------------------------------------------


def test_router_omits_an_empty_security_line(tmp_path: Path):
    from agentscaffold.agents.generate import write_workspace_agents_router
    from agentscaffold.paths import load_workspace

    ws = _shared_ws(tmp_path, security_dir="")
    write_workspace_agents_router(ws, load_workspace(ws / "alpha"))

    assert "Security templates" not in (ws / "AGENTS.md").read_text()


def test_project_stub_omits_an_empty_security_line(tmp_path: Path):
    from agentscaffold.agents.generate import _render_project_agents_md
    from agentscaffold.rendering import get_default_context

    ws = _shared_ws(tmp_path, security_dir="")
    config = ScaffoldConfig()
    content = _render_project_agents_md(config, ws / "alpha", get_default_context(config))

    assert "Security templates" not in content


def test_security_line_kept_when_set(tmp_path: Path):
    from agentscaffold.agents.generate import _render_project_agents_md
    from agentscaffold.rendering import get_default_context

    ws = _shared_ws(tmp_path)
    config = ScaffoldConfig()
    content = _render_project_agents_md(config, ws / "alpha", get_default_context(config))

    assert "- Security templates: docs/security/" in content


# ---------------------------------------------------------------------------
# agents.claude_md: import
# ---------------------------------------------------------------------------


def _solo(tmp_path: Path) -> Path:
    project = tmp_path / "solo"
    project.mkdir()
    (project / "scaffold.yaml").write_text("framework:\n  project_name: solo\n")
    return project


def test_claude_md_import_mode_writes_only_the_import(tmp_path: Path):
    project = _solo(tmp_path)
    (project / "CLAUDE.md").write_text("# Team notes\n\nKeep me.\n")

    _generate_all(ScaffoldConfig(agents={"claude_md": "import"}), project)

    text = (project / "CLAUDE.md").read_text()
    assert _managed_inner(text) == ["@AGENTS.md"]
    assert "Keep me." in text


def test_claude_md_switching_back_to_full_restores_the_document(tmp_path: Path):
    project = _solo(tmp_path)

    _generate_all(ScaffoldConfig(agents={"claude_md": "import"}), project)
    _generate_all(ScaffoldConfig(), project)

    inner = _managed_inner((project / "CLAUDE.md").read_text())
    assert "@AGENTS.md" not in inner
    assert "# CLAUDE.md (generated)" in inner


def test_claude_md_import_is_refused_under_a_shared_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    ws = _shared_ws(tmp_path)

    _generate_all(ScaffoldConfig(agents={"claude_md": "import"}), ws / "alpha")

    inner = _managed_inner((ws / "alpha" / "CLAUDE.md").read_text())
    assert "@AGENTS.md" not in inner
    assert "# CLAUDE.md (generated)" in inner
    assert "claude_md" in capsys.readouterr().out


def test_claude_md_defaults_to_full():
    assert ScaffoldConfig().agents.claude_md == "full"
