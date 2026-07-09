"""DuckPGQ native embedding storage and vector similarity tests — Step A.8."""

from __future__ import annotations

from typing import Any

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FILE_PROPS = {
    "id": "file::src/alpha.py",
    "path": "src/alpha.py",
    "language": "python",
    "size": 100,
    "lastModified": "2026-01-01",
    "lineCount": 10,
    "contentHash": "abc",
}

_FUNC_A = {
    "id": "fn::alpha::do_thing",
    "name": "do_thing",
    "filePath": "src/alpha.py",
    "startLine": 1,
    "endLine": 5,
    "isExported": True,
    "paramCount": 0,
    "signature": "do_thing()",
}

_FUNC_B = {
    "id": "fn::alpha::helper",
    "name": "helper",
    "filePath": "src/alpha.py",
    "startLine": 6,
    "endLine": 10,
    "isExported": False,
    "paramCount": 1,
    "signature": "helper(x)",
}

_VEC_A = [float(i) / 384 for i in range(384)]  # synthetic 384-dim vector
_VEC_B = [float(384 - i) / 384 for i in range(384)]  # orthogonal-ish vector


@pytest.fixture()
def store() -> Any:
    s = DuckPGQBackend(":memory:")
    s.init_schema()
    s.create_node("File", _FILE_PROPS)
    s.create_node("Function", _FUNC_A)
    s.create_node("Function", _FUNC_B)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# EmbeddingStore table exists
# ---------------------------------------------------------------------------


def test_embedding_store_table_exists(store: Any) -> None:
    rows = store.query("SELECT COUNT(*) AS n FROM EmbeddingStore")
    assert rows[0]["n"] == 0


# ---------------------------------------------------------------------------
# store_embedding
# ---------------------------------------------------------------------------


def test_store_embedding_inserts_row(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    count = store.embeddings_count("Function")
    assert count == 1


def test_store_embedding_records_model_and_text_hash(store: Any) -> None:
    store.store_embedding(
        _FUNC_A["id"],
        "Function",
        _VEC_A,
        model="test-model",
        text_hash="abc123",
    )
    rows = store.query("SELECT model, text_hash FROM EmbeddingStore")
    assert rows == [{"model": "test-model", "text_hash": "abc123"}]


def test_store_embedding_defaults_to_current_default_model(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    assert store.query_scalar("SELECT model FROM EmbeddingStore") == "all-MiniLM-L6-v2"


def test_store_embedding_upserts(store: Any) -> None:
    """Calling store_embedding twice with the same node_id replaces the row."""
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_B)
    assert store.embeddings_count("Function") == 1


def test_store_multiple_embeddings(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    store.store_embedding(_FUNC_B["id"], "Function", _VEC_B)
    assert store.embeddings_count("Function") == 2


def test_store_embedding_different_types(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    store.store_embedding(_FILE_PROPS["id"], "File", _VEC_B)
    assert store.embeddings_count("Function") == 1
    assert store.embeddings_count("File") == 1


# ---------------------------------------------------------------------------
# embeddings_count
# ---------------------------------------------------------------------------


def test_embeddings_count_zero_initial(store: Any) -> None:
    assert store.embeddings_count("Function") == 0
    assert store.embeddings_count("File") == 0


def test_embeddings_count_increments(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    assert store.embeddings_count("Function") == 1
    store.store_embedding(_FUNC_B["id"], "Function", _VEC_B)
    assert store.embeddings_count("Function") == 2


# ---------------------------------------------------------------------------
# search_similar_vss
# ---------------------------------------------------------------------------


def test_search_returns_empty_when_no_embeddings(store: Any) -> None:
    results = store.search_similar_vss("Function", _VEC_A, top_k=5)
    assert results == []


def test_search_returns_self_as_top_result(store: Any) -> None:
    """A vector should be most similar to itself."""
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    store.store_embedding(_FUNC_B["id"], "Function", _VEC_B)
    results = store.search_similar_vss("Function", _VEC_A, top_k=2)
    assert len(results) >= 1
    top = results[0]
    assert top["node_id"] == _FUNC_A["id"]
    sim = float(top["similarity"])
    assert sim > 0.99  # cosine similarity of a vector with itself is 1.0


def test_search_returns_correct_number_of_results(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    store.store_embedding(_FUNC_B["id"], "Function", _VEC_B)
    results = store.search_similar_vss("Function", _VEC_A, top_k=1)
    assert len(results) == 1


def test_search_results_ordered_by_similarity(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    store.store_embedding(_FUNC_B["id"], "Function", _VEC_B)
    results = store.search_similar_vss("Function", _VEC_A, top_k=2)
    assert len(results) == 2
    # First result should have higher (or equal) similarity than second
    assert float(results[0]["similarity"]) >= float(results[1]["similarity"])


def test_search_wrong_node_type_returns_empty(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    results = store.search_similar_vss("File", _VEC_A, top_k=5)
    assert results == []


def test_search_similar_vss_filters_by_model(store: Any) -> None:
    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A, model="model-a")
    store.store_embedding(_FUNC_B["id"], "Function", _VEC_B, model="model-b")
    results = store.search_similar_vss("Function", _VEC_A, top_k=5, model="model-a")
    assert [r["node_id"] for r in results] == [_FUNC_A["id"]]


# ---------------------------------------------------------------------------
# embeddings_available integration with embeddings module
# ---------------------------------------------------------------------------


def test_embeddings_available_false_when_empty(store: Any) -> None:
    from agentscaffold.graph.embeddings import embeddings_available

    assert embeddings_available(store) is False


def test_embeddings_available_true_after_store(store: Any) -> None:
    from agentscaffold.graph.embeddings import embeddings_available

    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A)
    assert embeddings_available(store) is True


def test_embeddings_available_false_for_different_model(store: Any) -> None:
    from agentscaffold.graph.embeddings import embeddings_available, embeddings_model_mismatch

    store.store_embedding(_FUNC_A["id"], "Function", _VEC_A, model="old-model")
    assert embeddings_available(store, "new-model") is False
    assert embeddings_model_mismatch(store, "new-model") is True


# ---------------------------------------------------------------------------
# generate_embeddings integration (requires sentence-transformers)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("sentence_transformers"),
    reason="sentence-transformers not installed",
)
def test_generate_embeddings_duckpgq(store: Any) -> None:
    from agentscaffold.graph.embeddings import generate_embeddings

    counts = generate_embeddings(store, tables=["Function"])
    assert "Function" in counts
    assert counts["Function"] >= 1
    assert store.embeddings_count("Function") >= 1


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("sentence_transformers"),
    reason="sentence-transformers not installed",
)
def test_search_similar_duckpgq_integration(store: Any) -> None:
    from agentscaffold.graph.embeddings import generate_embeddings, search_similar

    generate_embeddings(store, tables=["Function"])
    results = search_similar(store, "utility helper function", table="Function", top_k=2)
    assert isinstance(results, list)
    if results:
        assert "n.id" in results[0]
        assert "similarity" in results[0]
        assert 0 <= results[0]["similarity"] <= 1.0
