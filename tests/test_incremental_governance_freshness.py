"""Tests for incremental governance freshness gating (Plan 213, Item 2).

Governance is refreshed during incremental indexing based on a fingerprint of
the governance source documents, not the code changeset. This means:

- A doc-only edit (plan/contract/learning markdown) triggers a governance
  refresh even though it produces no code-symbol changes.
- A code-only edit (no governance doc changed) skips the ~2.7s governance
  reingest entirely.
- A true no-op is fast ("nothing to do").
- Runtime ReviewFindings survive a governance-triggered refresh.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"

PLAN_DOC = """# Plan 501: Freshness Fixture

| Status | Draft |

## Overview
A governance document used to exercise the incremental freshness gate.
"""


@pytest.fixture()
def indexed_repo(tmp_path):
    """Copy sample_repo, add a governance plan doc, and full-index it."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)

    plans_dir = repo / "docs" / "ai" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "501-freshness-fixture.md").write_text(PLAN_DOC)

    db_path = tmp_path / "graph.db"
    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))

    run_pipeline(repo, config)
    return config, repo, db_path


def _reopen(db_path):
    return DuckPGQBackend(db_path)


class TestGovernanceFreshnessGate:
    def test_doc_only_change_refreshes_governance(self, indexed_repo):
        config, repo, db_path = indexed_repo

        # Baseline: plan ingested, no findings yet.
        store = _reopen(db_path)
        assert store.node_count("ReviewFinding") == 0
        store.close()

        # Append a finding marker to the plan doc (a doc-only edit).
        plan = repo / "docs" / "ai" / "plans" / "501-freshness-fixture.md"
        plan.write_text(
            plan.read_text() + "\n## Review Findings\n[RISK] Fixture risk marker for ingestion.\n"
        )

        summary = run_pipeline(repo, config, incremental=True)
        assert "governance" in summary, "doc edit must trigger a governance refresh"

        store = _reopen(db_path)
        rows = store.query("SELECT category, planNumber FROM ReviewFinding WHERE planNumber = 501")
        assert any(r["category"] == "RISK" for r in rows)
        store.close()

    def test_backlog_change_refreshes_governance(self, indexed_repo):
        config, repo, _db_path = indexed_repo

        backlog = repo / "docs" / "ai" / "backlog.md"
        backlog.parent.mkdir(parents=True, exist_ok=True)
        backlog.write_text(
            "# Backlog\n\n| ID | Title | Priority | Effort | Status | Source |\n"
            "|----|-------|----------|--------|--------|--------|\n"
            "| B-TEST-1 | Fixture backlog item | P2 | Small | Open | Test |\n"
        )

        summary = run_pipeline(repo, config, incremental=True)

        assert "governance" in summary, "backlog.md edit must trigger governance refresh"

    def test_governance_artifact_change_refreshes_governance(self, indexed_repo):
        config, repo, _db_path = indexed_repo

        artifact = repo / "docs" / "ai" / "state" / "governance.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"governance_artifact_version": 1, "nodes": {}, "edges": {}}\n')

        summary = run_pipeline(repo, config, incremental=True)

        assert "governance" in summary, "governance.json edit must trigger governance refresh"

    def test_code_only_change_skips_governance(self, indexed_repo):
        config, repo, db_path = indexed_repo

        # Modify a Python file only; no governance doc changes.
        target = next(repo.rglob("*.py"))
        target.write_text(target.read_text() + "\n# code-only edit\n")

        summary = run_pipeline(repo, config, incremental=True)
        cs = summary["changeset"]
        assert cs["modified"], "expected the .py edit in the changeset"
        assert "governance" not in summary, "code-only edit must skip governance refresh"

    def test_no_change_is_nothing_to_do(self, indexed_repo):
        config, repo, db_path = indexed_repo

        summary = run_pipeline(repo, config, incremental=True)
        cs = summary["changeset"]
        assert cs["added"] == []
        assert cs["modified"] == []
        assert cs["deleted"] == []
        assert "governance" not in summary

    def test_runtime_finding_survives_governance_refresh(self, indexed_repo):
        config, repo, db_path = indexed_repo

        from agentscaffold.graph.findings import record_finding

        # Record a runtime finding (the kind begin_plan/complete_plan write).
        store = _reopen(db_path)
        rec = record_finding(
            store,
            plan_number=999,
            review_type="pre_review",
            category="DEPENDENCY",
            finding="Runtime finding that must survive re-indexing.",
            severity="high",
        )
        runtime_id = rec["id"]
        store.close()

        # Trigger a governance refresh via a doc-only edit.
        plan = repo / "docs" / "ai" / "plans" / "501-freshness-fixture.md"
        plan.write_text(plan.read_text() + "\n[GAP] another marker\n")
        run_pipeline(repo, config, incremental=True)

        store = _reopen(db_path)
        rows = store.query(f"SELECT status FROM ReviewFinding WHERE id = '{runtime_id}'")
        assert rows, "runtime finding must survive governance refresh"
        assert rows[0]["status"] == "open"
        store.close()
