"""Multi-project embedding search tests (Plan 225, Step 6).

Validates scoped/federated similarity search, per-hit project provenance, and
cross-project duplicate detection at the SQL level -- no sentence-transformers
model is required (vectors are inserted directly), so these run without the
``[search]`` extra. The natural-language ``search_similar`` path (which needs the
model) is covered by the search-quality suite under Plan 227.
"""

from __future__ import annotations

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.embeddings import _build_search_sql, find_duplicates
from agentscaffold.graph.scoping import Scope

pytest.importorskip("duckdb", reason="duckdb not installed")


@pytest.fixture
def backend():
    try:
        b = DuckPGQBackend(":memory:")
    except RuntimeError as exc:
        pytest.skip(f"duckpgq unavailable: {exc}")
    b.init_schema()
    yield b
    b.close()


def _make_multi_workspace(root, names):
    root.mkdir(parents=True, exist_ok=True)
    lines = ["projects:"]
    for name in names:
        (root / name).mkdir(exist_ok=True)
        (root / name / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
        (root / name / ".git").mkdir(exist_ok=True)
        lines.append(f"  - name: {name}")
        lines.append(f"    path: {name}")
    (root / "workspace.yaml").write_text("\n".join(lines) + "\n")
    return root


def _seed_two_projects(backend):
    backend.set_write_project("alpha")
    backend.store_embedding("func::a", "Function", [1.0, 0.0])
    backend.set_write_project("beta")
    backend.store_embedding("func::a", "Function", [0.99, 0.01])
    backend.set_write_project(None)


# ---------------------------------------------------------------------------
# _build_search_sql predicate injection + provenance
# ---------------------------------------------------------------------------


def test_build_sql_single_project_no_predicate_no_provenance():
    sql, params = _build_search_sql("Function", Scope(None, False))
    assert 'e.project AS "n.project"' not in sql
    assert "e.model = ?" in sql
    assert params == ["all-MiniLM-L6-v2"]


def test_build_sql_targeted_injects_predicate_and_provenance():
    sql, params = _build_search_sql("Function", Scope("alpha", True))
    assert 'e.project AS "n.project"' in sql
    assert "AND e.project = ?" in sql
    assert params == ["all-MiniLM-L6-v2", "alpha"]


def test_build_sql_federated_provenance_without_predicate():
    sql, params = _build_search_sql("Function", Scope(None, True))
    assert 'e.project AS "n.project"' in sql
    assert "AND e.project = ?" not in sql
    assert params == ["all-MiniLM-L6-v2"]


# ---------------------------------------------------------------------------
# Scoped / federated search via the backend (vector in, provenance out)
# ---------------------------------------------------------------------------


def test_vss_scoped_to_current_project(backend):
    _seed_two_projects(backend)
    hits = backend.search_similar_vss("Function", [1.0, 0.0], top_k=10, project="alpha")
    assert [h["node_id"] for h in hits] == ["alpha::func::a"]
    assert all(h["project"] == "alpha" for h in hits)


def test_vss_federated_returns_all_with_provenance(backend):
    _seed_two_projects(backend)
    hits = backend.search_similar_vss("Function", [1.0, 0.0], top_k=10, project=None)
    by_id = {h["node_id"]: h["project"] for h in hits}
    assert by_id == {"alpha::func::a": "alpha", "beta::func::a": "beta"}


def test_vss_scoped_excludes_sibling(backend):
    _seed_two_projects(backend)
    hits = backend.search_similar_vss("Function", [1.0, 0.0], top_k=10, project="beta")
    assert [h["node_id"] for h in hits] == ["beta::func::a"]


# ---------------------------------------------------------------------------
# Cross-project duplicate detection
# ---------------------------------------------------------------------------


def test_find_duplicates_surfaces_cross_project_pair(backend, tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    _seed_two_projects(backend)
    dupes = find_duplicates(backend, table="Function", threshold=0.9, start=ws / "alpha")
    assert len(dupes) == 1
    pair = dupes[0]
    assert {pair["project_a"], pair["project_b"]} == {"alpha", "beta"}
    assert pair["similarity"] >= 0.9


def test_find_duplicates_ignores_same_project_pairs(backend, tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    # Two near-identical embeddings within the SAME project must not be flagged.
    backend.set_write_project("alpha")
    backend.store_embedding("func::a", "Function", [1.0, 0.0])
    backend.store_embedding("func::b", "Function", [0.999, 0.001])
    backend.set_write_project(None)
    dupes = find_duplicates(backend, table="Function", threshold=0.9, start=ws / "alpha")
    assert dupes == []


def test_find_duplicates_single_project_returns_empty(backend, tmp_path):
    proj = tmp_path / "solo"
    proj.mkdir()
    (proj / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
    (proj / ".git").mkdir()
    _seed_two_projects(backend)  # data exists, but workspace is single-project
    assert find_duplicates(backend, table="Function", threshold=0.9, start=proj) == []
