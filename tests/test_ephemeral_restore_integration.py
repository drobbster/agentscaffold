"""Integration tests for durable/ephemeral storage (Plan 223).

Verifies that on a fresh/ephemeral cache, ``scaffold index`` rebuilds the graph
and restores governance from the committed artifact, and that the
``AGENTSCAFFOLD_DB_PATH`` override redirects the cache end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.config import GraphConfig, ScaffoldConfig  # noqa: E402
from agentscaffold.graph import open_graph  # noqa: E402
from agentscaffold.graph.findings import record_finding  # noqa: E402
from agentscaffold.graph.pipeline import run_pipeline  # noqa: E402
from agentscaffold.paths import DB_PATH_ENV_VAR, resolve_db_path  # noqa: E402


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "scaffold.yaml").write_text(
        "framework:\n  project_name: eph\n  architecture_layers: 3\n"
    )
    src = proj / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 1\n")
    return proj


def _config(proj: Path) -> ScaffoldConfig:
    cfg = ScaffoldConfig()
    cfg.graph = GraphConfig(
        db_path=str(proj / ".scaffold" / "graph.duckdb"),
        governance_artifact=str(proj / "docs" / "ai" / "state" / "governance.json"),
    )
    return cfg


def _delete_cache(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    wal = db_path.with_suffix(db_path.suffix + ".wal")
    if wal.exists():
        wal.unlink()


def test_fresh_cache_restores_from_artifact(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    config = _config(proj)

    run_pipeline(proj, config)
    store = open_graph(config)
    try:
        record_finding(
            store,
            plan_number=11,
            review_type="manual",
            category="design",
            finding="survives the devbox",
            severity="medium",
        )
    finally:
        store.close()

    # Ephemeral teardown: nuke the cache, keep the committed artifact.
    _delete_cache(Path(config.graph.db_path))
    assert Path(config.graph.governance_artifact).is_file()

    summary = run_pipeline(proj, config)
    assert summary["restored_from_artifact"] is True

    store2 = open_graph(config)
    try:
        assert store2.node_count("ReviewFinding") >= 1
    finally:
        store2.close()


def test_existing_cache_does_not_flag_restore(tmp_path: Path) -> None:
    """A normal re-index over an existing cache is not flagged as a restore."""
    proj = _project(tmp_path)
    config = _config(proj)

    run_pipeline(proj, config)
    summary = run_pipeline(proj, config)
    assert summary["restored_from_artifact"] is False


def test_db_path_env_override_redirects_cache(tmp_path: Path, monkeypatch) -> None:
    proj = _project(tmp_path)
    config = _config(proj)

    scratch = tmp_path / "scratch" / "graph.duckdb"
    monkeypatch.setenv(DB_PATH_ENV_VAR, str(scratch))

    assert resolve_db_path(config, start=proj) == scratch
    run_pipeline(proj, config)

    assert scratch.is_file()
    # The config's nominal db_path was overridden, so nothing was written there.
    assert not (proj / ".scaffold" / "graph.duckdb").exists()

    store = open_graph(config)
    try:
        assert store.node_count("File") >= 1
    finally:
        store.close()
