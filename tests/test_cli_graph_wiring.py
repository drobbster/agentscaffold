"""Tests for Phase 4: CLI wiring with graph context.

Verifies that plan create, agents generate, and review --template
commands properly inject graph context into their outputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.graph.pipeline import run_pipeline

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture(scope="module")
def indexed_project(tmp_path_factory):
    """Create a temporary project with scaffold.yaml and an indexed graph."""
    proj = tmp_path_factory.mktemp("cli_proj")

    # Minimal scaffold.yaml
    (proj / "scaffold.yaml").write_text(
        "framework:\n"
        "  project_name: test-project\n"
        "  architecture_layers: 3\n"
        "graph:\n"
        f"  db_path: {proj / '.scaffold' / 'graph.db'}\n"
    )

    # Create plans directory with a sample plan
    plans_dir = proj / "docs" / "ai" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "042-data-router.md").write_text("# Data Router\n\n## 0. Metadata\n- Plan: 42\n")

    # Create some source files to index
    src = proj / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    print('hello')\n")
    (src / "utils.py").write_text("def helper():\n    return 42\n")

    # Index the project
    from agentscaffold.config import GraphConfig, ScaffoldConfig

    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(proj / ".scaffold" / "graph.db"))
    run_pipeline(proj, config)

    return proj


# ---------------------------------------------------------------------------
# plan create with graph context
# ---------------------------------------------------------------------------


class TestPlanCreateWithGraph:
    """Test that scaffold plan create injects graph context."""

    def test_plan_created_with_graph_context(self, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)

        from agentscaffold.plan.create import run_plan_create

        run_plan_create(name="test-feature", plan_type="feature")

        plans = sorted((indexed_project / "docs" / "ai" / "plans").glob("*.md"))
        newest = plans[-1]
        content = newest.read_text()

        assert "File Impact Map" in content

    def test_plan_number_increments(self, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)

        from agentscaffold.plan.create import run_plan_create

        run_plan_create(name="second-feature", plan_type="feature")

        plans = sorted((indexed_project / "docs" / "ai" / "plans").glob("*.md"))
        newest = plans[-1]
        assert "second-feature" in newest.name


# ---------------------------------------------------------------------------
# agents generate with graph context
# ---------------------------------------------------------------------------


class TestAgentsGenerateWithGraph:
    """Test that scaffold agents generate injects graph context."""

    def test_agents_md_has_codebase_intelligence(self, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)

        from agentscaffold.agents.generate import run_agents_generate

        run_agents_generate()

        agents_md = indexed_project / "AGENTS.md"
        assert agents_md.exists()
        content = agents_md.read_text()
        assert "Codebase Intelligence" in content
        assert "scaffold index" in content

    def test_agents_md_contains_stats(self, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)

        from agentscaffold.agents.generate import run_agents_generate

        run_agents_generate()

        content = (indexed_project / "AGENTS.md").read_text()
        assert "Files" in content
        assert "Functions" in content


# ---------------------------------------------------------------------------
# review --template flag
# ---------------------------------------------------------------------------


class TestReviewTemplateFlag:
    """Test that review commands with --template produce enriched prompts."""

    def test_review_context_for_template(self, indexed_project):
        """Verify get_review_context works with the indexed project."""
        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.rendering import get_review_context

        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(indexed_project / ".scaffold" / "graph.db"))

        ctx = get_review_context(config, plan_number=42, review_type="challenges")
        assert "adversarial_challenges" in ctx
        assert "adversarial_challenges_md" in ctx

    def test_critique_template_rendering(self, indexed_project):
        """Verify the critique template renders with review context."""
        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.rendering import (
            get_default_context,
            get_review_context,
            render_template,
        )

        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(indexed_project / ".scaffold" / "graph.db"))

        ctx = get_default_context(config)
        ctx.update(get_review_context(config, plan_number=42, review_type="all"))
        result = render_template("prompts/plan_critique.md.j2", ctx)
        assert "Assumption Analysis" in result

    def test_expansion_template_rendering(self, indexed_project):
        """Verify the expansion template renders with review context."""
        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.rendering import (
            get_default_context,
            get_review_context,
            render_template,
        )

        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(indexed_project / ".scaffold" / "graph.db"))

        ctx = get_default_context(config)
        ctx.update(get_review_context(config, plan_number=42, review_type="gaps"))
        result = render_template("prompts/plan_expansion.md.j2", ctx)
        assert "Edge Case Analysis" in result

    def test_retro_template_rendering(self, indexed_project):
        """Verify the retrospective template renders with review context."""
        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.rendering import (
            get_default_context,
            get_review_context,
            render_template,
        )

        config = ScaffoldConfig()
        config.graph = GraphConfig(db_path=str(indexed_project / ".scaffold" / "graph.db"))

        ctx = get_default_context(config)
        ctx.update(get_review_context(config, plan_number=42, review_type="retro"))
        result = render_template("prompts/retrospective.md.j2", ctx)
        assert "What Worked Well" in result


# ---------------------------------------------------------------------------
# Graceful degradation (no graph)
# ---------------------------------------------------------------------------


class TestCLIWithoutGraph:
    """Verify CLI commands work without a graph."""

    def test_plan_create_without_graph(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        (tmp_path / "scaffold.yaml").write_text(
            "framework:\n  project_name: no-graph\n  architecture_layers: 3\n"
        )
        plans_dir = tmp_path / "docs" / "ai" / "plans"
        plans_dir.mkdir(parents=True)

        from agentscaffold.plan.create import run_plan_create

        run_plan_create(name="basic-plan", plan_type="feature")

        plans = list(plans_dir.glob("*.md"))
        assert len(plans) == 1
        content = plans[0].read_text()
        assert "File Impact Map" in content
        assert "GRAPH CONTEXT" not in content

    def test_agents_generate_without_graph(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        (tmp_path / "scaffold.yaml").write_text(
            "framework:\n  project_name: no-graph\n  architecture_layers: 3\n"
        )

        from agentscaffold.agents.generate import run_agents_generate

        run_agents_generate()

        content = (tmp_path / "AGENTS.md").read_text()
        assert "Planning Rules" in content
        assert "Codebase Intelligence" not in content
