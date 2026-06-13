"""Tests for index-time ReviewFinding ingestion from plan text (Plan 212).

`process_governance` parses `[CATEGORY] ...` review markers embedded in plan
files and materializes them as ReviewFinding nodes. This closes the previously
dead `_parse_review_findings` path. Ingestion must be idempotent and must not
clobber findings that were later resolved via the runtime path.
"""

from __future__ import annotations

from pathlib import Path

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.governance import process_governance

PLAN_WITH_MARKERS = """# Plan 307: Smoke Findings

| Status | Complete |

## Review Findings (devil's advocate)

[RISK] Unbounded retry loop could hammer the broker API under outage.
[GAP] No regression test covers the OOM decode path.
[DEPENDENCY] Relies on Plan 211 scheduler bounds being deployed first.

## Graph-Generated Gap Analysis

[CONSUMER_AUDIT]!! 85 files import changed modules but are NOT in the File Impact Map.
[DEPENDENCY_COMPLETENESS]! 51 upstream dependencies are not in the File Impact Map.
[TEST_COVERAGE]!! No test files reference 26 impacted files.
[SIMILAR_PATTERN]! Overlapping file scope with Plan 170, Plan 171.
[INTEGRATION_POINTS] Crosses 3 layer boundaries.
"""


def _make_plan(root: Path, name: str, body: str) -> None:
    plans = root / "docs" / "ai" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / name).write_text(body)


class TestPlanAppendixFindingIngestion:
    def test_markers_become_review_findings(self, tmp_path):
        _make_plan(tmp_path, "307-smoke.md", PLAN_WITH_MARKERS)

        store = DuckPGQBackend(":memory:")
        store.init_schema()
        try:
            result = process_governance(store, tmp_path)

            assert result["findings"] >= 8
            rows = store.query(
                "SELECT category, finding, severity, reviewType, planNumber FROM ReviewFinding"
            )
            categories = {r["category"] for r in rows}
            # Manual categories plus widened gaps-engine categories.
            assert {
                "RISK",
                "GAP",
                "DEPENDENCY",
                "CONSUMER_AUDIT",
                "DEPENDENCY_COMPLETENESS",
                "TEST_COVERAGE",
                "SIMILAR_PATTERN",
                "INTEGRATION_POINTS",
            } <= categories
            assert all(r["reviewType"] == "plan_appendix" for r in rows)
            assert all(int(r["planNumber"]) == 307 for r in rows)

            # Severity markers ("!!"/"!") map to high/medium; none defaults medium.
            by_cat = {r["category"]: r for r in rows}
            assert by_cat["CONSUMER_AUDIT"]["severity"] == "high"
            assert by_cat["TEST_COVERAGE"]["severity"] == "high"
            assert by_cat["DEPENDENCY_COMPLETENESS"]["severity"] == "medium"
            assert by_cat["INTEGRATION_POINTS"]["severity"] == "medium"
            # Severity markers must not leak into the finding text.
            assert not by_cat["CONSUMER_AUDIT"]["finding"].startswith("!")
        finally:
            store.close()

    def test_ingestion_is_idempotent(self, tmp_path):
        _make_plan(tmp_path, "307-smoke.md", PLAN_WITH_MARKERS)

        store = DuckPGQBackend(":memory:")
        store.init_schema()
        try:
            process_governance(store, tmp_path)
            count_after_first = store.node_count("ReviewFinding")
            assert count_after_first >= 3

            process_governance(store, tmp_path)
            process_governance(store, tmp_path)
            assert store.node_count("ReviewFinding") == count_after_first
        finally:
            store.close()

    def test_resolved_status_preserved_across_reingest(self, tmp_path):
        _make_plan(tmp_path, "307-smoke.md", PLAN_WITH_MARKERS)

        store = DuckPGQBackend(":memory:")
        store.init_schema()
        try:
            process_governance(store, tmp_path)
            rows = store.query("SELECT id FROM ReviewFinding LIMIT 1")
            assert rows
            fid = rows[0]["id"]

            from agentscaffold.graph.findings import resolve_finding

            resolve_finding(store, fid, resolution="fixed in commit abc123")

            # Re-index: governance re-ingests, but ON CONFLICT DO NOTHING must
            # keep the resolved status/resolution intact.
            process_governance(store, tmp_path)
            status_rows = store.query(
                f"SELECT status, resolution FROM ReviewFinding WHERE id = '{fid}'"
            )
            assert status_rows[0]["status"] == "resolved"
            assert "abc123" in status_rows[0]["resolution"]
        finally:
            store.close()

    def test_no_markers_yields_no_findings(self, tmp_path):
        _make_plan(
            tmp_path,
            "308-clean.md",
            "# Plan 308: Clean\n\n| Status | Draft |\n\nNo review markers here.\n",
        )

        store = DuckPGQBackend(":memory:")
        store.init_schema()
        try:
            result = process_governance(store, tmp_path)
            assert result["findings"] == 0
            assert store.node_count("ReviewFinding") == 0
        finally:
            store.close()
