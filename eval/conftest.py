"""Shared fixtures for evaluation scenarios."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

SIM_PROJECT = Path(__file__).parent / "sim_project"


@pytest.fixture(scope="session")
def sim_project_path(tmp_path_factory) -> Path:
    """Copy the simulation project to a temp directory."""
    tmp = tmp_path_factory.mktemp("sim")
    dest = tmp / "sim_project"
    shutil.copytree(SIM_PROJECT, dest)
    return dest


@pytest.fixture(scope="session")
def indexed_sim(sim_project_path) -> tuple:
    """Index the simulation project and return (path, store, config).

    Note: run_pipeline closes its own store, so we open a fresh one for queries.
    """
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph.pipeline import run_pipeline
    from agentscaffold.graph.store import GraphStore

    db_path = sim_project_path / ".scaffold" / "graph.db"
    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db_path),
        plans_dir="docs/ai/plans/",
        contracts_dir="docs/ai/contracts/",
        learnings_file="docs/ai/state/learnings_tracker.md",
    )

    # Pipeline opens and closes its own store
    run_pipeline(sim_project_path, config)

    # Open a fresh store for test queries
    store = GraphStore(db_path)
    yield sim_project_path, store, config
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
