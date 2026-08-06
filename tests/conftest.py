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


@pytest.fixture(autouse=True)
def isolate_agentscaffold_home(tmp_path_factory, monkeypatch) -> Path:
    """Point ``AGENTSCAFFOLD_HOME`` at a temp dir for every test.

    Autouse and unconditional, because the failure it prevents is not local. The
    user-level registry is real shared state: once ``scaffold workspace onboard``
    began mirroring into it (Plan 249, Step A8), the pre-existing onboard tests
    silently wrote ``alpha`` and ``beta`` into the developer's own
    ``~/.agentscaffold/registry.yaml``, pointing at temp directories that no
    longer existed.

    The damage then surfaced two files away, as ``test_graph_read_during_refresh``
    failing with ``ambiguous_project`` -- because dispatch could now see two
    registered projects and correctly refused to guess between them. A test that
    corrupts developer state and breaks an unrelated suite is worth preventing
    structurally rather than by asking each new test to remember.
    """
    home = tmp_path_factory.mktemp("agentscaffold-home")
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(home))
    return home


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
def any_store(tmp_path: Path):
    """Yield a DuckPGQBackend instance for tests."""
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    store = DuckPGQBackend(":memory:")
    store.init_schema()
    yield store
    store.close()


@pytest.fixture(scope="session")
def _built_two_project_workspace(tmp_path_factory):
    """Build and index the two-project workspace once for the whole session.

    Indexing twice per test would dominate the conformance suite's runtime, and
    the workspace is read-only for every test that shares it. Tests that write
    must use :func:`scratch_two_project_workspace`, which gets its own copy.
    """
    from tests.fixtures.multiproject import build_two_project_workspace, index_workspace

    workspace = build_two_project_workspace(tmp_path_factory.mktemp("multiproject") / "ws")
    index_workspace(workspace)
    return workspace


@pytest.fixture()
def two_project_workspace(_built_two_project_workspace, monkeypatch):
    """The shared workspace, registered into this test's isolated registry.

    Registration is per test rather than per session because
    ``isolate_agentscaffold_home`` gives every test a fresh registry -- which is
    the point, and cheap enough to redo.
    """
    from agentscaffold.workspace_registry import register_workspace
    from tests.fixtures.multiproject import ALPHA, BETA

    workspace = _built_two_project_workspace
    register_workspace(workspace.alpha, name=ALPHA)
    register_workspace(workspace.beta, name=BETA)
    return workspace


@pytest.fixture()
def scratch_two_project_workspace(tmp_path):
    """An unshared, unindexed two-project workspace for tests that mutate.

    Separate from :func:`two_project_workspace` so a write test cannot leave the
    shared graph in a state the next test reads.
    """
    from agentscaffold.workspace_registry import register_workspace
    from tests.fixtures.multiproject import build_two_project_workspace

    # Distinct names: the registry requires them to be unique across every
    # workspace, so a test holding both this and the shared fixture would
    # otherwise collide on `alpha`.
    workspace = build_two_project_workspace(
        tmp_path / "scratch-ws", alpha_name="scratch-alpha", beta_name="scratch-beta"
    )
    register_workspace(workspace.alpha, name=workspace.alpha_name)
    register_workspace(workspace.beta, name=workspace.beta_name)
    return workspace


@pytest.fixture()
def indexed_repo(fixture_repo: Path, tmp_path: Path):
    """fixture_repo with graph already built. Returns (repo_path, store)."""
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.pipeline import run_pipeline

    db_path = tmp_path / "graph.duckdb"
    from agentscaffold.config import GraphConfig

    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path), backend="duckpgq")
    run_pipeline(root=fixture_repo, config=config)
    store = DuckPGQBackend(db_path)
    yield fixture_repo, store
    store.close()
