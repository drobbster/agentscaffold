"""GraphBackend protocol tests parametrized across kuzu and duckpgq — Step A.11.

Uses the ``any_store`` fixture from conftest.py which is parametrized over
["kuzu", "duckpgq"].  Each variant is skipped if the backend's Python
package is not installed, so the suite degrades gracefully in CI.
"""

from __future__ import annotations

from typing import Any

from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.query_compat import is_duckpgq

_FILE_PROPS: dict[str, Any] = {
    "id": "file::src/app.py",
    "path": "src/app.py",
    "language": "python",
    "size": 200,
    "lastModified": "2026-01-01",
    "lineCount": 20,
    "contentHash": "deadbeef",
}

_FILE_B_PROPS: dict[str, Any] = {
    **_FILE_PROPS,
    "id": "file::src/utils.py",
    "path": "src/utils.py",
    "contentHash": "cafebabe",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_version_positive(any_store: GraphBackend) -> None:
    assert isinstance(any_store.schema_version(), int)
    assert any_store.schema_version() > 0


def test_schema_current(any_store: GraphBackend) -> None:
    assert any_store.schema_current() is True


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


def test_create_node_and_count(any_store: GraphBackend) -> None:
    any_store.create_node("File", _FILE_PROPS)
    assert any_store.node_count("File") == 1


def test_create_node_idempotent(any_store: GraphBackend) -> None:
    """Creating the same node twice must not raise or double-count."""
    any_store.create_node("File", _FILE_PROPS)
    any_store.create_node("File", _FILE_PROPS)
    assert any_store.node_count("File") == 1


def test_node_count_zero_initial(any_store: GraphBackend) -> None:
    assert any_store.node_count("Plan") == 0


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------


def test_create_edge_and_count(any_store: GraphBackend) -> None:
    any_store.create_node("File", _FILE_PROPS)
    any_store.create_node("File", _FILE_B_PROPS)
    any_store.create_edge("IMPORTS", "File", _FILE_PROPS["id"], "File", _FILE_B_PROPS["id"])
    assert any_store.edge_count("IMPORTS") == 1


def test_edge_count_zero_initial(any_store: GraphBackend) -> None:
    assert any_store.edge_count("CALLS") == 0


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------


def test_pipeline_state_roundtrip(any_store: GraphBackend) -> None:
    any_store.update_pipeline_state("running", ["structure", "parsing"])
    state = any_store.get_pipeline_state()
    assert state["state"] == "running"
    assert "structure" in state["phases_completed"]
    assert "parsing" in state["phases_completed"]


def test_pipeline_state_initial_is_dict(any_store: GraphBackend) -> None:
    state = any_store.get_pipeline_state()
    assert isinstance(state, dict)
    assert "state" in state
    assert "phases_completed" in state


# ---------------------------------------------------------------------------
# Parsing warnings
# ---------------------------------------------------------------------------


def test_parsing_warnings_empty_initial(any_store: GraphBackend) -> None:
    assert any_store.get_parsing_warnings() == []


def test_add_and_get_parsing_warning(any_store: GraphBackend) -> None:
    any_store.add_parsing_warning("w-1", "src/broken.py", "parse", "syntax error")
    warnings = any_store.get_parsing_warnings()
    assert len(warnings) == 1
    # Key name differs by backend: "w.filePath" (kuzu) vs "filePath" (duckpgq)
    row = warnings[0]
    file_path = row.get("filePath") or row.get("w.filePath")
    assert file_path == "src/broken.py"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_get_stats_has_required_keys(any_store: GraphBackend) -> None:
    stats = any_store.get_stats()
    assert isinstance(stats, dict)
    for key in ("schema_version", "files", "functions", "plans"):
        assert key in stats, f"Missing key: {key}"


def test_get_stats_counts_files(any_store: GraphBackend) -> None:
    any_store.create_node("File", _FILE_PROPS)
    stats = any_store.get_stats()
    assert stats["files"] == 1


# ---------------------------------------------------------------------------
# clear_table / clear_all
# ---------------------------------------------------------------------------


def test_clear_table(any_store: GraphBackend) -> None:
    any_store.create_node("File", _FILE_PROPS)
    assert any_store.node_count("File") == 1
    any_store.clear_table("File")
    assert any_store.node_count("File") == 0


def test_clear_all(any_store: GraphBackend) -> None:
    any_store.create_node("File", _FILE_PROPS)
    any_store.clear_all()
    assert any_store.node_count("File") == 0
    assert any_store.schema_current() is True


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_implements_graphbackend_protocol(any_store: GraphBackend) -> None:
    assert isinstance(any_store, GraphBackend)


def test_is_duckpgq_matches_backend_type(any_store: GraphBackend) -> None:
    """is_duckpgq() must agree with the actual backend class name."""
    duck = is_duckpgq(any_store)
    assert isinstance(duck, bool)
    if type(any_store).__name__ == "DuckPGQBackend":
        assert duck is True
    else:
        assert duck is False
