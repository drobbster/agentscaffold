"""Tests for Phase 5: Embeddings, communities, and hybrid search.

Tests cover:
- Embedding generation and semantic similarity search
- Leiden community detection
- Hybrid search with reciprocal rank fusion
- Graceful degradation without optional deps
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.graph.store import GraphStore

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture(scope="module")
def indexed_store(tmp_path_factory):
    """Index the sample repo and return a (store, config) tuple."""
    tmp = tmp_path_factory.mktemp("search_graph")
    db_path = tmp / "graph.db"

    from agentscaffold.config import GraphConfig, ScaffoldConfig

    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))

    run_pipeline(FIXTURE_REPO, config)

    store = GraphStore(db_path)
    yield store, config
    store.close()


# ---------------------------------------------------------------------------
# Community detection tests
# ---------------------------------------------------------------------------


class TestCommunityDetection:
    """Test Leiden community detection on the sample repo."""

    def test_detect_communities(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.communities import detect_communities

        result = detect_communities(store)
        assert isinstance(result, dict)
        assert "communities" in result
        assert "files_assigned" in result
        assert result["communities"] >= 0

    def test_community_nodes_created(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.communities import detect_communities

        result = detect_communities(store)
        if result["communities"] > 0:
            count = store.node_count("Community")
            assert count == result["communities"]

    def test_get_communities(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.communities import get_communities

        communities = get_communities(store)
        assert isinstance(communities, list)
        for c in communities:
            assert "c.label" in c
            assert "files" in c

    def test_community_has_label(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.communities import get_communities

        communities = get_communities(store)
        for c in communities:
            assert c.get("c.label") is not None

    def test_derive_label(self):
        from agentscaffold.graph.communities import _derive_label

        paths = ["libs/data/router.py", "libs/data/providers/base.py"]
        label = _derive_label(paths)
        assert "libs/data" in label or "libs" in label

    def test_derive_label_empty(self):
        from agentscaffold.graph.communities import _derive_label

        assert _derive_label([]) == "unknown"


# ---------------------------------------------------------------------------
# Embedding tests
# ---------------------------------------------------------------------------


class TestEmbeddings:
    """Test code embedding generation and similarity search."""

    def test_generate_embeddings(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.embeddings import generate_embeddings

        result = generate_embeddings(store, tables=["Function"])
        assert isinstance(result, dict)
        assert "Function" in result
        assert result["Function"] > 0

    def test_embeddings_available(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.embeddings import embeddings_available

        assert embeddings_available(store)

    def test_search_similar(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.embeddings import search_similar

        results = search_similar(store, "data routing", table="Function", top_k=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert "similarity" in results[0]
        assert results[0]["similarity"] > 0

    def test_search_returns_ranked(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.embeddings import search_similar

        results = search_similar(store, "strategy", table="Function", top_k=5)
        if len(results) >= 2:
            assert results[0]["similarity"] >= results[1]["similarity"]

    def test_build_text_functions(self):
        from agentscaffold.graph.embeddings import (
            _build_text_for_class,
            _build_text_for_file,
            _build_text_for_function,
            _build_text_for_method,
        )

        assert "function fetch" in _build_text_for_function(
            {"n.name": "fetch", "n.signature": "def fetch()", "n.filePath": "src/api.py"}
        )
        assert "class Router" in _build_text_for_class(
            {"n.name": "Router", "n.filePath": "src/router.py"}
        )
        assert "method Router.get" in _build_text_for_method(
            {"n.name": "get", "n.className": "Router", "n.signature": "", "n.filePath": ""}
        )
        assert "file src/main.py" in _build_text_for_file(
            {"n.path": "src/main.py", "n.language": "python"}
        )


# ---------------------------------------------------------------------------
# Hybrid search tests
# ---------------------------------------------------------------------------


class TestHybridSearch:
    """Test hybrid search combining Cypher and semantic modes."""

    def test_cypher_search(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.search import hybrid_search

        results = hybrid_search(store, "router", mode="cypher", top_k=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert results[0].source == "cypher"

    def test_semantic_search(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.search import hybrid_search

        results = hybrid_search(store, "data routing", mode="semantic", top_k=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert results[0].source == "semantic"

    def test_hybrid_search(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.search import hybrid_search

        results = hybrid_search(store, "router", mode="hybrid", top_k=5)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_search_result_fields(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.search import hybrid_search

        results = hybrid_search(store, "data", mode="cypher", top_k=5)
        if results:
            r = results[0]
            assert r.node_id
            assert r.name
            assert r.node_type in ("Function", "Class", "Method", "File")
            assert r.score > 0

    def test_format_search_results(self, indexed_store):
        store, _config = indexed_store

        from agentscaffold.graph.search import format_search_results, hybrid_search

        results = hybrid_search(store, "router", mode="cypher", top_k=3)
        md = format_search_results(results)
        assert "Search Results" in md
        assert "|" in md

    def test_format_empty_results(self):
        from agentscaffold.graph.search import format_search_results

        assert "No results" in format_search_results([])

    def test_reciprocal_rank_fusion(self):
        from agentscaffold.graph.search import SearchResult, _reciprocal_rank_fusion

        list_a = [
            SearchResult("id1", "foo", "a.py", "Function", 1.0, "cypher"),
            SearchResult("id2", "bar", "b.py", "Function", 0.5, "cypher"),
        ]
        list_b = [
            SearchResult("id2", "bar", "b.py", "Function", 0.9, "semantic"),
            SearchResult("id3", "baz", "c.py", "Function", 0.8, "semantic"),
        ]

        merged = _reciprocal_rank_fusion(list_a, list_b, top_k=3, k=60)
        assert len(merged) == 3
        # id2 appears in both lists, should get highest RRF score
        assert merged[0].node_id == "id2"
        assert merged[0].source == "both"

    def test_text_match_score(self):
        from agentscaffold.graph.search import _text_match_score

        assert _text_match_score(["router"], "DataRouter", "libs/data/router.py") > 0
        assert _text_match_score(["zzz"], "DataRouter", "libs/data/router.py") == 0
        assert _text_match_score([], "anything") == 0


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestPipelineWithCommunities:
    """Test that the pipeline integrates community detection."""

    def test_pipeline_detects_communities(self, tmp_path):
        from agentscaffold.config import GraphConfig, ScaffoldConfig

        config = ScaffoldConfig()
        db_path = tmp_path / "comm.db"
        config.graph = GraphConfig(db_path=str(db_path))

        summary = run_pipeline(FIXTURE_REPO, config)
        assert "communities" in summary
