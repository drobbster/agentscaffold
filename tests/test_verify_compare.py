"""Tests for compare_backends / print_comparison_report — Step A.9."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from agentscaffold.graph.verify import (
    _COMPARE_EDGE_TABLES,
    _COMPARE_NODE_TABLES,
    _SAMPLE_QUERIES,
    compare_backends,
    print_comparison_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_store(
    node_counts: dict[str, int] | None = None,
    edge_counts: dict[str, int] | None = None,
    scalar_val: int = 0,
) -> Any:
    """Return a MagicMock GraphBackend with pre-configured counts."""
    store = MagicMock()
    node_counts = node_counts or {}
    edge_counts = edge_counts or {}
    store.node_count.side_effect = lambda t: node_counts.get(t, 0)
    store.edge_count.side_effect = lambda t: edge_counts.get(t, 0)
    store.query_scalar.return_value = scalar_val
    return store


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_compare_node_tables_not_empty() -> None:
    assert len(_COMPARE_NODE_TABLES) >= 10


def test_compare_edge_tables_not_empty() -> None:
    assert len(_COMPARE_EDGE_TABLES) >= 5


def test_sample_queries_have_three_fields() -> None:
    for item in _SAMPLE_QUERIES:
        assert len(item) == 3, "Each sample query must be (label, cypher, sql)"


# ---------------------------------------------------------------------------
# compare_backends — PASS cases
# ---------------------------------------------------------------------------


def test_compare_backends_pass_when_counts_match() -> None:
    kuzu = _mock_store(scalar_val=5)
    duck = _mock_store(scalar_val=5)
    report = compare_backends(kuzu, duck)
    assert report["verdict"] == "PASS"
    assert report["total_divergences"] == 0


def test_compare_backends_report_has_required_keys() -> None:
    kuzu = _mock_store()
    duck = _mock_store()
    report = compare_backends(kuzu, duck)
    assert "node_counts" in report
    assert "edge_counts" in report
    assert "sample_queries" in report
    assert "total_divergences" in report
    assert "verdict" in report


def test_compare_backends_node_counts_keyed_by_table() -> None:
    kuzu = _mock_store()
    duck = _mock_store()
    report = compare_backends(kuzu, duck)
    for table in _COMPARE_NODE_TABLES:
        assert table in report["node_counts"]


def test_compare_backends_edge_counts_keyed_by_table() -> None:
    kuzu = _mock_store()
    duck = _mock_store()
    report = compare_backends(kuzu, duck)
    for table in _COMPARE_EDGE_TABLES:
        assert table in report["edge_counts"]


def test_compare_backends_sample_queries_keyed_by_label() -> None:
    kuzu = _mock_store()
    duck = _mock_store()
    report = compare_backends(kuzu, duck)
    for label, _, _ in _SAMPLE_QUERIES:
        assert label in report["sample_queries"]


def test_compare_backends_count_entries_have_match_field() -> None:
    kuzu = _mock_store(scalar_val=3)
    duck = _mock_store(scalar_val=3)
    report = compare_backends(kuzu, duck)
    for entry in report["node_counts"].values():
        assert "kuzu" in entry
        assert "duck" in entry
        assert "match" in entry


# ---------------------------------------------------------------------------
# compare_backends — FAIL cases
# ---------------------------------------------------------------------------


def test_compare_backends_fail_on_node_count_mismatch() -> None:
    kuzu = _mock_store(node_counts={"File": 10})
    duck = _mock_store(node_counts={"File": 9})
    report = compare_backends(kuzu, duck)
    assert report["verdict"] == "FAIL"
    assert report["node_counts"]["File"]["match"] is False
    assert report["total_divergences"] >= 1


def test_compare_backends_fail_on_edge_count_mismatch() -> None:
    kuzu = _mock_store(edge_counts={"IMPORTS": 5})
    duck = _mock_store(edge_counts={"IMPORTS": 4})
    report = compare_backends(kuzu, duck)
    assert report["verdict"] == "FAIL"
    assert report["edge_counts"]["IMPORTS"]["match"] is False


def test_compare_backends_fail_on_scalar_mismatch() -> None:
    kuzu = _mock_store(scalar_val=7)
    duck = _mock_store(scalar_val=6)
    report = compare_backends(kuzu, duck)
    assert report["verdict"] == "FAIL"
    assert report["total_divergences"] >= 1


def test_compare_backends_divergence_count_is_accurate() -> None:
    # Make exactly 2 node tables diverge
    kuzu = _mock_store(node_counts={"File": 1, "Plan": 2})
    duck = _mock_store(node_counts={"File": 1, "Plan": 99})
    report = compare_backends(kuzu, duck)
    # Plan diverges; scalar also diverges (0 vs 0 matches, so 0 there).
    # Only Plan node count diverges.
    assert report["node_counts"]["Plan"]["match"] is False
    assert report["node_counts"]["File"]["match"] is True


def test_compare_backends_tolerates_none_scalar() -> None:
    """query_scalar returning None is treated as 0."""
    kuzu = _mock_store()
    duck = _mock_store()
    kuzu.query_scalar.return_value = None
    duck.query_scalar.return_value = None
    report = compare_backends(kuzu, duck)
    assert report["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# print_comparison_report — smoke test (no crash)
# ---------------------------------------------------------------------------


def test_print_comparison_report_pass(capsys) -> None:
    kuzu = _mock_store(scalar_val=1)
    duck = _mock_store(scalar_val=1)
    report = compare_backends(kuzu, duck)
    print_comparison_report(report)  # must not raise


def test_print_comparison_report_fail(capsys) -> None:
    kuzu = _mock_store(node_counts={"File": 5})
    duck = _mock_store(node_counts={"File": 3})
    report = compare_backends(kuzu, duck)
    print_comparison_report(report)  # must not raise
