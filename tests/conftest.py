"""Shared fixtures for agentscaffold tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentscaffold.cli import app
from agentscaffold.config import ScaffoldConfig


@pytest.fixture()
def cli_runner() -> CliRunner:
    """Return a typer CliRunner for invoking CLI commands."""
    return CliRunner()


@pytest.fixture()
def config() -> ScaffoldConfig:
    """Return a default ScaffoldConfig instance."""
    return ScaffoldConfig()


@pytest.fixture()
def tmp_project(tmp_path: Path, cli_runner: CliRunner) -> Path:
    """Create a scaffolded project in a temp directory and return its path.

    Runs ``scaffold init -y`` inside *tmp_path* then restores the original
    working directory on teardown.
    """
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["init", str(tmp_path), "-y"])
        assert result.exit_code == 0, f"scaffold init failed:\n{result.output}"
    finally:
        os.chdir(orig_cwd)
    return tmp_path
