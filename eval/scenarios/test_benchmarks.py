"""Benchmark scenarios: A/B comparisons with/without graph enrichment."""

from __future__ import annotations

from eval.evaluator import score_graph_enrichment
from eval.runner import BenchmarkResult, EvalResult, collect_benchmark, collect_result, timed


class TestPlanTemplateEnrichment:
    """Benchmark: Plan template rendering with vs without graph."""

    @timed
    def test_plan_template_enriched_vs_baseline(self, indexed_sim):
        """Graph-enriched plan template should contain extra context."""
        root, store, config = indexed_sim
        from agentscaffold.rendering import get_default_context, get_graph_context, render_template

        graph_ctx = get_graph_context(config)
        default_ctx = get_default_context(config)

        enriched_ctx = {**default_ctx, **graph_ctx}
        baseline_ctx = {**default_ctx}

        enriched = render_template("core/plan_template.md.j2", enriched_ctx)
        baseline = render_template("core/plan_template.md.j2", baseline_ctx)

        enrichment_result = score_graph_enrichment(
            enriched,
            baseline,
            markers=["hot spot", "volatile", "Graph-Generated"],
        )

        benchmark = BenchmarkResult(
            scenario_name="plan_template_enrichment",
            with_graph_count=len(enriched),
            without_graph_count=len(baseline),
            delta=len(enriched) - len(baseline),
            observations=[
                f"Enriched length: {len(enriched)}",
                f"Baseline length: {len(baseline)}",
                f"Delta: {len(enriched) - len(baseline)} chars",
            ],
        )
        collect_benchmark(benchmark)
        collect_result(enrichment_result)

        assert len(enriched) >= len(baseline), "Enriched template should be at least as long"


class TestAgentsMdGenerationPath:
    """Plan 260: generate writes routing, not a graph dump into the manual."""

    @timed
    def test_agents_md_generate_path_is_routing(self, indexed_sim):
        """Init scaffolds the manual; generate owns routing only.

        The leftover ``{% if graph_stats %}`` block in ``agents_md.md.j2`` is a
        dead writer: ``scaffold agents generate`` no longer renders that
        template. Measuring it as "enrichment" would advertise a token cost
        the product no longer pays on the generate path.
        """
        root, store, config = indexed_sim
        from agentscaffold.agents.generate import render_agents_routing
        from agentscaffold.rendering import get_default_context, render_template

        default_ctx = get_default_context(config)
        manual = render_template("agents/agents_md.md.j2", default_ctx)
        routing = render_agents_routing(config)

        routing_ok = (
            "## Session Working Rhythm" in routing
            and "scaffold_session_record_decision" in routing
            and "## Plan Lifecycle" not in routing
            and "Codebase Intelligence" not in routing
        )
        manual_ok = "## Plan Lifecycle" in manual and "Codebase Intelligence" not in manual

        result = EvalResult(
            scenario="agents_md_generation_path",
            passed=routing_ok and manual_ok,
            score=1.0 if routing_ok and manual_ok else 0.0,
            expected="Generate writes routing only; init manual has no graph dump",
            actual=f"routing_ok={routing_ok}, manual_ok={manual_ok}",
            category="benchmark",
        )
        collect_result(result)
        assert routing_ok, f"Routing block is not the generate contract: {routing[:400]}"
        assert manual_ok, "Init manual should keep Plan Lifecycle and omit Codebase Intelligence"


class TestCritiqueTemplateEnrichment:
    """Benchmark: Plan critique prompt with vs without graph."""

    @timed
    def test_critique_enriched(self, indexed_sim):
        """Critique prompt should be enriched with review brief and challenges."""
        root, store, config = indexed_sim
        from agentscaffold.rendering import (
            get_default_context,
            get_graph_context,
            get_review_context,
            render_template,
        )

        graph_ctx = get_graph_context(config)
        review_ctx = get_review_context(plan_number=42, config=config)
        default_ctx = get_default_context(config)

        enriched_ctx = {**default_ctx, **graph_ctx, **review_ctx}
        baseline_ctx = {**default_ctx}

        enriched = render_template("prompts/plan_critique.md.j2", enriched_ctx)
        baseline = render_template("prompts/plan_critique.md.j2", baseline_ctx)

        enrichment_result = score_graph_enrichment(
            enriched,
            baseline,
            markers=["blast radius", "importer", "challenge"],
        )

        benchmark = BenchmarkResult(
            scenario_name="critique_enrichment",
            with_graph_count=len(enriched),
            without_graph_count=len(baseline),
            delta=len(enriched) - len(baseline),
        )
        collect_benchmark(benchmark)
        collect_result(enrichment_result)


class TestSearchModes:
    """Benchmark: Compare keyword vs hybrid search results."""

    @timed
    def test_keyword_vs_hybrid_coverage(self, indexed_sim):
        """Hybrid search should return at least as many results as keyword alone."""
        root, store, config = indexed_sim
        from agentscaffold.graph.search import hybrid_search

        keyword_results = hybrid_search(store, "DataRouter", mode="keyword", top_k=10)
        hybrid_results = hybrid_search(store, "DataRouter", mode="hybrid", top_k=10)

        benchmark = BenchmarkResult(
            scenario_name="search_mode_coverage",
            with_graph_count=len(hybrid_results),
            without_graph_count=len(keyword_results),
            delta=len(hybrid_results) - len(keyword_results),
            observations=[
                f"Keyword: {len(keyword_results)} results",
                f"Hybrid: {len(hybrid_results)} results",
            ],
        )
        collect_benchmark(benchmark)

        result = EvalResult(
            scenario="search_coverage",
            passed=len(hybrid_results) >= len(keyword_results),
            score=1.0 if len(hybrid_results) >= len(keyword_results) else 0.5,
            expected="Hybrid >= keyword results",
            actual=f"Hybrid: {len(hybrid_results)}, Keyword: {len(keyword_results)}",
            category="benchmark",
        )
        collect_result(result)


class TestTemplateWellformedness:
    """Benchmark: All rendered templates should be well-formed."""

    @timed
    def test_all_templates_clean(self, indexed_sim):
        """All templates rendered with graph context should have no Jinja2 residue."""
        root, store, config = indexed_sim
        from agentscaffold.rendering import (
            get_default_context,
            get_graph_context,
            get_review_context,
            render_template,
        )
        from eval.runner import check_template_wellformedness

        graph_ctx = get_graph_context(config)
        review_ctx = get_review_context(plan_number=42, config=config)
        default_ctx = get_default_context(config)
        full_ctx = {**default_ctx, **graph_ctx, **review_ctx}

        templates = [
            "core/plan_template.md.j2",
            "agents/agents_md.md.j2",
            "prompts/plan_critique.md.j2",
            "prompts/plan_expansion.md.j2",
            "prompts/retrospective.md.j2",
        ]

        all_issues = {}
        for tmpl in templates:
            try:
                rendered = render_template(tmpl, full_ctx)
                issues = check_template_wellformedness(rendered)
                if issues:
                    all_issues[tmpl] = issues
            except Exception as exc:
                all_issues[tmpl] = [f"Render error: {exc}"]

        result = EvalResult(
            scenario="template_wellformedness",
            passed=len(all_issues) == 0,
            score=1.0 - len(all_issues) / len(templates),
            expected="All templates clean",
            actual=f"{len(all_issues)} templates with issues: {list(all_issues.keys())}",
            observations=[f"{k}: {v}" for k, v in all_issues.items()],
            category="benchmark",
        )
        collect_result(result)
        assert len(all_issues) == 0, f"Template issues: {all_issues}"
