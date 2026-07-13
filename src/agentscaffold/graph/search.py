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
from agentscaffold.graph.query_compat import ql, sql_escape

logger = logging.getLogger(__name__)


def _project_of(value: str | None) -> str | None:
    """Normalize a stored ``project`` column value to ``str | None``.

    Node rows carry a ``project`` column that is populated in multi-project
    workspaces and empty in single-project repos. Provenance is surfaced only
    when it is actually present (federated / multi-project results).
    """
    return value or None


CODE_TABLES = ["Function", "Class", "Method", "File"]
GOVERNANCE_TABLES = ["Plan", "Learning", "ReviewFinding", "Study", "ADR", "Spike", "BacklogItem"]


@dataclass
class SearchResult:
    """A single search result with provenance tracking."""

    node_id: str
    name: str
    path: str
    node_type: str
    score: float
    source: str  # "keyword", "semantic", or "both"
    project: str | None = None  # owning project (federated searches only)
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

    if _embeddings.embeddings_model_mismatch(store):
        return _result(
            "degraded",
            "keyword" if requested == "hybrid" else "semantic",
            "embeddings were built with a different model; run 'scaffold index --embeddings'",
        )

    if not _embeddings.embeddings_available(store):
        return _result(
            "degraded",
            "keyword" if requested == "hybrid" else "semantic",
            "no embeddings indexed; run 'scaffold index --embeddings'",
        )

    if not _embeddings.model_ready():
        # Package + embeddings present, but the model weights are not cached and
        # may need a network download. Degrade gracefully with an actionable hint
        # instead of letting a load fail mid-query.
        reason = (
            "embedding model weights not provisioned; run 'scaffold graph warm' "
            "(or connect to a network) to download them once"
        )
        if requested == "semantic":
            return _result("unavailable", "none", reason)
        return _result("degraded", "keyword", reason)

    return _result("available", requested, "semantic and keyword retrieval available")


def hybrid_search(
    store: GraphBackend,
    query: str,
    *,
    mode: str = "hybrid",
    top_k: int = 10,
    tables: list[str] | None = None,
    rrf_k: int = 60,
    rerank: bool = False,
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    project: str | None = None,
    all_projects: bool = False,
    start: Any = None,
) -> list[SearchResult]:
    """Execute a hybrid search across the knowledge graph.

    Args:
        store: GraphBackend instance
        query: Natural language query
        mode: "keyword", "semantic", or "hybrid"
        top_k: Number of results to return
        tables: Node tables to search (default: Function, Class, Method, File)
        rrf_k: Reciprocal rank fusion constant (higher = more weight to lower ranks)
        rerank: Optionally rerank the fused top-k with a sentence-transformers CrossEncoder.
        rerank_model: CrossEncoder model id used when rerank is enabled.
        project: Target a specific project (multi-project workspace only)
        all_projects: Search federated across the workspace (overrides ``project``)
        start: Working directory hint for current-project resolution

    Scope (Plan 225): in a multi-project workspace both the keyword and semantic
    halves default to the current project; ``project=``/``all_projects=`` widen
    or retarget. Single-project repos ignore scope entirely.

    Returns:
        Ranked list of SearchResult objects
    """
    from agentscaffold.graph.scoping import resolve_scope

    scope = resolve_scope(project=project, all_projects=all_projects, start=start)

    target_tables = tables or CODE_TABLES

    keyword_results: list[SearchResult] = []
    semantic_results: list[SearchResult] = []

    if mode in ("keyword", "hybrid"):
        keyword_results = _keyword_search(store, query, target_tables, top_k * 2, scope)

    if mode in ("semantic", "hybrid"):
        semantic_results = _semantic_search(
            store, query, target_tables, top_k * 2, project=project, all_projects=all_projects
        )

    if mode == "keyword":
        results = keyword_results[:top_k]
        return _rerank_results(query, results, rerank_model) if rerank else results
    if mode == "semantic":
        results = semantic_results[:top_k]
        return _rerank_results(query, results, rerank_model) if rerank else results

    fused = _reciprocal_rank_fusion(keyword_results, semantic_results, top_k, rrf_k)
    return _rerank_results(query, fused, rerank_model) if rerank else fused


