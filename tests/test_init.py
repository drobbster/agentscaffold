"""Tests for the scaffold init command."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app


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


def test_init_creates_agents_md(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates AGENTS.md with content."""
    cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.is_file()
    content = agents_md.read_text()
    assert len(content) > 100
    assert "Agent" in content or "agent" in content


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


def test_init_creates_new_directory(tmp_path: Path, cli_runner: CliRunner) -> None:
    """init creates the target directory if it doesn't exist."""
    new_dir = tmp_path / "brand_new_project"
    result = cli_runner.invoke(app, ["init", str(new_dir), "-y"])
    assert result.exit_code == 0
    assert new_dir.is_dir()
    assert (new_dir / "scaffold.yaml").is_file()
