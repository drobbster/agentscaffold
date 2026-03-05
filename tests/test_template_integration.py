"""Tests for Phase 3: Template rendering with graph context.

Verifies that templates gracefully degrade without graph data
and render enriched content when graph data is available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.rendering import (
    get_default_context,
    get_graph_context,
    get_review_context,
    render_template,
)

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


# ---------------------------------------------------------------------------
# Fixture: indexed graph for template context
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def graph_config(tmp_path_factory):
    """Index the fixture repo and return config with graph path."""
    tmp = tmp_path_factory.mktemp("tmpl_graph")
    db_path = tmp / "graph.db"

    from agentscaffold.config import GraphConfig, ScaffoldConfig

    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))

    run_pipeline(FIXTURE_REPO, config)

    return config


# ---------------------------------------------------------------------------
# rendering.py helper tests
# ---------------------------------------------------------------------------


class TestGetGraphContext:
    """Test the get_graph_context() helper."""

    def test_returns_dict(self, graph_config):
        ctx = get_graph_context(graph_config)
        assert isinstance(ctx, dict)

    def test_contains_stats(self, graph_config):
        ctx = get_graph_context(graph_config)
        assert "graph_stats" in ctx
        assert ctx["graph_stats"]["files"] > 0

    def test_contains_plans(self, graph_config):
        ctx = get_graph_context(graph_config)
        assert "graph_plans" in ctx
        assert len(ctx["graph_plans"]) >= 2

    def test_contains_contracts(self, graph_config):
        ctx = get_graph_context(graph_config)
        assert "graph_contracts" in ctx

    def test_graceful_without_graph(self):
        from agentscaffold.config import GraphConfig, ScaffoldConfig

        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path="/nonexistent/path/graph.db")
        ctx = get_graph_context(config)
        assert ctx == {}


class TestGetReviewContext:
    """Test the get_review_context() helper."""

    def test_brief_context(self, graph_config):
        ctx = get_review_context(graph_config, plan_number=42, review_type="brief")
        assert "review_brief" in ctx
        assert "review_brief_md" in ctx

    def test_challenges_context(self, graph_config):
        ctx = get_review_context(graph_config, plan_number=42, review_type="challenges")
        assert "adversarial_challenges" in ctx
        assert "adversarial_challenges_md" in ctx

    def test_gaps_context(self, graph_config):
        ctx = get_review_context(graph_config, plan_number=42, review_type="gaps")
        assert "gap_analysis" in ctx
        assert "gap_analysis_md" in ctx

    def test_verify_context(self, graph_config):
        ctx = get_review_context(graph_config, plan_number=42, review_type="verify")
        assert "verification" in ctx
        assert "verification_md" in ctx

    def test_retro_context(self, graph_config):
        ctx = get_review_context(graph_config, plan_number=42, review_type="retro")
        assert "retro_enrichment" in ctx
        assert "retro_enrichment_md" in ctx

    def test_all_context(self, graph_config):
        ctx = get_review_context(graph_config, plan_number=42, review_type="all")
        assert "review_brief" in ctx
        assert "adversarial_challenges" in ctx
        assert "gap_analysis" in ctx
        assert "verification" in ctx
        assert "retro_enrichment" in ctx

    def test_graceful_without_graph(self):
        from agentscaffold.config import GraphConfig, ScaffoldConfig

        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path="/nonexistent/path/graph.db")
        ctx = get_review_context(config, plan_number=42)
        assert ctx == {}


# ---------------------------------------------------------------------------
# Template rendering tests (graceful degradation)
# ---------------------------------------------------------------------------


class TestTemplateGracefulDegradation:
    """Verify templates render without errors when graph context is absent."""

    def test_plan_template_without_graph(self):
        from agentscaffold.config import ScaffoldConfig

        config = ScaffoldConfig()
        ctx = get_default_context(config)
        result = render_template("core/plan_template.md.j2", ctx)
        assert "File Impact Map" in result
        assert "GRAPH CONTEXT" not in result

    def test_plan_critique_without_graph(self):
        from agentscaffold.config import ScaffoldConfig

        config = ScaffoldConfig()
        ctx = get_default_context(config)
        result = render_template("prompts/plan_critique.md.j2", ctx)
        assert "Assumption Analysis" in result
        assert "Graph-Generated" not in result

    def test_plan_expansion_without_graph(self):
        from agentscaffold.config import ScaffoldConfig

        config = ScaffoldConfig()
        ctx = get_default_context(config)
        result = render_template("prompts/plan_expansion.md.j2", ctx)
        assert "Edge Case Analysis" in result
        assert "Graph-Generated" not in result

    def test_retrospective_without_graph(self):
        from agentscaffold.config import ScaffoldConfig

        config = ScaffoldConfig()
        ctx = get_default_context(config)
        result = render_template("prompts/retrospective.md.j2", ctx)
        assert "What Worked Well" in result
        assert "Graph-Generated" not in result

    def test_agents_md_without_graph(self):
        from agentscaffold.config import ScaffoldConfig

        config = ScaffoldConfig()
        ctx = get_default_context(config)
        result = render_template("agents/agents_md.md.j2", ctx)
        assert "Planning Rules" in result
        assert "Codebase Intelligence" not in result


# ---------------------------------------------------------------------------
# Template rendering with graph context
# ---------------------------------------------------------------------------


class TestTemplateWithGraphContext:
    """Verify templates render enriched content when graph context is present."""

    def test_agents_md_with_graph(self, graph_config):
        ctx = get_default_context(graph_config)
        ctx.update(get_graph_context(graph_config))
        result = render_template("agents/agents_md.md.j2", ctx)
        assert "Codebase Intelligence" in result
        assert "scaffold index" in result

    def test_plan_template_with_hot_files(self, graph_config):
        ctx = get_default_context(graph_config)
        graph_ctx = get_graph_context(graph_config)
        # Inject a synthetic hot file for testing
        graph_ctx["graph_hot_files"] = [{"path": "src/data/router.py", "plan_count": 5}]
        ctx.update(graph_ctx)
        result = render_template("core/plan_template.md.j2", ctx)
        assert "GRAPH CONTEXT" in result
        assert "src/data/router.py" in result

    def test_critique_with_challenges(self, graph_config):
        ctx = get_default_context(graph_config)
        review_ctx = get_review_context(graph_config, plan_number=42, review_type="all")
        ctx.update(review_ctx)
        result = render_template("prompts/plan_critique.md.j2", ctx)
        assert "Assumption Analysis" in result
        # Brief and challenges sections present if data exists
        if review_ctx.get("review_brief_md"):
            assert "Review Brief" in result

    def test_expansion_with_gaps(self, graph_config):
        ctx = get_default_context(graph_config)
        review_ctx = get_review_context(graph_config, plan_number=42, review_type="all")
        ctx.update(review_ctx)
        result = render_template("prompts/plan_expansion.md.j2", ctx)
        assert "Edge Case Analysis" in result

    def test_retro_with_enrichment(self, graph_config):
        ctx = get_default_context(graph_config)
        review_ctx = get_review_context(graph_config, plan_number=42, review_type="all")
        ctx.update(review_ctx)
        result = render_template("prompts/retrospective.md.j2", ctx)
        assert "What Worked Well" in result
