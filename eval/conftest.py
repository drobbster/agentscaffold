"""Shared fixtures for evaluation scenarios."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

SIM_PROJECT = Path(__file__).parent / "sim_project"

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
def sim_project_path_kuzu(tmp_path_factory) -> Path:
    """Separate copy of the simulation project for the KuzuDB-only fixture."""
    tmp = tmp_path_factory.mktemp("sim_kuzu")
    dest = tmp / "sim_project"
    shutil.copytree(SIM_PROJECT, dest)
    return dest


@pytest.fixture(scope="session")
def indexed_sim(sim_project_path) -> tuple:
    """Index the simulation project (KuzuDB) and return (path, store, config).

    Note: run_pipeline closes its own store, so we open a fresh one for queries.
    """
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    db_path = sim_project_path / ".scaffold" / "graph.db"
    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db_path),
        backend="kuzu",
        **_GRAPH_CONFIG_KWARGS,
    )

    run_pipeline(sim_project_path, config)

    store = open_graph(config)
    yield sim_project_path, store, config
    store.close()


@pytest.fixture(scope="session")
def indexed_sim_duckdb(sim_project_path) -> tuple:
    """Index the simulation project (DuckPGQ) and return (path, store, config)."""
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    db_path = sim_project_path / ".scaffold" / "graph_duckpgq.duckdb"
    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db_path),
        backend="duckpgq",
        **_GRAPH_CONFIG_KWARGS,
    )

    run_pipeline(sim_project_path, config)

    store = open_graph(config)
    yield sim_project_path, store, config
    store.close()


@pytest.fixture(
    scope="session",
    params=["kuzu", "duckpgq"],
    ids=["backend=kuzu", "backend=duckpgq"],
)
def indexed_sim_both_backends(
    request,
    sim_project_path,
    sim_project_path_kuzu,
):
    """Parametrized fixture: yields (path, store, config) for each backend.

    KuzuDB uses sim_project_path_kuzu to avoid colliding with indexed_sim's db file.
    DuckPGQ re-uses sim_project_path with a .duckdb file.
    """
    backend = request.param
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    if backend == "kuzu":
        root = sim_project_path_kuzu
        db_path = root / ".scaffold" / "graph_both.db"
    else:
        root = sim_project_path
        db_path = root / ".scaffold" / "graph_duckpgq.duckdb"

    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db_path),
        backend=backend,
        **_GRAPH_CONFIG_KWARGS,
    )

    run_pipeline(root, config)

    store = open_graph(config)
    yield root, store, config
    store.close()


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
