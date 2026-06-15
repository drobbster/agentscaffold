"""Hybrid search combining keyword graph queries with semantic vector search.

Supports three search modes:
- keyword: Pure graph structural query (name/path matching)
- semantic: Vector similarity against code embeddings
- hybrid: Combines both with reciprocal rank fusion

Requires: pip install agentscaffold[search] for semantic/hybrid modes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.query_compat import ql

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result with provenance tracking."""

    node_id: str
    name: str
    path: str
    node_type: str
    score: float
    source: str  # "keyword", "semantic", or "both"
    context: dict[str, Any] = field(default_factory=dict)


def evaluate_retrieval(store: GraphBackend, mode: str = "hybrid") -> dict[str, str]:
    """Classify retrieval capability for a requested search mode.

    Returns a dict with prefixed keys so it can be merged directly into an MCP
    ``meta`` block or consumed by the CLI:

    - ``retrieval_status``: ``available`` | ``degraded`` | ``unavailable``
    - ``retrieval_effective_mode``: the mode that will actually run
      (``keyword`` | ``semantic`` | ``hybrid`` | ``none``)
    - ``retrieval_requested_mode``: the mode that was asked for
    - ``retrieval_reason``: human-readable explanation

    Semantics:
    - keyword: always ``available``.
    - semantic/hybrid with sentence-transformers missing: pure ``semantic`` is
      ``unavailable`` (no fallback); ``hybrid`` is ``degraded`` (keyword still runs).
    - semantic/hybrid installed but no embeddings indexed: ``degraded``.
    - both the library and embeddings present: ``available``.
    """
    requested = (mode or "hybrid").lower()

    def _result(status: str, effective: str, reason: str) -> dict[str, str]:
        return {
            "retrieval_status": status,
            "retrieval_effective_mode": effective,
            "retrieval_requested_mode": requested,
            "retrieval_reason": reason,
        }

    if requested not in ("semantic", "hybrid"):
        return _result("available", "keyword", "keyword search needs no optional dependencies")

    from agentscaffold.graph import embeddings as _embeddings

    if not _embeddings._st_available:
        if requested == "semantic":
            return _result(
                "unavailable",
                "none",
                "sentence-transformers not installed; install agentscaffold[search]",
            )
        return _result(
            "degraded",
            "keyword",
            "sentence-transformers not installed; using keyword search only",
        )

    if not _embeddings.embeddings_available(store):
        return _result(
            "degraded",
            "keyword" if requested == "hybrid" else "semantic",
            "no embeddings indexed; run 'scaffold index --embeddings'",
        )

    return _result("available", requested, "semantic and keyword retrieval available")


def hybrid_search(
    store: GraphBackend,
    query: str,
    *,
    mode: str = "hybrid",
    top_k: int = 10,
    tables: list[str] | None = None,
    rrf_k: int = 60,
) -> list[SearchResult]:
    """Execute a hybrid search across the knowledge graph.

    Args:
        store: GraphBackend instance
        query: Natural language query
        mode: "keyword", "semantic", or "hybrid"
        top_k: Number of results to return
        tables: Node tables to search (default: Function, Class, Method, File)
        rrf_k: Reciprocal rank fusion constant (higher = more weight to lower ranks)

    Returns:
        Ranked list of SearchResult objects
    """
    target_tables = tables or ["Function", "Class", "Method", "File"]

    keyword_results: list[SearchResult] = []
    semantic_results: list[SearchResult] = []

    if mode in ("keyword", "hybrid"):
        keyword_results = _keyword_search(store, query, target_tables, top_k * 2)

    if mode in ("semantic", "hybrid"):
        semantic_results = _semantic_search(store, query, target_tables, top_k * 2)

    if mode == "keyword":
        return keyword_results[:top_k]
    if mode == "semantic":
        return semantic_results[:top_k]

    return _reciprocal_rank_fusion(keyword_results, semantic_results, top_k, rrf_k)


