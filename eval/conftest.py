"""Shared fixtures for evaluation scenarios."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

SIM_PROJECT = Path(__file__).parent / "sim_project"
SIM_PROJECT_B = Path(__file__).parent / "sim_project_b"

_GRAPH_CONFIG_KWARGS = dict(
    plans_dir="docs/ai/plans/",
    contracts_dir="docs/ai/contracts/",
    learnings_file="docs/ai/state/learnings_tracker.md",
    studies_dir="docs/studies/",
    adrs_dir="docs/ai/adrs/",
    spikes_dir="docs/ai/spikes/",
    workflow_state_file="docs/ai/state/workflow_state.md",
)


@pytest.fixture(scope="session")
def sim_project_path(tmp_path_factory) -> Path:
    """Copy the simulation project to a temp directory."""
    tmp = tmp_path_factory.mktemp("sim")
    dest = tmp / "sim_project"
    shutil.copytree(SIM_PROJECT, dest)
    return dest


@pytest.fixture(scope="session")
def sim_project_path_duckdb(tmp_path_factory) -> Path:
    """Separate copy of the simulation project for the indexed_sim_duckdb fixture."""
    tmp = tmp_path_factory.mktemp("sim_duckdb")
    dest = tmp / "sim_project"
    shutil.copytree(SIM_PROJECT, dest)
    return dest


@pytest.fixture(scope="session")
def indexed_sim(sim_project_path) -> tuple:
    """Index the simulation project (DuckPGQ) and return (path, store, config).

    Note: run_pipeline closes its own store, so we open a fresh one for queries.
    """
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    db_path = sim_project_path / ".scaffold" / "graph.duckdb"
    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db_path),
        governance_artifact=str(sim_project_path / "docs/ai/state/governance.json"),
        backend="duckpgq",
        **_GRAPH_CONFIG_KWARGS,
    )
    # Disable async freshness to prevent background workers from clobbering
    # the DuckPGQ property graph (which is process-global).
    config.freshness.async_enabled = False

    run_pipeline(sim_project_path, config)

    store = open_graph(config)
    yield sim_project_path, store, config
    store.close()


@pytest.fixture(scope="session")
def indexed_sim_duckdb(sim_project_path_duckdb) -> tuple:
    """Index the simulation project (DuckPGQ) with an isolated database file."""
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    db_path = sim_project_path_duckdb / ".scaffold" / "graph_duckdb.duckdb"
    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db_path),
        governance_artifact=str(sim_project_path_duckdb / "docs/ai/state/governance.json"),
        backend="duckpgq",
        **_GRAPH_CONFIG_KWARGS,
    )
    # Disable async freshness to prevent background workers from clobbering
    # the DuckPGQ property graph (which is process-global).
    config.freshness.async_enabled = False

    run_pipeline(sim_project_path_duckdb, config)

    store = open_graph(config)
    yield sim_project_path_duckdb, store, config
    store.close()


@pytest.fixture(scope="session")
def indexed_two_project_workspace(tmp_path_factory) -> tuple:
    """Index two sibling projects into one shared workspace graph cache."""
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    workspace = tmp_path_factory.mktemp("multi_project")
    project_a = workspace / "sim_project"
    project_b = workspace / "sim_project_b"
    shutil.copytree(SIM_PROJECT, project_a)
    shutil.copytree(SIM_PROJECT_B, project_b)
    (workspace / "workspace.yaml").write_text(
        "\n".join(
            [
                "projects:",
                "  - name: sim_project",
                "    path: sim_project",
                "  - name: sim_project_b",
                "    path: sim_project_b",
                "",
            ]
        ),
        encoding="utf-8",
    )

    db_path = workspace / ".scaffold" / "graph.duckdb"
    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db_path),
        governance_artifact=str(workspace / ".scaffold" / "governance.json"),
        backend="duckpgq",
        **_GRAPH_CONFIG_KWARGS,
    )
    config.freshness.async_enabled = False

    run_pipeline(project_a, config)
    run_pipeline(project_b, config)

    store = open_graph(config)
    yield workspace, project_a, project_b, store, config
    store.close()


def _available_backends():
    return ["duckpgq"]


@pytest.fixture(
    scope="session",
    params=_available_backends(),
    ids=[f"backend={b}" for b in _available_backends()],
)
def indexed_sim_both_backends(
    request,
    indexed_sim,
):
    """Parametrized fixture: yields (path, store, config) for the duckpgq backend.

    Reuses indexed_sim to avoid DuckPGQ property graph conflicts: DuckPGQ property
    graphs are process-global, so running a second pipeline (DROP+CREATE) would
    clobber the shared store's graph registration.
    """
    return indexed_sim


@pytest.fixture()
def fresh_sim(tmp_path) -> Path:
    """A fresh copy of the simulation project (not indexed)."""
    dest = tmp_path / "sim_project"
    shutil.copytree(SIM_PROJECT, dest)
    return dest


@pytest.fixture()
def baseline_config():
    """Config with no graph -- for A/B baseline comparisons."""
    from agentscaffold.config import ScaffoldConfig

    return ScaffoldConfig()
