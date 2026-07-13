"""Tests for graph coverage signaling (Plan 214, P1)."""

from __future__ import annotations

from typing import Any

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import ScaffoldConfig
from agentscaffold.mcp.coverage import (
    HEURISTIC_CONFIDENCE_THRESHOLD,
    PARSED_LANGUAGES,
    count_heuristic,
    empty_result_caveat,
    is_heuristic_confidence,
    is_parsed_language,
    language_for_path,
    repo_coverage,
)
from agentscaffold.mcp.render import format_context_markdown, format_impact_markdown


def test_language_for_path() -> None:
    assert language_for_path("libs/risk/exit.py") == "python"
    assert language_for_path("web/app.tsx") == "typescript"
    assert language_for_path("configs/trading.yaml") == "yaml"
    assert language_for_path("run.sh") == "shell"
    assert language_for_path("schema.sql") == "sql"
    assert language_for_path("README.md") == "markdown"
    assert language_for_path("noext") == "unknown"


def test_is_parsed_language() -> None:
    assert is_parsed_language("python")
    assert is_parsed_language("TypeScript")  # case-insensitive
    assert not is_parsed_language("yaml")
    assert not is_parsed_language("markdown")
    assert not is_parsed_language(None)
    assert PARSED_LANGUAGES  # non-empty registry


def test_empty_result_caveat_unparsed_language() -> None:
    caveat = empty_result_caveat(target="configs/trading.yaml", language="yaml", result_count=0)
    assert caveat is not None
    assert "does not extract" in caveat
    assert "grep" in caveat


def test_empty_result_caveat_unparsed_even_with_results() -> None:
    # Unparsed languages always get the coverage-gap caveat, even if some rows.
    caveat = empty_result_caveat(target="x.sql", language="sql", result_count=3)
    assert caveat is not None
    assert "coverage gap" in caveat


def test_empty_result_caveat_parsed_zero() -> None:
    caveat = empty_result_caveat(
        target="thing", language="python", result_count=0, relation="callers"
    )
    assert caveat is not None
    assert "unconfirmed" in caveat
    assert "dynamic dispatch" in caveat


def test_empty_result_caveat_parsed_nonzero_is_none() -> None:
    assert empty_result_caveat(target="thing", language="python", result_count=5) is None


class _FakeStore:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def query(self, sql: str) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._rows


def test_repo_coverage_totals_and_summary() -> None:
    store = _FakeStore(
        [
            {"language": "python", "n": 700},
            {"language": "typescript", "n": 50},
            {"language": "markdown", "n": 400},
            {"language": "yaml", "n": 150},
            {"language": "unknown", "n": 40},
        ]
    )
    cov = repo_coverage(store)
    assert cov["available"] is True
    assert cov["total_files"] == 1340
    assert cov["parsed_files"] == 750
    assert cov["unparsed_files"] == 590
    assert cov["parsed_pct"] == round(100.0 * 750 / 1340, 1)
    assert cov["by_language"]["markdown"] == 400
    assert "have call/import coverage" in cov["summary"]
    assert "verify with grep" in cov["summary"]


def test_repo_coverage_unavailable_on_error() -> None:
    class _BadStore:
        def query(self, sql: str) -> list[dict[str, Any]]:  # noqa: ARG002
            raise RuntimeError("no db")

    assert repo_coverage(_BadStore()) == {"available": False}


def test_repo_coverage_empty_graph() -> None:
    cov = repo_coverage(_FakeStore([]))
    assert cov["available"] is True
    assert cov["total_files"] == 0
    assert cov["parsed_pct"] == 0.0


def test_format_impact_markdown_appends_caveat() -> None:
    md = format_impact_markdown("configs/x.yaml", [], [], [], caveat="THIS IS THE CAVEAT")
    assert "Coverage note: THIS IS THE CAVEAT" in md


def test_format_impact_markdown_no_caveat() -> None:
    md = format_impact_markdown("a.py", [], [], [])
    assert "Coverage note:" not in md


def test_format_context_markdown_appends_caveat() -> None:
    md = format_context_markdown(
        {"name": "foo", "filePath": "a.py"}, [], [], [], caveat="DYNAMIC WARNING"
    )
    assert "Coverage note: DYNAMIC WARNING" in md


