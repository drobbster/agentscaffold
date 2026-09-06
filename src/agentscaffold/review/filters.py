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
    best_pos: int | None = None
    best: str | None = None
    for token, canonical in _STATUS_CANON:
        pos = lowered.find(token)
        if pos == -1:
            continue
        if best_pos is None or pos < best_pos:
            best_pos = pos
            best = canonical
    return best or "Unknown"


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


# ---------------------------------------------------------------------------
# Plan file-overlap noise denylist (Plan 245)
# ---------------------------------------------------------------------------

# Ubiquitous governance docs that nearly every plan touches. Counting them as
# "shared impacted files" floods staleness / compare / prior-experiment signals.
DEFAULT_OVERLAP_NOISE_PATHS: frozenset[str] = frozenset(
    {
        "docs/ai/contracts/README.md",
        "docs/ai/state/workflow_state.md",
        "docs/ai/backlog.md",
        "docs/ai/architectural_design_changelog.md",
    }
)


def normalize_plan_file_path(path: str) -> str:
    """Normalize a plan File Impact path for overlap comparison."""
    return path.replace("\\", "/").lstrip("./").strip()


def resolve_overlap_noise_paths(configured: list[str] | None = None) -> frozenset[str]:
    """Return the active noise denylist.

    ``None`` (config omitted) uses :data:`DEFAULT_OVERLAP_NOISE_PATHS`. An
    explicit list (including empty) replaces the defaults so operators can
    disable or customize filtering via ``graph.overlap_noise_paths``.
    """
    if configured is None:
        return DEFAULT_OVERLAP_NOISE_PATHS
    return frozenset(normalize_plan_file_path(p) for p in configured if p and str(p).strip())


def is_overlap_noise_path(path: str, noise_paths: frozenset[str] | None = None) -> bool:
    """Return True if ``path`` is a denylisted governance noise path."""
    if not path:
        return False
    noise = noise_paths if noise_paths is not None else DEFAULT_OVERLAP_NOISE_PATHS
    if not noise:
        return False
    normalized = normalize_plan_file_path(path)
    if normalized in noise:
        return True
    for noise_path in noise:
        if normalized.endswith("/" + noise_path):
            return True
    return False


def meaningful_plan_file_overlap(
    files_a: set[str] | frozenset[str] | list[str],
    files_b: set[str] | frozenset[str] | list[str],
    *,
    noise_paths: frozenset[str] | None = None,
    path_frequency: dict[str, int] | None = None,
    frequency_demote_threshold: int = 5,
) -> tuple[list[str], list[str]]:
    """Split shared plan files into (meaningful, noise) sorted lists.

    Meaningful overlaps drive staleness / conflict_risk. Noise overlaps are
    returned for audit transparency (``overlap_noise_filtered``).

    When ``path_frequency`` is provided (path -> number of completed plans that
    touch it), paths at or above ``frequency_demote_threshold`` are treated as
    noise unless they are the only shared meaningful path (Plan 247).
    """
    noise = noise_paths if noise_paths is not None else DEFAULT_OVERLAP_NOISE_PATHS
    shared = {normalize_plan_file_path(f) for f in files_a if f} & {
        normalize_plan_file_path(f) for f in files_b if f
    }
    shared.discard("")
    meaningful: list[str] = []
    noise_shared: list[str] = []
    for path in sorted(shared):
        if is_overlap_noise_path(path, noise):
            noise_shared.append(path)
        else:
            meaningful.append(path)

    if path_frequency and meaningful:
        core: list[str] = []
        demoted: list[str] = []
        for path in meaningful:
            freq = int(path_frequency.get(path, 0))
            if freq >= frequency_demote_threshold:
                demoted.append(path)
            else:
                core.append(path)
        # Keep at least one meaningful signal when everything was ubiquitous.
        if not core and demoted:
            core = [rank_lead_overlap(demoted, limit=1)[0]]
            demoted = [p for p in demoted if p not in core]
        meaningful = core
        noise_shared.extend(demoted)

    return meaningful, noise_shared


# Soft-noise: governance/docs paths that are not on the hard denylist but are
# usually weak conflict signals compared to code/config (Plan 247).
_SOFT_NOISE_PREFIXES: tuple[str, ...] = (
    "docs/ai/templates/",
    "docs/ai/standards/",
    "docs/ai/state/",
    "docs/ai/prompts/",
    "docs/ai/contracts/",
)
_SOFT_NOISE_BASENAMES: frozenset[str] = frozenset(
    {"AGENTS.md", "CLAUDE.md", "README.md", ".gitignore"}
)


def overlap_signal_weight(path: str) -> int:
    """Lower weight = stronger lead signal for agents.

    Code/config paths rank ahead of docs/governance soft-noise.
    """
    n = normalize_plan_file_path(path)
    if is_overlap_noise_path(n):
        return 100
    if n in _SOFT_NOISE_BASENAMES or any(n.endswith("/" + b) for b in _SOFT_NOISE_BASENAMES):
        return 60
    if any(n.startswith(p) or f"/{p}" in f"/{n}" for p in _SOFT_NOISE_PREFIXES):
        return 50
    if n.startswith("docs/"):
        return 40
    return 0


def rank_lead_overlap(paths: list[str], *, limit: int = 5) -> list[str]:
    """Return the most agent-useful shared paths first (Plan 247 lead signal)."""
    ranked = sorted(
        {normalize_plan_file_path(p) for p in paths if p},
        key=lambda p: (overlap_signal_weight(p), p),
    )
    return ranked[: max(0, limit)]
