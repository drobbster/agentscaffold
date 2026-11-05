"""Tests for CI setup and task runner generation."""

from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from agentscaffold.cli import app


def test_ci_setup_github(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CI setup generates .github/workflows/ci.yml."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["ci"])
        assert result.exit_code == 0

        ci_yml = tmp_project / ".github" / "workflows" / "ci.yml"
        assert ci_yml.is_file()
        content = ci_yml.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_ci_setup_security(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CI setup generates security.yml when security_scanning is enabled."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["ci"])
        assert result.exit_code == 0

        # security_scanning defaults to True
        sec_yml = tmp_project / ".github" / "workflows" / "security.yml"
        assert sec_yml.is_file()
        content = sec_yml.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_ci_setup_no_config(tmp_path: Path, cli_runner: CliRunner) -> None:
    """CI setup without scaffold.yaml fails gracefully."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["ci"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_justfile(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner generates justfile."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "justfile"])
        assert result.exit_code == 0

        justfile = tmp_project / "justfile"
        assert justfile.is_file()
        content = justfile.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_makefile(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner generates Makefile."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "makefile"])
        assert result.exit_code == 0

        makefile = tmp_project / "Makefile"
        assert makefile.is_file()
        content = makefile.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_both(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner with 'both' generates both justfile and Makefile."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "both"])
        assert result.exit_code == 0

        assert (tmp_project / "justfile").is_file()
        assert (tmp_project / "Makefile").is_file()
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_no_config(tmp_path: Path, cli_runner: CliRunner) -> None:
    """taskrunner without scaffold.yaml fails gracefully."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["taskrunner"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_invalid_format(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner with invalid format fails."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "invalid"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_ci_template_runs_the_inventory_check_when_enabled() -> None:
    """Inventory check, and INV-008 over a pull request's changed files."""
    import yaml

    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.rendering import get_default_context, render_template

    config = ScaffoldConfig()
    assert "inventory" not in render_template("ci/github_ci.yml.j2", get_default_context(config))

    config.inventory.enabled = True
    text = render_template("ci/github_ci.yml.j2", get_default_context(config))
    steps = {s["name"]: s for s in yaml.safe_load(text)["jobs"]["test"]["steps"] if "name" in s}
    assert steps["System inventory"]["run"] == "scaffold inventory check"
    changed = steps["Paused or deprecated components changed (INV-008)"]
    assert changed["if"] == "github.event_name == 'pull_request'"
    assert "origin/${{ github.base_ref }}" in changed["run"]
    assert "scaffold inventory check --changed-files -" in changed["run"]
