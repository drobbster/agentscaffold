"""Explain empty structural/search results (Plan 246)."""

from __future__ import annotations

from typing import Any

from agentscaffold.mcp.coverage import (
    empty_result_caveat,
    is_parsed_language,
    language_for_path,
    repo_coverage,
)


def explain_why_empty(
    store: Any,
    *,
    kind: str = "structural",
    target: str = "",
    query: str = "",
    meta: dict[str, Any] | None = None,
    arguments_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a single structured explanation for an empty agent result.

    ``kind`` is one of: structural, search, impact, context, generic.
    """
    meta = meta or {}
    reasons: list[str] = []
    suggestions: list[str] = []

    # Lock / refresh
    if meta.get("refresh_in_progress") or meta.get("freshness_status") == "refreshing":
        reasons.append("Graph refresh is in progress; results may be empty or briefly stale.")
        suggestions.append("Retry the same tool shortly, or use scaffold_grep_graph as a fallback.")
    if meta.get("graph_locked"):
        reasons.append("Graph was locked when the prior call failed.")
        suggestions.append("Wait for refresh/index to finish, then retry.")

    # Wrong / missing args
    args = arguments_hint or {}
    has_target = bool(target or args.get("file_or_symbol") or args.get("symbol"))
    if kind in {"structural", "impact", "context"} and not has_target:
        reasons.append(
            "Required target argument is missing or empty (file_or_symbol / symbol)."
        )
        suggestions.append(
            "Re-call with file_or_symbol set to a repo-relative path or symbol name."
        )

    # Coverage
    coverage = repo_coverage(store)
    if coverage.get("available") and coverage.get("parsed_pct", 100) < 40:
        reasons.append(
            f"Low structural coverage ({coverage.get('parsed_pct')}% parsed files); "
            "many paths have no call/import edges."
        )
        suggestions.append("Use scaffold_grep_graph for text hits when coverage is low.")

    lang = language_for_path(target) if target else "unknown"
    caveat = None
    if target:
        caveat = empty_result_caveat(
            target=target,
            language=lang,
            result_count=0,
            relation="importers or callers" if kind in {"impact", "structural"} else "matches",
        )
        if caveat:
            reasons.append(caveat)
        if not is_parsed_language(lang):
            suggestions.append(
                "Prefer scaffold_grep_graph for non-parsed languages (md/yaml/shell/...)."
            )

    # Retrieval / embeddings
    if kind == "search":
        degraded = meta.get("retrieval_status") == "degraded"
        keyword_only = meta.get("retrieval_effective_mode") == "keyword"
        if degraded or keyword_only:
            reasons.append(
                "Search is degraded/keyword-only"
                f" ({meta.get('retrieval_reason') or 'no embeddings'})."
            )
            suggestions.append(
                "Run `scaffold index --embeddings` or use scaffold_grep_graph."
            )
        if query:
            suggestions.append(
                f"Confirm the symbol exists via scaffold_grep_graph with pattern={query!r}."
            )

    # Empty graph
    try:
        stats = store.get_stats()
        if stats.get("files", 0) == 0:
            reasons.append("Graph has 0 files -- index may not have run.")
            suggestions.append("Run `scaffold index` then retry.")
    except Exception:
        pass

    if not reasons:
        reasons.append(
            "No hits found. This may be a true negative or an unconfirmed static-analysis gap."
        )
        suggestions.append("Verify with scaffold_grep_graph before treating as unused.")

    return {
        "kind": kind,
        "target": target or None,
        "query": query or None,
        "reasons": reasons,
        "suggestions": suggestions[:5],
        "coverage": coverage if coverage.get("available") else None,
        "target_language": lang if target else None,
        "retrieval_status": meta.get("retrieval_status"),
        "freshness_status": meta.get("freshness_status"),
        "read_during_refresh": meta.get("read_during_refresh"),
    }
