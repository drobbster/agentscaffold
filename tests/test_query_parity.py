"""Parity tests: review/queries.py returns equivalent results on both backends.

Each test inserts the same data into a KuzuBackend (Cypher) and a
DuckPGQBackend (SQL), calls the same query function from review/queries.py,
and asserts that the normalised results match.

Skip conditions:
  - Entire module is skipped if *either* kuzu or duckdb is unavailable.
  - Individual tests can skip extra backends independently via pytest.importorskip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# Both backends must be present for parity tests to be meaningful.
kuzu = pytest.importorskip("kuzu", reason="kuzu not installed")
duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402
from agentscaffold.graph.store import GraphStore  # noqa: E402
from agentscaffold.review import queries  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_FILE_A = {
    "id": "file::src/alpha.py",
    "path": "src/alpha.py",
    "language": "python",
    "size": 100,
    "lastModified": "2026-01-01",
    "lineCount": 10,
    "contentHash": "aaa",
}
_FILE_B = {
    "id": "file::src/beta.py",
    "path": "src/beta.py",
    "language": "python",
    "size": 200,
    "lastModified": "2026-01-01",
    "lineCount": 20,
    "contentHash": "bbb",
}
_PLAN_1 = {
    "id": "p:1",
    "number": 1,
    "title": "Alpha Plan",
    "status": "COMPLETE",
    "planType": "feature",
    "filePath": "docs/ai/plans/001-alpha.md",
    "createdDate": "2026-01-01",
    "lastUpdated": "2026-01-02",
}
_PLAN_2 = {
    "id": "p:2",
    "number": 2,
    "title": "Beta Plan",
    "status": "IN_PROGRESS",
    "planType": "bug",
    "filePath": "docs/ai/plans/002-beta.md",
    "createdDate": "2026-01-03",
    "lastUpdated": "2026-01-04",
}
_FUNC_A = {
    "id": "fn::src/alpha.py::do_thing",
    "name": "do_thing",
    "filePath": "src/alpha.py",
    "startLine": 1,
    "endLine": 5,
    "isExported": True,
    "paramCount": 0,
    "signature": "do_thing()",
}
_FUNC_B = {
    "id": "fn::src/beta.py::call_it",
    "name": "call_it",
    "filePath": "src/beta.py",
    "startLine": 1,
    "endLine": 5,
    "isExported": True,
    "paramCount": 0,
    "signature": "call_it()",
}
_ADR_1 = {
    "id": "adr:1",
    "number": 1,
    "title": "Use DuckDB",
    "status": "Accepted",
    "date": "2026-01-01",
    "filePath": "docs/ai/adr/001-duckdb.md",
    "relatedPlans": "1",
    "relatedADRs": "",
    "supersededBy": "",
}
_ADR_2 = {
    "id": "adr:2",
    "number": 2,
    "title": "Old Decision",
    "status": "Superseded by ADR-003",
    "date": "2025-01-01",
    "filePath": "docs/ai/adr/002-old.md",
    "relatedPlans": "",
    "relatedADRs": "3",
    "supersededBy": "3",
}
_SPIKE_1 = {
    "id": "spike:1",
    "title": "DuckPGQ validation spike",
    "parentPlan": "1",
    "status": "COMPLETE",
    "created": "2026-01-01",
    "timeBox": "2h",
    "filePath": "docs/ai/spikes/spike-001.md",
}
_STUDY_1 = {
    "id": "study:1",
    "studyId": "STU-001",
    "title": "Graph backend study",
    "studyType": "comparison",
    "status": "COMPLETE",
    "outcome": "recommendation",
    "confidence": "high",
    "tags": "duckdb,graph",
    "started": "2026-01-01",
    "completed": "2026-01-10",
}
_FINDING_1 = {
    "id": "rf:1",
    "reviewType": "code",
    "planNumber": 1,
    "category": "correctness",
    "finding": "Missing null check",
    "severity": "warning",
    "status": "OPEN",
}


def _populate(store: Any) -> None:
    """Insert shared test data into *store* (works for both backends)."""
    store.create_node("File", _FILE_A)
    store.create_node("File", _FILE_B)
    store.create_node("Plan", _PLAN_1)
    store.create_node("Plan", _PLAN_2)
    store.create_node("Function", _FUNC_A)
    store.create_node("Function", _FUNC_B)
    store.create_node("ADR", _ADR_1)
    store.create_node("ADR", _ADR_2)
    store.create_node("Spike", _SPIKE_1)
    store.create_node("Study", _STUDY_1)
    store.create_node("ReviewFinding", _FINDING_1)
    # Edges
    store.create_edge("IMPORTS", "File", _FILE_A["id"], "File", _FILE_B["id"])
    store.create_edge(
        "PLAN_IMPACTS", "Plan", "p:1", "File", _FILE_A["id"], {"changeType": "MODIFY"}
    )
    store.create_edge("PLAN_IMPACTS", "Plan", "p:1", "File", _FILE_B["id"], {"changeType": "ADD"})
    store.create_edge(
        "CALLS",
        "Function",
        _FUNC_B["id"],
        "Function",
        _FUNC_A["id"],
    )
    store.create_edge("ADR_GOVERNS", "ADR", "adr:1", "Plan", "p:1")
    store.create_edge("SPIKE_FOR_PLAN", "Spike", "spike:1", "Plan", "p:1")
    store.create_edge("STUDY_REFERENCES_PLAN", "Study", "study:1", "Plan", "p:1")
    store.create_edge("STUDY_REFERENCES_FILE", "Study", "study:1", "File", _FILE_A["id"])
    store.create_edge("FINDING_ABOUT_FILE", "ReviewFinding", "rf:1", "File", _FILE_A["id"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kuzu_store(tmp_path: Path) -> Any:
    store = GraphStore(tmp_path / "parity_kuzu.db")
    store.init_schema()
    _populate(store)
    yield store
    store.close()


@pytest.fixture()
def duck_store() -> Any:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    _populate(store)
    yield store
    store.close()


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort rows and stringify values for stable comparison."""
    return sorted(
        [{k: str(v) if v is not None else "" for k, v in row.items()} for row in rows],
        key=lambda r: sorted(r.items()),
    )