def _keyword_search(
    store: GraphBackend,
    query: str,
    tables: list[str],
    limit: int,
) -> list[SearchResult]:
    """Search using graph structure: name matching, path matching."""
    results: list[SearchResult] = []
    terms = query.lower().split()

    for table in tables:
        if table == "Function":
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", name AS "n.name", '
                    f'filePath AS "n.filePath", signature AS "n.signature" '
                    f"FROM Function LIMIT {limit * 2}"
                ),
            )
            for row in rows:
                score = _text_match_score(
                    terms,
                    row.get("n.name", ""),
                    row.get("n.filePath", ""),
                    row.get("n.signature", ""),
                )
                if score > 0:
                    results.append(
                        SearchResult(
                            node_id=row["n.id"],
                            name=row.get("n.name", ""),
                            path=row.get("n.filePath", ""),
                            node_type="Function",
                            score=score,
                            source="keyword",
                            context={"signature": row.get("n.signature", "")},
                        )
                    )

        elif table == "Class":
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", name AS "n.name", '
                    f'filePath AS "n.filePath" FROM Class LIMIT {limit * 2}'
                ),
            )
            for row in rows:
                score = _text_match_score(terms, row.get("n.name", ""), row.get("n.filePath", ""))
                if score > 0:
                    results.append(
                        SearchResult(
                            node_id=row["n.id"],
                            name=row.get("n.name", ""),
                            path=row.get("n.filePath", ""),
                            node_type="Class",
                            score=score,
                            source="keyword",
                        )
                    )

        elif table == "Method":
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", name AS "n.name", className AS "n.className",'
                    f' filePath AS "n.filePath", signature AS "n.signature"'
                    f" FROM Method LIMIT {limit * 2}"
                ),
            )
            for row in rows:
                full_name = f"{row.get('n.className', '')}.{row.get('n.name', '')}"
                score = _text_match_score(
                    terms,
                    full_name,
                    row.get("n.filePath", ""),
                    row.get("n.signature", ""),
                )
                if score > 0:
                    results.append(
                        SearchResult(
                            node_id=row["n.id"],
                            name=full_name,
                            path=row.get("n.filePath", ""),
                            node_type="Method",
                            score=score,
                            source="keyword",
                            context={"signature": row.get("n.signature", "")},
                        )
                    )

        elif table == "File":
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", path AS "n.path", '
                    f'language AS "n.language" FROM File LIMIT {limit * 2}'
                ),
            )
            for row in rows:
                score = _text_match_score(terms, row.get("n.path", ""), row.get("n.language", ""))
                if score > 0:
                    results.append(
                        SearchResult(
                            node_id=row["n.id"],
                            name=row.get("n.path", "").split("/")[-1],
                            path=row.get("n.path", ""),
                            node_type="File",
                            score=score,
                            source="keyword",
                        )
                    )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def _semantic_search(
    store: GraphBackend,
    query: str,
    tables: list[str],
    limit: int,
) -> list[SearchResult]:
    """Search using vector similarity."""
    try:
        from agentscaffold.graph.embeddings import search_similar
    except ImportError:
        logger.debug("sentence-transformers not available for semantic search")
        return []

    results: list[SearchResult] = []

    for table in tables:
        if table not in ("Function", "Class", "Method", "File"):
            continue

        try:
            hits = search_similar(store, query, table=table, top_k=limit)
        except Exception:
            logger.debug("Semantic search failed for %s", table, exc_info=True)
            continue

        for hit in hits:
            name = hit.get("n.name", hit.get("n.path", "unknown"))
            path = hit.get("n.filePath", hit.get("n.path", ""))

            results.append(
                SearchResult(
                    node_id=hit.get("n.id", ""),
                    name=name,
                    path=path,
                    node_type=table,
                    score=hit.get("similarity", 0.0),
                    source="semantic",
                )
            )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def _reciprocal_rank_fusion(
    keyword_results: list[SearchResult],
    semantic_results: list[SearchResult],
    top_k: int,
    k: int = 60,
) -> list[SearchResult]:
    """Merge results from two ranked lists using reciprocal rank fusion.

    RRF score = sum(1 / (k + rank_i)) across all lists where the result appears.
    """
    scores: dict[str, float] = {}
    result_map: dict[str, SearchResult] = {}

    for rank, r in enumerate(keyword_results):
        scores[r.node_id] = scores.get(r.node_id, 0.0) + 1.0 / (k + rank + 1)
        if r.node_id not in result_map:
            result_map[r.node_id] = r

    for rank, r in enumerate(semantic_results):
        scores[r.node_id] = scores.get(r.node_id, 0.0) + 1.0 / (k + rank + 1)
        if r.node_id in result_map:
            result_map[r.node_id].source = "both"
        else:
            result_map[r.node_id] = r

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    results: list[SearchResult] = []
    for node_id, score in ranked[:top_k]:
        r = result_map[node_id]
        r.score = round(score, 6)
        results.append(r)

    return results


def _text_match_score(terms: list[str], *fields: str) -> float:
    """Score a node based on term overlap with its fields."""
    if not terms:
        return 0.0

    combined = " ".join(f.lower() for f in fields if f)
    if not combined:
        return 0.0

    matches = sum(1 for t in terms if t in combined)
    if matches == 0:
        return 0.0

    exact_bonus = 0.0
    for f in fields:
        f_lower = f.lower() if f else ""
        for t in terms:
            if f_lower == t:
                exact_bonus += 0.5
            elif f_lower.endswith(f".{t}") or f_lower.endswith(f"/{t}"):
                exact_bonus += 0.3

    return matches / len(terms) + exact_bonus


def format_search_results(results: list[SearchResult]) -> str:
    """Format search results as markdown."""
    if not results:
        return "No results found."

    lines = ["## Search Results", ""]
    lines.append("| # | Type | Name | Path | Score | Source |")
    lines.append("|---|------|------|------|-------|--------|")

    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r.node_type} | `{r.name}` | `{r.path}` | {r.score:.4f} | {r.source} |"
        )

    return "\n".join(lines)
