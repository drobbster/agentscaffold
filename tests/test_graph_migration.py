"""Tests for governance export/import schema-migration safety (Plan 219)."""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


def _seed_governance(store: DuckPGQBackend) -> None:
    store.create_node(
        "ReviewFinding",
        {
            "id": "rf::keep",
            "reviewType": "brief",
            "planNumber": 42,
            "severity": "high",
            "category": "design",
            "finding": "something to remember",
            "resolution": "",
            "status": "open",
        },
    )
    store.create_node(
        "BacklogItem",
        {
            "id": "B-1-1",
            "planNumber": 1,
            "title": "do the thing",
            "priority": "P2",
            "effort": "M",
            "status": "archived",
            "source": "review",
            "createdAt": "2026-01-01T00:00:00+00:00",
            "archivedAt": "2026-01-02T00:00:00+00:00",
        },
    )
    store.create_node(
        "Session",
        {
            "id": "s1",
            "date": "2026-01-01T00:00:00+00:00",
            "planNumbers": "[]",
            "filesModified": "[]",
            "summary": "did stuff",
        },
    )
    store.create_node(
        "File",
        {
            "id": "f1",
            "path": "a.py",
            "language": "python",
            "size": 1,
            "lastModified": "",
            "lineCount": 1,
            "contentHash": "",
        },
    )
    store.create_edge("SESSION_MODIFIED", "", "s1", "", "f1")


def test_export_import_round_trip(tmp_path):
    db = tmp_path / "g.duckdb"
    store = DuckPGQBackend(str(db))
    store.init_schema()
    _seed_governance(store)

    data = store.export_governance()
    assert "ReviewFinding" in data["nodes"]
    assert "SESSION_MODIFIED" in data["edges"]

    store.clear_all()
    assert store.node_count("ReviewFinding") == 0
    assert store.node_count("Session") == 0
    assert store.edge_count("SESSION_MODIFIED") == 0

    result = store.import_governance(data)
    assert result["compatible"] is True

    assert store.node_count("ReviewFinding") == 1
    assert store.node_count("BacklogItem") == 1
    assert store.node_count("Session") == 1
    assert store.edge_count("SESSION_MODIFIED") == 1
    store.close()


def test_import_marks_incompatible_for_unknown_table(tmp_path):
    db = tmp_path / "g.duckdb"
    store = DuckPGQBackend(str(db))
    store.init_schema()

    data = {
        "nodes": {"BogusTable": {"columns": ["id", "x"], "rows": [{"id": "1", "x": "y"}]}},
        "edges": {},
    }
    result = store.import_governance(data)
    assert result["compatible"] is False
    assert "BogusTable" in result["skipped"]
    store.close()


def test_get_stats_reports_sessions(tmp_path):
    db = tmp_path / "g.duckdb"
    store = DuckPGQBackend(str(db))
    store.init_schema()
    store.create_node(
        "Session",
        {
            "id": "s1",
            "date": "2026-01-01T00:00:00+00:00",
            "planNumbers": "[]",
            "filesModified": "[]",
            "summary": "x",
        },
    )
    stats = store.get_stats()
    assert stats["sessions"] == 1
    store.close()


def test_pipeline_migration_preserves_governance(tmp_path):
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph.pipeline import run_pipeline

    db = tmp_path / ".scaffold" / "graph.duckdb"
    config = ScaffoldConfig()
    config.graph = GraphConfig(
        db_path=str(db),
        governance_artifact=str(tmp_path / "governance.json"),
    )

    run_pipeline(FIXTURE_REPO, config)

    store = DuckPGQBackend(str(db))
    store.create_node(
        "ReviewFinding",
        {
            "id": "rf::keep",
            "reviewType": "brief",
            "planNumber": 42,
            "severity": "high",
            "category": "design",
            "finding": "survive the migration",
            "resolution": "",
            "status": "open",
        },
    )
    # Force a schema-version mismatch so the next run triggers migration.
    store.execute("UPDATE GraphMeta SET schemaVersion = 1 WHERE id = 'singleton'")
    store.close()

    run_pipeline(FIXTURE_REPO, config)

    store = DuckPGQBackend(str(db))
    try:
        assert store.node_count("ReviewFinding") == 1
        assert (db.parent / "graph_export_v1.json").exists()
    finally:
        store.close()


def test_migration_is_fail_closed_when_export_fails(tmp_path, monkeypatch):
    from agentscaffold.graph import pipeline as pipeline_mod

    db = tmp_path / "g.duckdb"
    store = DuckPGQBackend(str(db))
    store.init_schema()
    store.create_node(
        "ReviewFinding",
        {
            "id": "rf::keep",
            "reviewType": "brief",
            "planNumber": 42,
            "severity": "high",
            "category": "design",
            "finding": "must not be lost",
            "resolution": "",
            "status": "open",
        },
    )

    cleared = {"called": False}
    real_clear = store.clear_all

    def _spy_clear():
        cleared["called"] = True
        real_clear()

    def _boom():
        raise RuntimeError("export blew up")

    monkeypatch.setattr(store, "clear_all", _spy_clear)
    monkeypatch.setattr(store, "export_governance", _boom)

    with pytest.raises(RuntimeError, match="Aborting schema rebuild"):
        pipeline_mod._migrate_on_version_change(store, db, 1)

    # Fail-closed: nothing was destroyed.
    assert cleared["called"] is False
    assert store.node_count("ReviewFinding") == 1
    store.close()


def test_force_rebuild_proceeds_when_export_fails(tmp_path, monkeypatch):
    from agentscaffold.graph import pipeline as pipeline_mod

    db = tmp_path / "g.duckdb"
    store = DuckPGQBackend(str(db))
    store.init_schema()
    store.create_node(
        "ReviewFinding",
        {
            "id": "rf::doomed",
            "reviewType": "brief",
            "planNumber": 42,
            "severity": "high",
            "category": "design",
            "finding": "expendable when forced",
            "resolution": "",
            "status": "open",
        },
    )

    def _boom():
        raise RuntimeError("export blew up")

    monkeypatch.setattr(store, "export_governance", _boom)

    # force=True: export failure is downgraded to a warning and the rebuild proceeds.
    pipeline_mod._migrate_on_version_change(store, db, 1, force=True)

    # Governance was discarded by the forced rebuild.
    assert store.node_count("ReviewFinding") == 0
    store.close()