# ---------------------------------------------------------------------------
# Pure node-scan queries
# ---------------------------------------------------------------------------


def test_get_all_plans_parity(kuzu_store: Any, duck_store: Any) -> None:
    kuzu_rows = queries.get_all_plans(kuzu_store)
    duck_rows = queries.get_all_plans(duck_store)
    assert _normalise(kuzu_rows) == _normalise(duck_rows)
    numbers = {r.get("p.number") for r in duck_rows}
    assert "1" in {str(n) for n in numbers}


def test_get_plan_by_number_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_plan_by_number(kuzu_store, 1)
    d = queries.get_plan_by_number(duck_store, 1)
    assert k is not None and d is not None
    assert str(k.get("p.number")) == str(d.get("p.number"))
    assert k.get("p.title") == d.get("p.title")


def test_get_all_adrs_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_all_adrs(kuzu_store)
    d = queries.get_all_adrs(duck_store)
    assert _normalise(k) == _normalise(d)


def test_get_all_spikes_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_all_spikes(kuzu_store)
    d = queries.get_all_spikes(duck_store)
    k_titles = {r.get("sp.title") for r in k}
    d_titles = {r.get("sp.title") for r in d}
    assert k_titles == d_titles


def test_get_all_studies_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_all_studies(kuzu_store)
    d = queries.get_all_studies(duck_store)
    k_ids = {r.get("s.studyId") for r in k}
    d_ids = {r.get("s.studyId") for r in d}
    assert k_ids == d_ids


# ---------------------------------------------------------------------------
# Single-hop GRAPH_TABLE traversal
# ---------------------------------------------------------------------------


def test_get_file_importers_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_file_importers(kuzu_store, "src/beta.py")
    d = queries.get_file_importers(duck_store, "src/beta.py")
    k_paths = {r.get("a.path") for r in k}
    d_paths = {r.get("a.path") for r in d}
    assert k_paths == d_paths
    assert "src/alpha.py" in d_paths


def test_get_file_importees_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_file_importees(kuzu_store, "src/alpha.py")
    d = queries.get_file_importees(duck_store, "src/alpha.py")
    k_paths = {r.get("b.path") for r in k}
    d_paths = {r.get("b.path") for r in d}
    assert k_paths == d_paths
    assert "src/beta.py" in d_paths


def test_get_plan_impacted_files_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_plan_impacted_files(kuzu_store, 1)
    d = queries.get_plan_impacted_files(duck_store, 1)
    k_paths = {r.get("f.path") for r in k}
    d_paths = {r.get("f.path") for r in d}
    assert k_paths == d_paths
    assert "src/alpha.py" in d_paths


def test_get_plans_impacting_file_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_plans_impacting_file(kuzu_store, "src/alpha.py")
    d = queries.get_plans_impacting_file(duck_store, "src/alpha.py")
    k_nums = {str(r.get("p.number")) for r in k}
    d_nums = {str(r.get("p.number")) for r in d}
    assert k_nums == d_nums
    assert "1" in d_nums


def test_get_adrs_for_plan_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_adrs_for_plan(kuzu_store, 1)
    d = queries.get_adrs_for_plan(duck_store, 1)
    k_nums = {str(r.get("a.number")) for r in k}
    d_nums = {str(r.get("a.number")) for r in d}
    assert k_nums == d_nums
    assert "1" in d_nums


def test_get_spikes_for_plan_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_spikes_for_plan(kuzu_store, 1)
    d = queries.get_spikes_for_plan(duck_store, 1)
    k_titles = {r.get("sp.title") for r in k}
    d_titles = {r.get("sp.title") for r in d}
    assert k_titles == d_titles


