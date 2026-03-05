"""Shared fixtures for agentscaffold tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentscaffold.cli import app
from agentscaffold.config import ScaffoldConfig

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_REPO = FIXTURES_DIR / "sample_repo"


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


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    """Copy sample_repo fixture into tmp_path, return path."""
    dest = tmp_path / "repo"
    shutil.copytree(SAMPLE_REPO, dest)
    return dest


@pytest.fixture()
def graph_store(tmp_path: Path):
    """Create a fresh GraphStore in a temp directory."""
    try:
        from agentscaffold.graph.store import GraphStore
    except ImportError:
        pytest.skip("kuzu not installed")

    db_path = tmp_path / "test.db"
    store = GraphStore(db_path)
    store.init_schema()
    yield store
    store.close()


@pytest.fixture()
def indexed_repo(fixture_repo: Path, tmp_path: Path):
    """fixture_repo with graph already built. Returns (repo_path, store)."""
    try:
        from agentscaffold.graph.pipeline import run_pipeline
        from agentscaffold.graph.store import GraphStore
    except ImportError:
        pytest.skip("kuzu not installed")

    db_path = tmp_path / "graph.db"
    from agentscaffold.config import GraphConfig

    config = type("FakeConfig", (), {"graph": GraphConfig(db_path=str(db_path))})()
    run_pipeline(root=fixture_repo, config=config)
    store = GraphStore(db_path)
    yield fixture_repo, store
    store.close()