def test_rule_policy_includes_graph_trust_discipline() -> None:
    doc = generate_rule_policy_document(config=ScaffoldConfig(), title="Test Rules")
    assert "Graph Trust Discipline" in doc
    assert "unconfirmed" in doc
    assert "grep" in doc
    assert "why_empty" in doc
    assert "grep_fallback" in doc


def test_rule_policy_includes_call_compression_discipline() -> None:
    doc = generate_rule_policy_document(config=ScaffoldConfig(), title="Test Rules")
    assert "Call Compression Discipline" in doc
    assert "scaffold_diff_plan_vs_code" in doc
    assert "recommended_actions" in doc
    assert "Fallback only" in doc or "fallback only" in doc.lower()
    # Intent notes present for fused vs standalone tools
    assert "Prefer inline `why_empty`" in doc or "inline `why_empty`" in doc
    assert "scaffold_why_empty" in doc
    assert "scaffold_next_action" in doc


def test_rule_policy_identical_across_quote_modes_for_compression() -> None:
    """Cursor quotes intents; Windsurf/prompt may not -- policy body must match."""
    cfg = ScaffoldConfig()
    quoted = generate_rule_policy_document(config=cfg, title="A", quote_intents=True)
    plain = generate_rule_policy_document(config=cfg, title="A", quote_intents=False)
    assert "Call Compression Discipline" in quoted
    assert "Call Compression Discipline" in plain
    assert "High-Value MCP-First Routes" in quoted
    assert "High-Value MCP-First Routes" in plain


def test_rule_policy_includes_multiproject_scope_discipline() -> None:
    doc = generate_rule_policy_document(config=ScaffoldConfig(), title="Test Rules")
    assert "Multi-Project Workspace Discipline" in doc
    # Teaches the current-project default and the explicit widening flags.
    assert "--all-projects" in doc
    assert "--project" in doc
    assert "scaffold workspace list" in doc


# --- P2: edge confidence surfacing ---


def test_is_heuristic_confidence_threshold() -> None:
    assert HEURISTIC_CONFIDENCE_THRESHOLD == 0.75
    assert is_heuristic_confidence(0.5)
    assert is_heuristic_confidence(0.6)
    assert not is_heuristic_confidence(0.85)
    assert not is_heuristic_confidence(0.9)
    assert not is_heuristic_confidence(None)
    assert not is_heuristic_confidence("not-a-number")


def test_count_heuristic() -> None:
    rows = [
        {"name": "a", "confidence": 0.5},
        {"name": "b", "confidence": 0.85},
        {"name": "c", "confidence": 0.6},
        {"name": "d"},  # missing confidence -> not heuristic
    ]
    assert count_heuristic(rows) == 2


def test_format_context_markdown_annotates_low_confidence() -> None:
    callers = [
        {"name": "solid", "filePath": "a.py", "confidence": 0.85},
        {"name": "guess", "filePath": "b.py", "confidence": 0.5},
    ]
    md = format_context_markdown({"name": "foo", "filePath": "f.py"}, callers, [], [])
    assert "Callers (2, 1 heuristic)" in md
    assert "[confidence 0.50, heuristic]" in md
    # High-confidence caller is not annotated.
    assert "`solid`" in md
    assert "solid`  (a.py)\n" in md or "solid`  (a.py)" in md


def test_format_impact_markdown_annotates_low_confidence() -> None:
    callers = [{"name": "guess", "filePath": "b.py", "confidence": 0.6}]
    md = format_impact_markdown("x.py", [], callers, [])
    assert "Functions calling into this file (1, 1 heuristic)" in md
    assert "[confidence 0.60, heuristic]" in md


# --- P2.2: coverage check on scaffold_validate ---


def test_tool_validate_coverage_check() -> None:
    from agentscaffold.mcp.server import _tool_validate

    store = _FakeStore(
        [
            {"language": "python", "n": 100},
            {"language": "yaml", "n": 50},
        ]
    )
    result = _tool_validate(store, {"check": "coverage"}, {})
    assert result["report"]["available"] is True
    assert result["report"]["total_files"] == 150
    assert result["report"]["parsed_files"] == 100
