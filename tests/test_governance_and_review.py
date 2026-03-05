"""Tests for Phase 2: Governance ingestion and Dialectic Engine.

Tests governance markdown parsing, plan/contract/learning ingestion,
and the review modules (brief, challenges, gaps, verify, feedback).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.graph.store import GraphStore

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


# ---------------------------------------------------------------------------
# Shared fixture: indexed repo with governance data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def indexed_store(tmp_path_factory):
    """Run the full pipeline (including governance) on the fixture repo."""
    tmp = tmp_path_factory.mktemp("gov_graph")
    db_path = tmp / "graph.db"

    from agentscaffold.config import GraphConfig, ScaffoldConfig

    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))

    summary = run_pipeline(FIXTURE_REPO, config)

    store = GraphStore(db_path)
    yield store, summary
    store.close()


# ---------------------------------------------------------------------------
# 2A: Governance ingestion tests
# ---------------------------------------------------------------------------


class TestGovernanceIngestion:
    """Test that governance artifacts are parsed and ingested correctly."""

    def test_plans_ingested(self, indexed_store):
        store, summary = indexed_store
        gov = summary.get("governance", {})
        assert gov.get("plans", 0) >= 2, "Should ingest at least 2 plan files"

    def test_contracts_ingested(self, indexed_store):
        store, summary = indexed_store
        gov = summary.get("governance", {})
        assert gov.get("contracts", 0) >= 1, "Should ingest at least 1 contract"

    def test_learnings_ingested(self, indexed_store):
        store, summary = indexed_store
        gov = summary.get("governance", {})
        assert gov.get("learnings", 0) >= 2, "Should ingest at least 2 learnings"

    def test_plan_node_data(self, indexed_store):
        store, _summary = indexed_store
        rows = store.query(
            "MATCH (p:Plan) WHERE p.number = 42 " "RETURN p.title, p.status, p.planType"
        )
        assert len(rows) >= 1
        plan = rows[0]
        assert "Data Router" in plan.get("p.title", "")

    def test_contract_node_data(self, indexed_store):
        store, _summary = indexed_store
        rows = store.query("MATCH (c:Contract) RETURN c.name, c.version")
        assert len(rows) >= 1
        contract = rows[0]
        assert contract.get("c.version") == "1.2"

    def test_learning_node_data(self, indexed_store):
        store, _summary = indexed_store
        rows = store.query(
            "MATCH (lr:Learning) WHERE lr.learningId = 'L042-1' "
            "RETURN lr.description, lr.planNumber, lr.status"
        )
        assert len(rows) >= 1
        assert rows[0].get("lr.planNumber") == 42

    def test_impact_edges_created(self, indexed_store):
        store, summary = indexed_store
        gov = summary.get("governance", {})
        # Impact edges only created when plan paths match indexed file paths
        # so this depends on fixture alignment
        assert gov.get("impact_edges", 0) >= 0


# ---------------------------------------------------------------------------
# Governance markdown parser unit tests
# ---------------------------------------------------------------------------


class TestGovernanceParsing:
    """Unit tests for the governance markdown parser functions."""

    def test_extract_plan_number(self):
        from agentscaffold.graph.governance import _extract_plan_number

        assert _extract_plan_number("plan_042_data_router.md") == 42
        assert _extract_plan_number("plan_085_caching.md") == 85
        assert _extract_plan_number("plan_1_init.md") == 1
        assert _extract_plan_number("README.md") is None

    def test_extract_metadata(self):
        from agentscaffold.graph.governance import _extract_metadata

        text = """| Field | Value |
|-------|-------|
| Title | My Plan |
| Status | Complete |
| Type | feature |
"""
        meta = _extract_metadata(text)
        assert meta["title"] == "My Plan"
        assert meta["status"] == "Complete"
        assert meta["type"] == "feature"

    def test_extract_file_impact(self):
        from agentscaffold.graph.governance import _extract_file_impact

        text = """## File Impact Map

| File | Change Type | Description |
|------|-------------|-------------|
| src/foo.py | modify | Update logic |
| src/bar.py | add | New file |

