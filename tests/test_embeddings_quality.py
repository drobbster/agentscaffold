"""Search-quality unit tests for embedding text enrichment (Plan 227, Tier 1).

These exercise the pure, dependency-light helpers -- L2 normalization, docstring
/ leading-comment extraction, and source-slice enrichment -- without invoking
sentence-transformers, so they run even when the ``[search]`` extra is absent.
The model-encoding path is covered by the existing embeddings integration tests.
"""

from __future__ import annotations

import math

from agentscaffold.graph.embeddings import (
    GOVERNANCE_TABLES,
    _build_enriched_text,
    _build_text_for_review_finding,
    _enrich_text,
    _extract_leading_doc,
    _hash_text,
    _normalize,
)

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_unit_length():
    out = _normalize([3.0, 4.0])
    assert math.isclose(sum(x * x for x in out) ** 0.5, 1.0, rel_tol=1e-9)
    assert math.isclose(out[0], 0.6) and math.isclose(out[1], 0.8)


def test_normalize_zero_vector_unchanged():
    assert _normalize([0.0, 0.0]) == [0.0, 0.0]


# ---------------------------------------------------------------------------
# Docstring / comment extraction
# ---------------------------------------------------------------------------


def test_extract_triple_quoted_docstring():
    src = '    """Compute the risk-adjusted return."""\n    return x\n'
    assert _extract_leading_doc(src) == "Compute the risk-adjusted return."


def test_extract_leading_hash_comments():
    src = "# first line\n# second line\nx = 1\n"
    assert _extract_leading_doc(src) == "first line second line"


def test_extract_leading_slash_comments():
    src = "// header doc\nint x = 1;\n"
    assert _extract_leading_doc(src) == "header doc"


def test_extract_returns_empty_when_no_doc():
    assert _extract_leading_doc("x = 1\ny = 2\n") == ""


def test_extract_truncates_long_doc():
    long = '"""' + ("word " * 300) + '"""'
    assert len(_extract_leading_doc(long)) <= 400


# ---------------------------------------------------------------------------
# Source-slice enrichment
# ---------------------------------------------------------------------------


def test_enrich_reads_function_docstring_from_slice(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text('def foo():\n    """Does the foo thing."""\n    return 1\n')
    row = {"n.filePath": "mod.py", "n.startLine": 1, "n.endLine": 3}
    assert _enrich_text(tmp_path, "Function", row) == "Does the foo thing."


def test_enrich_missing_file_returns_empty(tmp_path):
    row = {"n.filePath": "nope.py", "n.startLine": 1, "n.endLine": 3}
    assert _enrich_text(tmp_path, "Function", row) == ""


def test_enrich_file_reads_head(tmp_path):
    f = tmp_path / "head.py"
    f.write_text('"""Module-level summary."""\nimport os\n')
    row = {"n.path": "head.py"}
    assert _enrich_text(tmp_path, "File", row) == "Module-level summary."


def test_build_enriched_text_appends_doc(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text('def foo():\n    """Foo summary."""\n    return 1\n')
    row = {
        "n.id": "func::foo",
        "n.name": "foo",
        "n.signature": "foo()",
        "n.filePath": "mod.py",
        "n.startLine": 1,
        "n.endLine": 3,
    }
    text = _build_enriched_text(tmp_path, "Function", row)
    assert "function foo" in text
    assert "doc: Foo summary." in text


def test_build_enriched_text_without_doc_is_base(tmp_path):
    row = {
        "n.id": "c::C",
        "n.name": "C",
        "n.filePath": "absent.py",
        "n.startLine": 1,
        "n.endLine": 2,
    }
    text = _build_enriched_text(tmp_path, "Class", row)
    assert text == "class C | in module absent"


def test_governance_tables_are_embeddable():
    assert {"Plan", "ReviewFinding", "Learning", "ADR"}.issubset(set(GOVERNANCE_TABLES))


def test_review_finding_text_builder_includes_finding_and_status():
    row = {
        "n.id": "finding::1",
        "n.severity": "high",
        "n.category": "missing tests",
        "n.finding": "No test covers stale plan execution.",
        "n.resolution": "Add pre-execution checklist coverage.",
        "n.status": "open",
    }
    text = _build_text_for_review_finding(row)
    assert "No test covers stale plan execution." in text
    assert "missing tests" in text
    assert "status: open" in text


def test_hash_text_is_stable_and_changes_with_content():
    assert _hash_text("same") == _hash_text("same")
    assert _hash_text("same") != _hash_text("different")