def _keyword_search(
    store: GraphBackend,
    query: str,
    tables: list[str],
    limit: int,
    scope: Any = None,
) -> list[SearchResult]:
    """Search using graph structure: name matching, path matching.

    Candidates are filtered in SQL with case-insensitive ``contains`` predicates
    (Plan 243) so matches are not missed when they fall outside a blind ``LIMIT``
    window. Surviving rows are still scored in Python via ``_text_match_score``.

    When *scope* targets a single project (multi-project workspace), a
    ``project = '<name>'`` predicate is AND-ed. Project names are validated
    to a safe charset so inlining is injection-safe.
    """
    results: list[SearchResult] = []
    terms = [t for t in query.lower().split() if t]
    # Cap the candidate pool after predicate filter; large enough to outrun
    # the old blind top_k*4 window, small enough for interactive MCP latency.
    candidate_limit = max(limit * 10, 100)

    project_clause = ""
    if scope is not None and not getattr(scope, "is_noop", True):
        project_clause = f"project = '{sql_escape(str(scope.project))}'"

    for table in tables:
        if table == "Function":
            where = _keyword_where(
                terms,
                ["name", "filePath", "signature"],
                project_clause=project_clause,
            )
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", name AS "n.name", '
                    f'filePath AS "n.filePath", signature AS "n.signature", '
                    f'project AS "n.project" '
                    f"FROM Function{where} LIMIT {candidate_limit}"
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
                            project=_project_of(row.get("n.project")),
                            context={"signature": row.get("n.signature", "")},
                        )
                    )

        elif table == "Class":
            where = _keyword_where(
                terms,
                ["name", "filePath"],
                project_clause=project_clause,
            )
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", name AS "n.name", '
                    f'filePath AS "n.filePath", project AS "n.project" '
                    f"FROM Class{where} LIMIT {candidate_limit}"
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
                            project=_project_of(row.get("n.project")),
                        )
                    )

        elif table == "Method":
            # className || '.' || name covers "Class.method" style queries.
            where = _keyword_where(
                terms,
                ["name", "className", "filePath", "signature"],
                project_clause=project_clause,
                extra_exprs=["(COALESCE(className, '') || '.' || COALESCE(name, ''))"],
            )
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", name AS "n.name", className AS "n.className",'
                    f' filePath AS "n.filePath", signature AS "n.signature",'
                    f' project AS "n.project"'
                    f" FROM Method{where} LIMIT {candidate_limit}"
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
                            project=_project_of(row.get("n.project")),
                            context={"signature": row.get("n.signature", "")},
                        )
                    )

        elif table == "File":
            where = _keyword_where(
                terms,
                ["path", "language"],
                project_clause=project_clause,
            )
            rows = ql(
                store,
                sql=(
                    f'SELECT id AS "n.id", path AS "n.path", '
                    f'language AS "n.language", project AS "n.project" '
                    f"FROM File{where} LIMIT {candidate_limit}"
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
                            project=_project_of(row.get("n.project")),
                        )
                    )

        elif table in GOVERNANCE_TABLES:
            cols, exprs = _governance_keyword_filter_cols(table)
            where = _keyword_where(
                terms,
                cols,
                project_clause=project_clause,
                extra_exprs=exprs,
            )
            sql = (
                f'SELECT {_governance_keyword_cols(table)}, project AS "n.project"'
                f" FROM {table}{where} LIMIT {candidate_limit}"
            )
            rows = ql(
                store,
                sql=sql,
            )
            for row in rows:
                name = row.get("n.name", row.get("n.id", ""))
                path = row.get("n.filePath", "")
                description = row.get("n.description", "")
                status = row.get("n.status", "")
                score = _text_match_score(terms, name, path, description, status)
                if score > 0:
                    results.append(
                        SearchResult(
                            node_id=row.get("n.id", ""),
                            name=name,
                            path=path,
                            node_type=table,
                            score=score,
                            source="keyword",
                            project=_project_of(row.get("n.project")),
                            context={
                                k.removeprefix("n."): v
                                for k, v in row.items()
                                if k.startswith("n.") and k != "n.project"
                            },
                        )
                    )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def _keyword_where(
    terms: list[str],
    columns: list[str],
    *,
    project_clause: str = "",
    extra_exprs: list[str] | None = None,
) -> str:
    """Build ``WHERE`` for keyword candidate fetch.

    Any term matching any column/expression is enough (OR), matching
    ``_text_match_score`` which scores when ``matches > 0``.

    Uses DuckDB ``contains(lower(...), ...)`` instead of ``ILIKE`` so ``%`` /
    ``_`` in identifiers are matched literally (no LIKE metacharacters).
    """
    clauses: list[str] = []
    if project_clause:
        clauses.append(project_clause)

    if terms:
        match_parts: list[str] = []
        exprs = list(columns) + list(extra_exprs or [])
        for term in terms:
            lit = sql_escape(term)
            for expr in exprs:
                match_parts.append(f"contains(lower(CAST({expr} AS VARCHAR)), '{lit}')")
        if match_parts:
            clauses.append("(" + " OR ".join(match_parts) + ")")

    if not clauses:
        return ""
    return " WHERE " + " AND ".join(clauses)


