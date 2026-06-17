"""Tests for the git-backed governance serialization codec (Plan 222)."""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402
from agentscaffold.graph.governance_store import (  # noqa: E402
    GOVERNANCE_ARTIFACT_VERSION,
    GovernanceArtifactError,
    enable_write_through,
    ingest_governance,
    load_governance,
    serialize_governance,
    sync_if_enabled,
)


def _seed(store: DuckPGQBackend) -> None:
    store.create_node(
        "ReviewFinding",
        {
            "id": "rf::a",
            "reviewType": "brief",
            "planNumber": 7,
            "severity": "high",
            "category": "design",
            "finding": "remember me",
            "resolution": "",
            "status": "open",
        },
    )
    store.create_node(
        "Session",
        {
            "id": "s1",
            "date": "2026-01-01T00:00:00+00:00",
            "planNumbers": "[]",
            "filesModified": "[]",
            "summary": "worked",
        },
    )


def _fresh(tmp_path: Path, name: str = "g.duckdb") -> DuckPGQBackend:
    store = DuckPGQBackend(str(tmp_path / name))
    store.init_schema()
    return store


def test_serialize_writes_versioned_artifact(tmp_path: Path) -> None:
    store = _fresh(tmp_path)
    _seed(store)
    artifact = tmp_path / "gov.json"

    serialize_governance(store, artifact)
    store.close()

    assert artifact.is_file()
    data = load_governance(artifact)
    assert data is not None
    assert data["governance_artifact_version"] == GOVERNANCE_ARTIFACT_VERSION
    assert "ReviewFinding" in data["nodes"]


def test_round_trip_reproduces_governance(tmp_path: Path) -> None:
    src = _fresh(tmp_path, "src.duckdb")
    _seed(src)
    artifact = tmp_path / "gov.json"
    serialize_governance(src, artifact)
    src.close()

    dst = _fresh(tmp_path, "dst.duckdb")
    result = ingest_governance(dst, artifact)
    assert result["present"] is True
    assert dst.node_count("ReviewFinding") == 1
    assert dst.node_count("Session") == 1
    dst.close()


def test_serialize_is_atomic_and_stable(tmp_path: Path) -> None:
    """Re-serializing an unchanged graph yields byte-identical output."""
    store = _fresh(tmp_path)
    _seed(store)
    artifact = tmp_path / "gov.json"

    serialize_governance(store, artifact)
    first = artifact.read_text()
    serialize_governance(store, artifact)
    second = artifact.read_text()
    store.close()

    assert first == second
    # No leftover temp file
    assert not (tmp_path / "gov.json.tmp").exists()


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_governance(tmp_path / "nope.json") is None


def test_ingest_missing_is_noop(tmp_path: Path) -> None:
    store = _fresh(tmp_path)
    result = ingest_governance(store, tmp_path / "absent.json")
    store.close()
    assert result["present"] is False
    assert result["imported"] == {}


def test_malformed_artifact_raises(tmp_path: Path) -> None:
    artifact = tmp_path / "bad.json"
    artifact.write_text("{ this is not json")
    with pytest.raises(GovernanceArtifactError):
        load_governance(artifact)


def test_non_object_artifact_raises(tmp_path: Path) -> None:
    artifact = tmp_path / "list.json"
    artifact.write_text("[1, 2, 3]")
    with pytest.raises(GovernanceArtifactError):
        load_governance(artifact)


def test_write_through_disabled_by_default(tmp_path: Path) -> None:
    """A backend without write-through enabled does not write an artifact."""
    store = _fresh(tmp_path)
    _seed(store)
    sync_if_enabled(store)  # no-op: not enabled
    store.close()
    assert not (tmp_path / "gov.json").exists()


def test_write_through_when_enabled(tmp_path: Path) -> None:
    store = _fresh(tmp_path)
    artifact = tmp_path / "gov.json"
    enable_write_through(store, artifact)
    _seed(store)
    sync_if_enabled(store)
    store.close()

    data = load_governance(artifact)
    assert data is not None
    assert "ReviewFinding" in data["nodes"]
