"""Graph coverage signaling for MCP tools.

The knowledge graph only extracts call/import edges for languages that have a
tree-sitter grammar (see ``graph.parsing._GRAMMAR_MODULES``). Files in other
languages -- markdown, yaml, shell, sql, json, toml, ... -- exist as ``File``
nodes but carry no structural edges. Even within parsed languages, static
analysis cannot see dynamic dispatch, reflection, dependency-injection
registries, or config/string-driven wiring.

Without an explicit signal, an empty structural result ("0 callers") is
indistinguishable from "not analyzed" -- the classic "absence of evidence read
as evidence of absence" trap. These helpers attach honest caveats so an agent
treats empty structural results as *unconfirmed*, not *unused*, and a repo-level
coverage summary so it can calibrate trust at orientation time.
"""

from __future__ import annotations

import os
from typing import Any

# Languages for which AgentScaffold extracts call/import edges. Mirrors the keys
# of ``graph.parsing._GRAMMAR_MODULES``; kept as a local constant so this module
# has no hard dependency on tree-sitter being importable.
PARSED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "javascript", "typescript", "go", "rust", "java", "c", "cpp"}
)

# Call/method-call edges below this confidence were resolved heuristically (the
# symbol resolver could not pin the target unambiguously). Observed distribution:
# 0.5 / 0.6 = heuristic guesses, 0.85 = resolved, 0.9 = high confidence. Edges at
# or above the threshold are treated as reliable; below it, agents should verify.
HEURISTIC_CONFIDENCE_THRESHOLD: float = 0.75


def is_heuristic_confidence(confidence: Any) -> bool:
    """Return True if an edge confidence indicates a heuristic (unsure) resolution."""
    try:
        return float(confidence) < HEURISTIC_CONFIDENCE_THRESHOLD
    except (TypeError, ValueError):
        return False


def count_heuristic(rows: list[dict[str, Any]], key: str = "confidence") -> int:
    """Count rows whose ``key`` confidence is below the heuristic threshold."""
    return sum(1 for r in rows if is_heuristic_confidence(r.get(key)))


def language_for_path(path: str) -> str:
    """Return the detected language for *path* (``"unknown"`` if unmapped)."""
    from agentscaffold.graph.structure import LANGUAGE_MAP

    ext = os.path.splitext(path or "")[1].lower()
    return LANGUAGE_MAP.get(ext, "unknown")


def is_parsed_language(language: str | None) -> bool:
    """Return True if *language* has call/import edge coverage in the graph."""
    return (language or "").lower() in PARSED_LANGUAGES


def empty_result_caveat(
    *,
    target: str,
    language: str | None,
    result_count: int,
    relation: str = "callers",
) -> str | None:
    """Return a caveat when a structural result must not be read as "none".

    Returns ``None`` when the target is a parsed language and the result is
    non-empty (no caveat needed). Otherwise returns a short, agent-facing note
    explaining why an empty/low result is *unconfirmed* rather than *unused*.

    Args:
        target: The file or symbol that was queried.
        language: Detected language of the target (or its defining file).
        result_count: Number of structural results returned (callers, importers).
        relation: Human label for the relation queried (e.g. "callers").
    """
    if not is_parsed_language(language):
        lang = language or "non-code"
        return (
            f"`{target}` is a {lang} file; AgentScaffold does not extract "
            f"call/import edges for it. Empty structural results here are a "
            f"coverage gap, not evidence the file is unused. Confirm usage with "
            f"a text search (grep) before treating it as safe to change."
        )
    if result_count == 0:
        return (
            f"No {relation} found via static analysis. Static analysis does not "
            f"capture dynamic dispatch, reflection, or config/string-driven "
            f"wiring. Treat this as `unconfirmed`, not `unused` -- grep for the "
            f"name before changing it."
        )
    return None


def repo_coverage(store: Any) -> dict[str, Any]:
    """Summarize how much of the indexed corpus has structural (edge) coverage.

    Returns a dict with ``available=False`` if the query fails, otherwise totals,
    a parsed percentage, a per-language breakdown, and a one-line ``summary``
    suitable for inclusion in ``scaffold_orient`` output.
    """
    by_language: dict[str, int] = {}
    try:
        rows = store.query("SELECT language, COUNT(*) AS n FROM File GROUP BY language")
    except Exception:
        return {"available": False}

    for r in rows:
        lang = (r.get("language") or "unknown") if isinstance(r, dict) else "unknown"
        try:
            by_language[lang] = int(r.get("n") or 0)
        except (TypeError, ValueError):
            by_language[lang] = 0

    total = sum(by_language.values())
    parsed = sum(n for lang, n in by_language.items() if lang in PARSED_LANGUAGES)
    unparsed = total - parsed
    parsed_langs = sorted(lang for lang in by_language if lang in PARSED_LANGUAGES)
    unparsed_langs = sorted(
        (lang for lang in by_language if lang not in PARSED_LANGUAGES),
        key=lambda lang: -by_language[lang],
    )
    pct = round(100.0 * parsed / total, 1) if total else 0.0

    summary = (
        f"{parsed}/{total} files ({pct}%) have call/import coverage "
        f"(parsed: {', '.join(parsed_langs) or 'none'}). "
        f"{unparsed} files are structurally invisible "
        f"({', '.join(unparsed_langs[:6]) or 'none'}). "
        f"For unparsed files and dynamic/config-driven wiring, an empty "
        f"structural result is unconfirmed -- verify with grep."
    )
    return {
        "available": True,
        "total_files": total,
        "parsed_files": parsed,
        "unparsed_files": unparsed,
        "parsed_pct": pct,
        "by_language": by_language,
        "summary": summary,
    }
