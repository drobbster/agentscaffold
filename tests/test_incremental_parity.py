"""Scoped incremental parity tests for Plan 231."""

from __future__ import annotations

import shutil
from pathlib import Path

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


def _config(db_path: Path) -> ScaffoldConfig:
    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))
    return config


def _edge_counts(db_path: Path) -> tuple[int, int]:
    store = DuckPGQBackend(db_path)
    try:
        imports = int(store.query_scalar("SELECT COUNT(*) FROM IMPORTS") or 0)
        calls = int(store.query_scalar("SELECT COUNT(*) FROM CALLS") or 0)
        return imports, calls
    finally:
        store.close()


def test_incremental_signature_edit_matches_full_reindex_edge_counts(tmp_path: Path) -> None:
    incremental_repo = tmp_path / "incremental"
    full_repo = tmp_path / "full"
    shutil.copytree(FIXTURE_REPO, incremental_repo)
    shutil.copytree(FIXTURE_REPO, full_repo)

    inc_db = tmp_path / "incremental.duckdb"
    full_db = tmp_path / "full.duckdb"
    inc_config = _config(inc_db)
    full_config = _config(full_db)

    run_pipeline(incremental_repo, inc_config)

    target = next(incremental_repo.rglob("*.py"))
    rel = target.relative_to(incremental_repo)
    target.write_text(target.read_text() + "\n\ndef parity_added_function():\n    return 1\n")
    (full_repo / rel).write_text(
        (full_repo / rel).read_text() + "\n\ndef parity_added_function():\n    return 1\n"
    )

    run_pipeline(incremental_repo, inc_config, incremental=True)
    run_pipeline(full_repo, full_config)

    assert _edge_counts(inc_db) == _edge_counts(full_db)
