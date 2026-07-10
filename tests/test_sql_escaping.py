"""Tests for Plan 239: correct, consistent SQL string-literal escaping.

Covers the ``sql_escape`` helper (DuckDB quote-doubling, backslash-literal) and a
round-trip proving that identifiers containing an apostrophe no longer break the
graph queries that build SQL by f-string interpolation.
"""

from __future__ import annotations

from agentscaffold.graph.query_compat import sql_escape

# ---------------------------------------------------------------------------
# sql_escape helper
# ---------------------------------------------------------------------------


def test_sql_escape_doubles_single_quotes():
    assert sql_escape("O'Brien") == "O''Brien"
    assert sql_escape("it's a 'test'") == "it''s a ''test''"


def test_sql_escape_leaves_backslash_literal():
    # DuckDB treats backslash as a literal in ordinary string literals; it must
    # NOT be doubled (the old code did, which corrupted paths on Windows-style
    # separators).
    assert sql_escape("a\\b") == "a\\b"
    assert sql_escape("path\\to\\file") == "path\\to\\file"


def test_sql_escape_handles_plain_and_empty():
    assert sql_escape("") == ""
    assert sql_escape("normal_name") == "normal_name"


# ---------------------------------------------------------------------------
# Round-trip: apostrophe-bearing identifiers survive the query layer
# ---------------------------------------------------------------------------


def _store():
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    s = DuckPGQBackend(":memory:")
    s.init_schema()
    return s


def test_apostrophe_path_query_round_trips():
    """A File path with an apostrophe must be queryable without a SQL error.

    Before Plan 239 the backslash-escaping variant left the quote unescaped, so
    the generated SQL was malformed for such a path.
    """
    from agentscaffold.review.queries import get_contracts_for_file, get_file_layer

    quirky = "src/agentscaffold/o'brien/module.py"
    store = _store()
    try:
        store.create_node("File", {"id": "file::0", "path": quirky, "language": "python"})

        # Neither call should raise; both simply return "no result" for this path.
        assert get_file_layer(store, quirky) is None
        assert get_contracts_for_file(store, quirky) == []
    finally:
        store.close()


def test_apostrophe_study_outcome_query_round_trips():
    from agentscaffold.review.queries import get_studies_by_outcome

    store = _store()
    try:
        # Must not raise even though the outcome fragment contains a quote.
        assert get_studies_by_outcome(store, "beat the team's baseline") == []
    finally:
        store.close()
