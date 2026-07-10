"""Shared helpers for pre-review signal quality.

These small, pure helpers keep the challenge/gap/brief generators honest about
what the graph can and cannot say:

- ``is_source_code_file`` decides whether a heuristic that only makes sense for
  parsed code (modification-frequency instability, missing-test coverage) should
  apply. Markdown, YAML, JSON, and other governance/docs artifacts are invisible
  to structural parsing, so applying code heuristics to them produces false
  positives (e.g. append-only ``workflow_state.md`` flagged as "architecturally
  unstable").
- ``normalize_plan_status`` / ``recover_plan_date`` clean up the free-text plan
  status and recover a trailing ``(YYYY-MM-DD)`` date so historical context is
  legible.

The parsed-language set intentionally mirrors ``graph.parsing`` grammars so this
module and the indexer agree on what "code" means.
"""

from __future__ import annotations

import re

# Languages the structural indexer actually parses (tree-sitter grammars).
# Keep in sync with agentscaffold.graph.parsing._GRAMMAR_MODULES.
PARSED_CODE_LANGUAGES: frozenset[str] = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "go",
        "rust",
        "java",
        "c",
        "cpp",
    }
)

# Fallback when the graph did not record a language for a file. Extensions map
# to the same parsed-language universe above.
_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cxx",
        ".hpp",
        ".hxx",
    }
)


def is_source_code_file(path: str, language: str | None = None) -> bool:
    """Return True if ``path`` is a parsed source-code file.

    Uses the graph-recorded ``language`` when available; falls back to the file
    extension when the language is missing/empty. Non-code files (markdown,
    docs, config, state artifacts) return False so code-only heuristics skip them.
    """
    if language:
        return language.lower() in PARSED_CODE_LANGUAGES

    lowered = path.lower()
    dot = lowered.rfind(".")
    if dot == -1:
        return False
    return lowered[dot:] in _CODE_EXTENSIONS


# ---------------------------------------------------------------------------
# Plan status / date normalization
# ---------------------------------------------------------------------------

_STATUS_CANON: tuple[tuple[str, str], ...] = (
    # order matters: check more specific tokens first
    ("superseded", "Superseded"),
    ("in progress", "In Progress"),
    ("in-progress", "In Progress"),
    ("ready", "Ready"),
    ("review", "Review"),
    ("draft", "Draft"),
    ("complete", "Complete"),
    ("done", "Complete"),
)

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def normalize_plan_status(raw: str | None) -> str:
    """Map a free-text plan status onto a known vocabulary.

    Returns one of: Draft, Review, Ready, In Progress, Complete, Superseded,
    Unknown. Unrecognized/empty input maps to ``Unknown``. The raw string is not
    destroyed by callers -- they should keep it alongside this normalized value.
    """
    if not raw:
        return "Unknown"
    lowered = raw.strip().lower()
    if not lowered or lowered == "unknown":
        return "Unknown"
    for token, canonical in _STATUS_CANON:
        if token in lowered:
            return canonical
    return "Unknown"


def recover_plan_date(date_field: str | None, status: str | None = None) -> str:
    """Return a ``YYYY-MM-DD`` date, recovering it from status text if needed.

    Prefers the dedicated ``date_field``; if empty, extracts a trailing date
    embedded in the status string (e.g. ``"COMPLETE (2026-07-09)"``). Returns an
    empty string when no date is available.
    """
    if date_field:
        m = _DATE_RE.search(date_field)
        if m:
            return m.group(1)
        return date_field.strip()
    if status:
        m = _DATE_RE.search(status)
        if m:
            return m.group(1)
    return ""