def test_get_studies_for_plan_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_studies_for_plan(kuzu_store, 1)
    d = queries.get_studies_for_plan(duck_store, 1)
    k_ids = {r.get("s.studyId") for r in k}
    d_ids = {r.get("s.studyId") for r in d}
    assert k_ids == d_ids


def test_get_studies_for_file_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_studies_for_file(kuzu_store, "src/alpha.py")
    d = queries.get_studies_for_file(duck_store, "src/alpha.py")
    k_ids = {r.get("s.studyId") for r in k}
    d_ids = {r.get("s.studyId") for r in d}
    assert k_ids == d_ids


def test_get_findings_for_file_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_findings_for_file(kuzu_store, "src/alpha.py")
    d = queries.get_findings_for_file(duck_store, "src/alpha.py")
    k_cats = {r.get("rf.category") for r in k}
    d_cats = {r.get("rf.category") for r in d}
    assert k_cats == d_cats
    assert "correctness" in d_cats


# ---------------------------------------------------------------------------
# 2-hop traversal
# ---------------------------------------------------------------------------


def test_get_adrs_for_file_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_adrs_for_file(kuzu_store, "src/alpha.py")
    d = queries.get_adrs_for_file(duck_store, "src/alpha.py")
    k_nums = {str(r.get("a.number")) for r in k}
    d_nums = {str(r.get("a.number")) for r in d}
    assert k_nums == d_nums
    assert "1" in d_nums


# ---------------------------------------------------------------------------
# Variable-length path
# ---------------------------------------------------------------------------


def test_get_transitive_consumers_parity(kuzu_store: Any, duck_store: Any) -> None:
    # beta imports alpha, so alpha is consumed by beta
    k = queries.get_transitive_consumers(kuzu_store, "src/beta.py", depth=2)
    d = queries.get_transitive_consumers(duck_store, "src/beta.py", depth=2)
    k_paths = {r.get("a.path") for r in k}
    d_paths = {r.get("a.path") for r in d}
    assert k_paths == d_paths
    assert "src/alpha.py" in d_paths


# ---------------------------------------------------------------------------
# Scalar / aggregate
# ---------------------------------------------------------------------------


def test_count_callers_for_function_parity(kuzu_store: Any, duck_store: Any) -> None:
    func_id = _FUNC_A["id"]
    k = queries.count_callers_for_function(kuzu_store, func_id)
    d = queries.count_callers_for_function(duck_store, func_id)
    assert k == d
    assert d >= 1


def test_get_hot_files_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_hot_files(kuzu_store, limit=5)
    d = queries.get_hot_files(duck_store, limit=5)
    k_paths = {r.get("f.path") for r in k}
    d_paths = {r.get("f.path") for r in d}
    assert k_paths == d_paths


# ---------------------------------------------------------------------------
# CONTAINS-based queries
# ---------------------------------------------------------------------------


def test_get_spike_by_title_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_spike_by_title(kuzu_store, "DuckPGQ")
    d = queries.get_spike_by_title(duck_store, "DuckPGQ")
    k_titles = {r.get("sp.title") for r in k}
    d_titles = {r.get("sp.title") for r in d}
    assert k_titles == d_titles
    assert len(d_titles) >= 1


def test_get_superseded_adrs_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_superseded_adrs(kuzu_store)
    d = queries.get_superseded_adrs(duck_store)
    k_nums = {str(r.get("a.number")) for r in k}
    d_nums = {str(r.get("a.number")) for r in d}
    assert k_nums == d_nums
    assert "2" in d_nums


def test_get_studies_by_outcome_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_studies_by_outcome(kuzu_store, "recommendation")
    d = queries.get_studies_by_outcome(duck_store, "recommendation")
    k_ids = {r.get("s.studyId") for r in k}
    d_ids = {r.get("s.studyId") for r in d}
    assert k_ids == d_ids
    assert "STU-001" in d_ids


def test_get_studies_by_tags_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_studies_by_tags(kuzu_store, ["duckdb"])
    d = queries.get_studies_by_tags(duck_store, ["duckdb"])
    k_ids = {r.get("s.studyId") for r in k}
    d_ids = {r.get("s.studyId") for r in d}
    assert k_ids == d_ids
    assert "STU-001" in d_ids


def test_get_adr_by_number_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_adr_by_number(kuzu_store, 1)
    d = queries.get_adr_by_number(duck_store, 1)
    assert k is not None and d is not None
    assert k.get("a.title") == d.get("a.title")
    assert k.get("a.status") == d.get("a.status")


def test_get_recurring_finding_patterns_parity(kuzu_store: Any, duck_store: Any) -> None:
    k = queries.get_recurring_finding_patterns(kuzu_store, min_occurrences=1)
    d = queries.get_recurring_finding_patterns(duck_store, min_occurrences=1)
    # Column is "category" (not dot-qualified) since it's an aggregation alias
    k_cats = {r.get("category") for r in k}
    d_cats = {r.get("category") for r in d}
    assert k_cats == d_cats
