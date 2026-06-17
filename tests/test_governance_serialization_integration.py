"""Integration tests for git-backed governance serialization (Plan 222).

Verifies the end-to-end property: governance recorded at runtime is serialized to
the committed artifact, and a rebuilt graph (fresh DB) reproduces it from the
artifact plus code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.config import GraphConfig, ScaffoldConfig  # noqa: E402
from agentscaffold.graph import open_graph  # noqa: E402
from agentscaffold.graph.findings import record_finding  # noqa: E402
from agentscaffold.graph.governance_store import resolve_governance_artifact  # noqa: E402
from agentscaffold.graph.pipeline import run_pipeline  # noqa: E402

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "scaffold.yaml").write_text(
        "framework:\n  project_name: gov\n  architecture_layers: 3\n"
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


def test_record_serializes_then_rebuild_reproduces(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    config = _config(proj)

    run_pipeline(proj, config)

    # Record a finding at runtime via the write-through-enabled store.
    store = open_graph(config)
    try:
        record_finding(
            store,
            plan_number=99,
            review_type="manual",
            category="design",
            finding="durable knowledge",
            severity="high",
        )
    finally:
        store.close()

    artifact = Path(config.graph.governance_artifact)
    assert artifact.is_file(), "write-through should have created the artifact"

    # Simulate a fresh devbox: delete the cache, rebuild from code + artifact.
    db_file = Path(config.graph.db_path)
    if db_file.exists():
        db_file.unlink()
    wal = db_file.with_suffix(db_file.suffix + ".wal")
    if wal.exists():
        wal.unlink()

    summary = run_pipeline(proj, config)
    assert summary["governance"]["governance_restored"] >= 1

    store2 = open_graph(config)
    try:
        assert store2.node_count("ReviewFinding") >= 1
    finally:
        store2.close()


def test_index_without_artifact_is_clean(tmp_path: Path) -> None:
    """A repo with no governance artifact indexes to empty governance, no error."""
    proj = _project(tmp_path)
    config = _config(proj)

    summary = run_pipeline(proj, config)

    assert summary["governance"]["governance_restored"] == 0
    assert not Path(config.graph.governance_artifact).exists()


def test_resolve_artifact_uses_project_root(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    cfg = ScaffoldConfig()  # default relative governance_artifact
    resolved = resolve_governance_artifact(cfg, start=proj)
    assert resolved == proj / "docs/ai/state/governance.json"