def _governance_keyword_filter_cols(table: str) -> tuple[list[str], list[str]]:
    """Return (plain columns, extra SQL exprs) used for governance ILIKE filters."""
    if table == "Plan":
        return ["title", "filePath", "status"], ["CAST(number AS VARCHAR)"]
    if table == "Learning":
        return ["learningId", "target", "status", "description"], []
    if table == "ReviewFinding":
        return ["category", "finding", "status", "severity"], []
    if table == "Study":
        return ["title", "filePath", "status", "outcome"], []
    if table == "ADR":
        return ["title", "filePath", "status"], ["CAST(number AS VARCHAR)"]
    if table == "Spike":
        return ["title", "filePath", "status", "parentPlan"], []
    # BacklogItem
    return ["title", "source", "status", "priority"], []


def _semantic_search(
    store: GraphBackend,
    query: str,
    tables: list[str],
    limit: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[SearchResult]:
    """Search using vector similarity (scope-aware via search_similar)."""
    try:
        from agentscaffold.graph.embeddings import search_similar
    except ImportError:
        logger.debug("sentence-transformers not available for semantic search")
        return []

    results: list[SearchResult] = []

    for table in tables:
        if table not in (*CODE_TABLES, *GOVERNANCE_TABLES):
            continue

        try:
            hits = search_similar(
                store,
                query,
                table=table,
                top_k=limit,
                project=project,
                all_projects=all_projects,
            )
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
                    project=_project_of(hit.get("project")),
                    context={k.removeprefix("n."): v for k, v in hit.items() if k.startswith("n.")},
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


def _rerank_results(
    query: str,
    results: list[SearchResult],
    model_name: str,
) -> list[SearchResult]:
    """Best-effort CrossEncoder rerank (optional, off by default)."""
    if not results:
        return results
    try:
        from sentence_transformers import CrossEncoder  # noqa: PLC0415
    except Exception:
        logger.debug("CrossEncoder unavailable; returning pre-rerank results", exc_info=True)
        return results
    try:
        model = CrossEncoder(model_name)
        pairs = [(query, f"{r.node_type} {r.name} {r.path}") for r in results]
        scores = model.predict(pairs)
    except Exception:
        logger.debug("CrossEncoder rerank failed; returning pre-rerank results", exc_info=True)
        return results

    reranked: list[SearchResult] = []
    for result, score in zip(results, scores):
        result.score = round(float(score), 6)
        reranked.append(result)
    reranked.sort(key=lambda r: r.score, reverse=True)
    return reranked


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


def _governance_keyword_cols(table: str) -> str:
    """Return a normalized SELECT list for governance keyword search."""
    if table == "Plan":
        return (
            'id AS "n.id", title AS "n.name", filePath AS "n.filePath",'
            ' status AS "n.status", CAST(number AS VARCHAR) AS "n.description"'
        )
    if table == "Learning":
        return (
            'id AS "n.id", learningId AS "n.name", target AS "n.filePath",'
            ' status AS "n.status", description AS "n.description"'
        )
    if table == "ReviewFinding":
        return (
            'id AS "n.id", category AS "n.name", finding AS "n.description",'
            ' status AS "n.status", severity AS "n.filePath"'
        )
    if table == "Study":
        return (
            'id AS "n.id", title AS "n.name", filePath AS "n.filePath",'
            ' status AS "n.status", outcome AS "n.description"'
        )
    if table == "ADR":
        return (
            'id AS "n.id", title AS "n.name", filePath AS "n.filePath",'
            ' status AS "n.status", CAST(number AS VARCHAR) AS "n.description"'
        )
    if table == "Spike":
        return (
            'id AS "n.id", title AS "n.name", filePath AS "n.filePath",'
            ' status AS "n.status", parentPlan AS "n.description"'
        )
    return (
        'id AS "n.id", title AS "n.name", source AS "n.filePath",'
        ' status AS "n.status", priority AS "n.description"'
    )


def format_search_results(results: list[SearchResult]) -> str:
    """Format search results as markdown."""
    if not results:
        return "No results found."

    # Show a Project column only for federated results (multi-project hits),
    # so cross-project provenance is always visible when it matters.
    show_project = any(r.project for r in results)

    lines = ["## Search Results", ""]
    if show_project:
        lines.append("| # | Project | Type | Name | Path | Score | Source |")
        lines.append("|---|---------|------|------|------|-------|--------|")
        for i, r in enumerate(results, 1):
            lines.append(
                f"| {i} | {r.project or '-'} | {r.node_type} | `{r.name}` | "
                f"`{r.path}` | {r.score:.4f} | {r.source} |"
            )
    else:
        lines.append("| # | Type | Name | Path | Score | Source |")
        lines.append("|---|------|------|------|-------|--------|")
        for i, r in enumerate(results, 1):
            lines.append(
                f"| {i} | {r.node_type} | `{r.name}` | `{r.path}` | {r.score:.4f} | {r.source} |"
            )

    return "\n".join(lines)