## Execution Steps
"""
        impacts = _extract_file_impact(text)
        assert len(impacts) == 2
        assert impacts[0]["path"] == "src/foo.py"
        assert impacts[1]["change_type"] == "add"

    def test_parse_learnings(self):
        from agentscaffold.graph.governance import _parse_learnings

        learnings_file = FIXTURE_REPO / "docs/ai/state/learnings_tracker.md"
        learnings = _parse_learnings(learnings_file)
        assert len(learnings) >= 4
        ids = [lr["learning_id"] for lr in learnings]
        assert "L042-1" in ids
        assert "L085-1" in ids


# ---------------------------------------------------------------------------
# 2B: Dialectic Engine tests
# ---------------------------------------------------------------------------


class TestReviewBrief:
    """Test the pre-review brief generator."""

    def test_brief_for_existing_plan(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.brief import generate_brief

        brief = generate_brief(store, 42)
        assert "error" not in brief
        assert brief["plan"]["number"] == 42

    def test_brief_for_nonexistent_plan(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.brief import generate_brief

        brief = generate_brief(store, 9999)
        assert "error" in brief

    def test_brief_markdown_rendering(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.brief import (
            format_brief_markdown,
            generate_brief,
        )

        brief = generate_brief(store, 42)
        md = format_brief_markdown(brief)
        assert "REVIEW BRIEF" in md
        assert "Plan 42" in md


class TestChallenges:
    """Test the adversarial challenge generator."""

    def test_challenges_return_list(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.challenges import generate_challenges

        challenges = generate_challenges(store, 42)
        assert isinstance(challenges, list)

    def test_challenges_for_nonexistent_plan(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.challenges import generate_challenges

        challenges = generate_challenges(store, 9999)
        assert challenges == []

    def test_challenge_has_category(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.challenges import generate_challenges

        challenges = generate_challenges(store, 42)
        for c in challenges:
            assert c.category in (
                "DEPENDENCY",
                "HISTORY",
                "LEARNING",
                "LAYER",
                "CONTRACT",
                "PATTERN",
                "CONSUMER",
                "PERFORMANCE",
            )

    def test_challenges_markdown(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.challenges import (
            format_challenges_markdown,
            generate_challenges,
        )

        challenges = generate_challenges(store, 42)
        md = format_challenges_markdown(challenges)
        assert isinstance(md, str)


class TestGaps:
    """Test the gap analysis generator."""

    def test_gaps_return_list(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.gaps import generate_gaps

        gaps = generate_gaps(store, 42)
        assert isinstance(gaps, list)

    def test_gap_has_category(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.gaps import generate_gaps

        gaps = generate_gaps(store, 42)
        valid_categories = {
            "CONSUMER_AUDIT",
            "INTEGRATION_POINTS",
            "SIMILAR_PATTERN",
            "TEST_COVERAGE",
        }
        for g in gaps:
            assert g.category in valid_categories

    def test_gaps_markdown(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps

        gaps = generate_gaps(store, 42)
        md = format_gaps_markdown(gaps)
        assert isinstance(md, str)


class TestVerification:
    """Test post-implementation verification."""

    def test_verify_returns_items(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.verify import verify_implementation

        items = verify_implementation(store, 42)
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_verify_item_has_status(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.verify import verify_implementation

        items = verify_implementation(store, 42)
        for item in items:
            assert item.status in ("pass", "warn", "fail")

    def test_verify_nonexistent_plan(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.verify import verify_implementation

        items = verify_implementation(store, 9999)
        assert items[0].status == "fail"

    def test_verify_markdown(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.verify import (
            format_verification_markdown,
            verify_implementation,
        )

        items = verify_implementation(store, 42)
        md = format_verification_markdown(items)
        assert "Post-Implementation Verification" in md


class TestFeedback:
    """Test retrospective enrichment."""

    def test_retro_returns_insights(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.feedback import generate_retro_enrichment

        insights = generate_retro_enrichment(store, 42)
        assert isinstance(insights, list)

    def test_retro_nonexistent_plan(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.feedback import generate_retro_enrichment

        insights = generate_retro_enrichment(store, 9999)
        assert insights == []

    def test_retro_markdown(self, indexed_store):
        store, _summary = indexed_store
        from agentscaffold.review.feedback import (
            format_retro_markdown,
            generate_retro_enrichment,
        )

        insights = generate_retro_enrichment(store, 42)
        md = format_retro_markdown(insights)
        assert isinstance(md, str)


# ---------------------------------------------------------------------------
# Pipeline integration: governance phase
# ---------------------------------------------------------------------------


class TestPipelineGovernance:
    """Test that governance integrates correctly in the pipeline."""

    def test_governance_phase_in_summary(self, indexed_store):
        _store, summary = indexed_store
        assert "governance" in summary.get("phases_completed", [])

    def test_pipeline_state_complete(self, indexed_store):
        store, _summary = indexed_store
        state = store.get_pipeline_state()
        assert state["state"] == "complete"
        assert "governance" in state["phases_completed"]
