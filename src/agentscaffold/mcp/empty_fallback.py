"""Helpers to attach empty-result diagnosis + grep fallback (Plan 247)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def attach_empty_fallback(
    payload: dict[str, Any],
    *,
    store: Any,
    root: Path,
    meta: dict[str, Any],
    kind: str,
    target: str = "",
    query: str = "",
    max_grep_hits: int = 8,
) -> dict[str, Any]:
    """Attach inline ``why_empty`` and ``grep_fallback`` to an empty result.

    Collapses the search/impact -> why_empty -> grep hop chain into one response.
    """
    from agentscaffold.mcp.why_empty import explain_why_empty
    from agentscaffold.mcp.workspace_grep import workspace_grep

    payload = dict(payload)
    why = explain_why_empty(
        store,
        kind=kind,
        target=target,
        query=query,
        meta=meta,
        arguments_hint={
            "file_or_symbol": target,
            "symbol": target,
            "query": query,
        },
    )
    payload["why_empty"] = why

    pattern = (query or target or "").strip()
    if "/" in pattern or "\\" in pattern:
        pattern = pattern.replace("\\", "/").rsplit("/", 1)[-1]
    if not pattern:
        return payload

    grep = workspace_grep(root, pattern, max_hits=max_grep_hits)
    if "error" in grep:
        return payload

    payload["grep_fallback"] = {
        "pattern": pattern,
        "count": grep.get("count", 0),
        "hits": grep.get("hits", [])[:max_grep_hits],
        "engine": grep.get("engine"),
        "hint": (
            "Inline fallback so empty graph/search does not require a second tool call"
        ),
    }
    if grep.get("count"):
        prior = [s for s in why.get("suggestions", []) if "grep" not in s.lower()]
        why["suggestions"] = [
            f"grep_fallback found {grep['count']} text hit(s) for {pattern!r}; "
            "use those paths instead of treating the empty graph result as unused."
        ] + prior[:4]
    return payload
