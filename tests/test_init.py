"""Tests for the scaffold init command."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app


@pytest.fixture(autouse=True)
def isolated_client_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real ``~/.cursor/mcp.json`` out of these results.

    ``init`` generates a per-project MCP config only when no shared server
    already covers the repo, so without this the suite would pass or fail
    depending on whether whoever runs it has run ``scaffold mcp install`` —
    green on a fresh checkout and red on a maintainer's laptop.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "clean-home"))


def test_init_creates_structure(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates expected directories and files."""
    result = cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    assert result.exit_code == 0

    expected_dirs = [
        "docs/ai/templates",
        "docs/ai/prompts",
        "docs/ai/standards",
        "docs/ai/state",
        "docs/ai/contracts",
        "docs/ai/plans",
        "docs/ai/spikes",
        "docs/ai/adrs",
        "docs/runbook",
        "docs/studies",
        "docs/security",
    ]
    for d in expected_dirs:
        assert (tmp_path / d).is_dir(), f"Missing directory: {d}"


def test_init_shared_workspace_splits_assets(tmp_path: Path, cli_runner: CliRunner) -> None:
    """Init into a shared_workspace writes process assets once at the workspace root."""
    ws = tmp_path / "ws"
    project = ws / "alpha"
    project.mkdir(parents=True)
    ws_manifest = ws / "workspace.yaml"
    ws_manifest.write_text(
        "projects:\n  - name: alpha\n    path: alpha\n  - name: beta\n    path: beta\n"
        "asset_layout:\n  layout: shared_workspace\n"
    )

    result = cli_runner.invoke(app, ["init", str(project), "-y"])
    assert result.exit_code == 0

    # Reusable process assets land at the workspace root (shared once).
    assert (ws / "docs/ai/standards/errors.md").is_file()
    assert (ws / "docs/ai/prompts/plan_critique.md").is_file()
    assert (ws / "docs/ai/collaboration_protocol.md").is_file()
    assert (ws / "docs/ai/commands.md").is_file()
    # Project system-of-record artifacts stay under the project root.
    assert (project / "docs/ai/backlog.md").is_file()
    assert (project / "docs/ai/product_vision.md").is_file()
    assert (project / "docs/ai/system_architecture.md").is_file()
    # And are NOT duplicated at the workspace root.
    assert not (ws / "docs/ai/backlog.md").exists()
    assert not (project / "docs/ai/standards/errors.md").exists()


@pytest.mark.smoke
def test_init_agents_md_has_no_duplicate_headings(tmp_path: Path, cli_runner: CliRunner) -> None:
    """The Critical defect: init must not write every heading twice."""
    result = cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    assert result.exit_code == 0
    content = (tmp_path / "AGENTS.md").read_text()
    headings = [line for line in content.splitlines() if line.startswith("## ")]
    assert headings
    assert len(headings) == len(set(headings))
    assert "Session Working Rhythm" in content
    assert "Planning Rules" in content
    assert "agentscaffold-manual" in content


def test_init_creates_agents_md(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates AGENTS.md with content."""
    cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.is_file()
    content = agents_md.read_text()
    assert len(content) > 100
    assert "Agent" in content or "agent" in content


def test_init_manual_uses_configured_paths(tmp_path: Path, cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    assert result.exit_code == 0
    yaml_path = tmp_path / "scaffold.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    data.setdefault("graph", {})["plans_dir"] = "docs/custom/plans/"
    data["graph"]["adrs_dir"] = "docs/custom/adrs/"
    yaml_path.write_text(yaml.dump(data))
    # Re-render by deleting AGENTS.md and writing the manual from current config.
    from agentscaffold.agents.manual_diff import render_governance_manual, stamp_manual
    from agentscaffold.config import load_config

    (tmp_path / "AGENTS.md").unlink()
    config = load_config(yaml_path)
    (tmp_path / "AGENTS.md").write_text(stamp_manual(render_governance_manual(config)))
    text = (tmp_path / "AGENTS.md").read_text()
    assert "docs/custom/plans/" in text
    assert "docs/custom/adrs/" in text


def test_init_creates_scaffold_yaml(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates scaffold.yaml with the project name from the directory."""
    cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    yaml_file = tmp_path / "scaffold.yaml"
    assert yaml_file.is_file()
    data = yaml.safe_load(yaml_file.read_text())
    assert data["framework"]["project_name"] == tmp_path.resolve().name


def test_init_creates_cursor_rules(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates .cursor/rules.md."""
    cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    rules_md = tmp_path / ".cursor" / "rules.md"
    assert rules_md.is_file()
    content = rules_md.read_text()
    assert len(content) > 0


def test_init_idempotent(tmp_path: Path, cli_runner: CliRunner) -> None:
    """Running init twice does not overwrite existing files."""
    cli_runner.invoke(app, ["init", str(tmp_path), "-y"])

    agents_md = tmp_path / "AGENTS.md"
    original_content = agents_md.read_text()
    agents_md.write_text(original_content + "\n# Custom addition\n")

    result = cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    assert result.exit_code == 0

    content_after = agents_md.read_text()
    assert "# Custom addition" in content_after


def test_init_non_interactive(tmp_path: Path, cli_runner: CliRunner) -> None:
    """The -y flag skips all prompts and uses defaults."""
    result = cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    assert result.exit_code == 0
    assert "Initialization complete" in result.output


def test_init_creates_templated_files(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates key template files from the template map."""
    cli_runner.invoke(app, ["init", str(tmp_path), "-y"])

    expected_files = [
        "docs/ai/templates/plan_template.md",
        "docs/ai/templates/spike_template.md",
        "docs/ai/templates/study_template.md",
        "docs/ai/prompts/plan_critique.md",
        "docs/ai/standards/errors.md",
        "docs/ai/standards/testing.md",
        "docs/ai/state/workflow_state.md",
        "docs/ai/backlog.md",
        "docs/ai/contracts/README.md",
        "docs/ai/system_architecture.md",
        "docs/security/threat_model_template.md",
    ]
    for f in expected_files:
        assert (tmp_path / f).is_file(), f"Missing file: {f}"


def test_init_generates_full_rule_set(tmp_path: Path, cli_runner: CliRunner) -> None:
    """A fresh init generates the complete platform rule set, including the
    MCP routing / graph trust-discipline doc that drives context-blindness
    mitigation.

    The init target is a subdirectory and the process cwd is an isolated,
    config-free directory. This guards against generation paths that rely on
    ``find_config()``/cwd instead of the project root passed by init.
    """
    target = tmp_path / "proj"
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["init", str(target), "-y"])
        assert result.exit_code == 0
    finally:
        os.chdir(orig_cwd)

    for rel in (
        ".cursor/rules.md",
        ".cursor/rules/agentscaffold.mdc",
        ".cursor/mcp.json",
        "CLAUDE.md",
        ".windsurfrules",
    ):
        assert (target / rel).is_file(), f"Missing generated rule file: {rel}"

    intent = (target / ".cursor/rules/agentscaffold.mdc").read_text().lower()
    assert "graph trust discipline" in intent
    assert "tool selection policy" in intent
    assert "intent map" in intent


def test_init_creates_new_directory(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates the target directory if it doesn't exist."""
    new_dir = tmp_path / "brand_new_project"
    result = cli_runner.invoke(app, ["init", str(new_dir), "-y"])
    assert result.exit_code == 0
    assert new_dir.is_dir()
    assert (new_dir / "scaffold.yaml").is_file()
