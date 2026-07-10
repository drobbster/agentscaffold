"""Tests for Plan 239: federated search reports project provenance.

Covers deriving the owning project from a project-qualified node id, the
``SearchResult.project`` field, and the conditional Project column in the
rendered markdown (shown only for federated/multi-project results).
"""

from __future__ import annotations

from agentscaffold.graph.search import (
    SearchResult,
    _project_of,
    format_search_results,
)


def test_project_of_normalizes_empty_to_none():
    # Single-project repos store an empty project column; that must read as None,
    # while a real project name is preserved for federated provenance.
    assert _project_of("") is None
    assert _project_of(None) is None
    assert _project_of("alpha") == "alpha"


def test_format_shows_project_column_when_federated():
    results = [
        SearchResult(
            node_id="a",
            name="foo",
            path="x.py",
            node_type="Function",
            score=0.9,
            source="keyword",
            project="alpha",
        ),
        SearchResult(
            node_id="b",
            name="bar",
            path="y.py",
            node_type="Function",
            score=0.5,
            source="keyword",
            project="beta",
        ),
    ]
    md = format_search_results(results)
    assert "Project" in md
    assert "alpha" in md
    assert "beta" in md


def test_format_omits_project_column_single_project():
    results = [
        SearchResult(
            node_id="a",
            name="foo",
            path="x.py",
            node_type="Function",
            score=0.9,
            source="keyword",
        ),
    ]
    md = format_search_results(results)
    assert "Project" not in md
    assert "| # | Type | Name | Path | Score | Source |" in md


def test_search_result_project_defaults_none():
    r = SearchResult(
        node_id="a", name="foo", path="x.py", node_type="File", score=1.0, source="keyword"
    )
    assert r.project is None
