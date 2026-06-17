"""Search-quality regression baseline scenarios."""

from __future__ import annotations

import math

import pytest

from eval.runner import (
    EvalResult,
    SearchQualityResult,
    collect_result,
    collect_search_quality,
)

LABELED_QUERIES = [
    ("data router provider routing", "DataRouter"),
    ("risk manager position limits", "RiskManager"),
    ("momentum strategy signal", "MomentumStrategy"),
]


def _score_results(results, expected: str, k: int) -> tuple[float, float]:
    expected_norm = expected.lower()
    top = results[:k]
    relevant = [
        idx + 1
        for idx, result in enumerate(top)
        if expected_norm in result.name.lower()
        or expected_norm in result.node_id.lower()
        or expected_norm in result.path.lower()
    ]
    precision = len(relevant) / k
    reciprocal_rank = 1.0 / relevant[0] if relevant else 0.0
    return precision, reciprocal_rank


class TestSearchQuality:
    """Small labeled query-set metrics for keyword vs hybrid retrieval."""

    def test_keyword_vs_hybrid_quality_and_normalization(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.graph.embeddings import (
            configure_embeddings,
            generate_embeddings,
            model_ready,
        )
        from agentscaffold.graph.search import hybrid_search

        configure_embeddings(config.search.embedding_model, config.search.cache_dir)
        if not model_ready(config.search.embedding_model, config.search.cache_dir):
            reason = "embedding model is not available in the local cache"
            collect_search_quality(
                SearchQualityResult(
                    mode="hybrid",
                    precision_at_k=0.0,
                    mrr=0.0,
                    queries=len(LABELED_QUERIES),
                    skipped=True,
                    reason=reason,
                )
            )
            pytest.skip(reason)

        generate_embeddings(
            store,
            model_name=config.search.embedding_model,
            cache_dir=config.search.cache_dir,
            tables=["Function", "Class"],
            root=root,
        )

        metrics: dict[str, tuple[float, float]] = {}
        for mode in ("keyword", "hybrid"):
            precision_total = 0.0
            mrr_total = 0.0
            for query, expected in LABELED_QUERIES:
                results = hybrid_search(
                    store,
                    query,
                    mode=mode,
                    top_k=5,
                    tables=["Function", "Class"],
                    start=root,
                )
                precision, rr = _score_results(results, expected, k=5)
                precision_total += precision
                mrr_total += rr

            precision_at_k = precision_total / len(LABELED_QUERIES)
            mrr = mrr_total / len(LABELED_QUERIES)
            metrics[mode] = (precision_at_k, mrr)
            collect_search_quality(
                SearchQualityResult(
                    mode=mode,
                    precision_at_k=round(precision_at_k, 3),
                    mrr=round(mrr, 3),
                    queries=len(LABELED_QUERIES),
                )
            )

        norms = store.query(
            "SELECT node_id, sqrt(list_sum(list_transform(embedding, x -> x * x))) AS norm"
            " FROM EmbeddingStore"
            " WHERE node_type IN ('Function', 'Class')",
            {},
        )
        norm_failures = [
            f"{row['node_id']}={row['norm']:.4f}"
            for row in norms
            if not math.isclose(float(row["norm"]), 1.0, rel_tol=0.01, abs_tol=0.01)
        ]

        keyword_precision, keyword_mrr = metrics["keyword"]
        hybrid_precision, hybrid_mrr = metrics["hybrid"]
        passed = (
            hybrid_precision >= keyword_precision
            and hybrid_mrr >= keyword_mrr
            and not norm_failures
        )

        collect_result(
            EvalResult(
                scenario="search_quality_keyword_vs_hybrid",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Hybrid non-inferior to keyword; all stored embeddings L2-normalized",
                actual=(
                    f"keyword p@5={keyword_precision:.3f}, mrr={keyword_mrr:.3f}; "
                    f"hybrid p@5={hybrid_precision:.3f}, mrr={hybrid_mrr:.3f}; "
                    f"norm failures={len(norm_failures)}"
                ),
                observations=norm_failures[:10],
                category="search_quality",
            )
        )

        assert passed
