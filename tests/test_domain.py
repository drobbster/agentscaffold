"""Tests for domain pack system (list and add)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app
from agentscaffold.domain_packs.loader import _get_available_packs

EXPECTED_PACKS = [
    "api_services",
    "data_engineering",
    "embedded",
    "game_dev",
    "infrastructure",
    "mlops",
    "mobile",
    "research",
    "trading",
    "webapp",
]


def test_domain_list(cli_runner: CliRunner) -> None:
    """domains list shows all 10 available packs."""
    result = cli_runner.invoke(app, ["domains", "list"])
    assert result.exit_code == 0
    for pack in EXPECTED_PACKS:
        assert pack in result.output, f"Missing pack in list: {pack}"


def test_available_packs_count() -> None:
    """Verify there are exactly 10 domain packs available."""
    packs = _get_available_packs()
    assert len(packs) == 10
    assert packs == EXPECTED_PACKS


def test_domain_add_trading(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Add the trading domain pack and verify files are copied."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["domains", "add", "trading"])
        assert result.exit_code == 0
        assert "installed" in result.output.lower()

        # Verify domain files were written
        prompts_dir = tmp_project / "docs/ai/prompts"
        standards_dir = tmp_project / "docs/ai/standards"
        assert prompts_dir.is_dir()
        assert standards_dir.is_dir()

        # At least some trading-specific files should exist
        prompt_files = list(prompts_dir.glob("*"))
        standard_files = list(standards_dir.glob("*"))
        assert len(prompt_files) > 0
        assert len(standard_files) > 0

        # scaffold.yaml should be updated with the domain
        yaml_path = tmp_project / "scaffold.yaml"
        data = yaml.safe_load(yaml_path.read_text())
        assert "trading" in data.get("domains", [])
    finally:
        os.chdir(orig_cwd)


def test_domain_add_unknown_pack(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Adding an unknown pack prints an error."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["domains", "add", "nonexistent_pack"])
        assert result.exit_code == 0  # handled gracefully
        assert "Unknown" in result.output or "unknown" in result.output.lower()
    finally:
        os.chdir(orig_cwd)


def test_domain_add_webapp(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Add the webapp domain pack and verify files are installed."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["domains", "add", "webapp"])
        assert result.exit_code == 0

        yaml_path = tmp_project / "scaffold.yaml"
        data = yaml.safe_load(yaml_path.read_text())
        assert "webapp" in data.get("domains", [])
    finally:
        os.chdir(orig_cwd)


def test_domain_alias_still_works(cli_runner: CliRunner) -> None:
    """Legacy `domain` command alias remains supported."""
    result = cli_runner.invoke(app, ["domain", "list"])
    assert result.exit_code == 0
    assert "Available Domain Packs" in result.output
