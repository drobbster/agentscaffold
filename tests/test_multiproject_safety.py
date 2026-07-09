"""Multi-project backend safety tests (Plan 225, Step 5).

Exercises the create_node/create_edge/store_embedding choke point and the
project-scoped clears against a real in-memory DuckPGQ backend: ID-prefixing,
project stamping, check-before-insert collision detection, idempotent
re-indexing, and "scoped clear leaves siblings intact". Validates the spike's
safety findings in the actual implementation.
"""

from __future__ import annotations

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend, GraphCorruptionError

pytest.importorskip("duckdb", reason="duckdb not installed")


@pytest.fixture
def backend():
    try:
        b = DuckPGQBackend(":memory:")
    except RuntimeError as exc:  # duckpgq extension unavailable
        pytest.skip(f"duckpgq unavailable: {exc}")
    b.init_schema()
    yield b
    b.close()


# ---------------------------------------------------------------------------
# ID prefixing + project stamping
# ---------------------------------------------------------------------------


def test_multi_project_prefixes_and_stamps(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a", "path": "a.py"})
    rows = backend.query("SELECT id, project FROM File")
    assert rows == [{"id": "alpha::file::a", "project": "alpha"}]


def test_same_raw_id_two_projects_no_collision(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a"})
    backend.set_write_project("beta")
    backend.create_node("File", {"id": "file::a"})
    ids = {r["id"] for r in backend.query("SELECT id FROM File")}
    assert ids == {"alpha::file::a", "beta::file::a"}


def test_single_project_unchanged(backend):
    backend.set_write_project(None)
    backend.create_node("File", {"id": "file::a", "path": "a.py"})
    rows = backend.query("SELECT id, project FROM File")
    assert rows == [{"id": "file::a", "project": ""}]


def test_qualify_is_idempotent_within_project(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a"})
    backend.create_node("File", {"id": "file::a"})  # re-index same node
    assert backend.node_count("File") == 1


def test_already_qualified_id_not_double_prefixed(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "alpha::file::a"})
    ids = [r["id"] for r in backend.query("SELECT id FROM File")]
    assert ids == ["alpha::file::a"]


# ---------------------------------------------------------------------------
# Check-before-insert collision detection
# ---------------------------------------------------------------------------


def test_collision_guard_raises_on_cross_project_id(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a"})
    # Simulate corruption: a row with alpha's qualified id but beta's project.
    backend.execute("INSERT INTO File (id, path, project) VALUES ('alpha::file::z', 'z', 'beta')")
    backend.set_write_project("alpha")
    with pytest.raises(GraphCorruptionError):
        backend.create_node("File", {"id": "file::z"})


# ---------------------------------------------------------------------------
# Project-scoped clears leave siblings intact
# ---------------------------------------------------------------------------


def test_clear_derived_scoped_preserves_sibling(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a"})
    backend.set_write_project("beta")
    backend.create_node("File", {"id": "file::b"})
    backend.clear_derived(project="alpha")
    ids = {r["id"] for r in backend.query("SELECT id FROM File")}
    assert ids == {"beta::file::b"}


def test_clear_derived_scoped_preserves_sibling_edges(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a"})
    backend.create_node("File", {"id": "file::a2"})
    backend.create_edge("IMPORTS", "File", "file::a", "File", "file::a2")
    backend.set_write_project("beta")
    backend.create_node("File", {"id": "file::b"})
    backend.create_node("File", {"id": "file::b2"})
    backend.create_edge("IMPORTS", "File", "file::b", "File", "file::b2")
    backend.clear_derived(project="alpha")
    edges = backend.query("SELECT src, dst FROM IMPORTS")
    assert edges == [{"src": "beta::file::b", "dst": "beta::file::b2"}]


def test_clear_governance_scoped_preserves_sibling(backend):
    backend.set_write_project("alpha")
    backend.create_node("Plan", {"id": "plan::1", "number": 1})
    backend.set_write_project("beta")
    backend.create_node("Plan", {"id": "plan::1", "number": 1})
    backend.clear_governance(project="alpha")
    projects = {r["project"] for r in backend.query("SELECT project FROM Plan")}
    assert projects == {"beta"}


def test_clear_table_scoped_preserves_sibling(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a"})
    backend.set_write_project("beta")
    backend.create_node("File", {"id": "file::b"})
    backend.clear_table("File", project="alpha")
    ids = {r["id"] for r in backend.query("SELECT id FROM File")}
    assert ids == {"beta::file::b"}


def test_clear_global_wipes_all(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a"})
    backend.set_write_project("beta")
    backend.create_node("File", {"id": "file::b"})
    backend.clear_derived()  # no project -> global
    assert backend.node_count("File") == 0


# ---------------------------------------------------------------------------
# Embeddings: scoped store + scoped clear
# ---------------------------------------------------------------------------


def test_store_embedding_prefixes_and_stamps(backend):
    backend.set_write_project("alpha")
    backend.store_embedding("func::a", "Function", [1.0, 0.0])
    backend.set_write_project("beta")
    backend.store_embedding("func::a", "Function", [0.0, 1.0])
    rows = backend.query("SELECT node_id, project FROM EmbeddingStore")
    assert {(r["node_id"], r["project"]) for r in rows} == {
        ("alpha::func::a", "alpha"),
        ("beta::func::a", "beta"),
    }


def test_store_embedding_single_project_unchanged(backend):
    backend.set_write_project(None)
    backend.store_embedding("func::a", "Function", [1.0, 0.0])
    rows = backend.query("SELECT node_id, project FROM EmbeddingStore")
    assert rows == [{"node_id": "func::a", "project": ""}]


def test_clear_derived_scoped_preserves_sibling_embeddings(backend):
    backend.set_write_project("alpha")
    backend.store_embedding("func::a", "Function", [1.0, 0.0])
    backend.set_write_project("beta")
    backend.store_embedding("func::a", "Function", [0.0, 1.0])
    backend.clear_derived(project="alpha")
    remaining = [r["node_id"] for r in backend.query("SELECT node_id FROM EmbeddingStore")]
    assert remaining == ["beta::func::a"]


# ---------------------------------------------------------------------------
# Single -> multi mode flip (atomic re-key) + integrity invariant
# ---------------------------------------------------------------------------


def test_migrate_rekeys_nodes_edges_embeddings(backend):
    # Seed a single-project (unprefixed) graph.
    backend.set_write_project(None)
    backend.create_node("File", {"id": "file::a", "path": "a.py"})
    backend.create_node("File", {"id": "file::b", "path": "b.py"})
    backend.create_edge("IMPORTS", "File", "file::a", "File", "file::b")
    backend.create_node("Plan", {"id": "plan::1", "number": 1, "title": "P1"})
    backend.store_embedding("func::a", "Function", [1.0, 0.0])

    counts = backend.migrate_to_multi_project("alpha")

    assert counts["nodes"] >= 3  # 2 files + 1 plan
    assert counts["edges"] == 1
    assert counts["embeddings"] == 1
    file_rows = backend.query("SELECT id, project FROM File ORDER BY id")
    assert file_rows == [
        {"id": "alpha::file::a", "project": "alpha"},
        {"id": "alpha::file::b", "project": "alpha"},
    ]
    edges = backend.query("SELECT src, dst FROM IMPORTS")
    assert edges == [{"src": "alpha::file::a", "dst": "alpha::file::b"}]
    emb = backend.query("SELECT node_id, project FROM EmbeddingStore")
    assert emb == [{"node_id": "alpha::func::a", "project": "alpha"}]


def test_migrate_is_idempotent(backend):
    backend.set_write_project(None)
    backend.create_node("File", {"id": "file::a", "path": "a.py"})
    backend.migrate_to_multi_project("alpha")
    second = backend.migrate_to_multi_project("alpha")
    assert second == {"nodes": 0, "edges": 0, "embeddings": 0}
    ids = [r["id"] for r in backend.query("SELECT id FROM File")]
    assert ids == ["alpha::file::a"]


def test_migrate_then_sibling_coexists(backend):
    backend.set_write_project(None)
    backend.create_node("Plan", {"id": "plan::1", "number": 1, "title": "P1"})
    backend.migrate_to_multi_project("alpha")
    # A new sibling can now write an identically-numbered plan without collision.
    backend.set_write_project("beta")
    backend.create_node("Plan", {"id": "plan::1", "number": 1, "title": "P1-beta"})
    projects = {r["project"] for r in backend.query("SELECT project FROM Plan")}
    assert projects == {"alpha", "beta"}
    assert backend.verify_integrity() == []


def test_verify_integrity_flags_mismatch(backend):
    backend.set_write_project("alpha")
    backend.create_node("File", {"id": "file::a", "path": "a.py"})
    # Inject a corrupt row: stamped beta but id carries no beta prefix.
    backend.execute("INSERT INTO File (id, path, project) VALUES ('file::bad', 'bad', 'beta')")
    problems = backend.verify_integrity()
    assert any("file::bad" in p for p in problems)
