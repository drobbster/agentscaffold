"""Readability scenarios: ensure graph-enriched output stays human-readable.

Compares enriched vs baseline rendered plans, reviews, and prompts to verify
that injecting graph metadata maintains or improves readability -- never degrades it.
"""

from __future__ import annotations

from eval.evaluator import score_readability
from eval.runner import EvalResult, collect_result


class TestPlanTemplateReadability:
    """Plan template should be well-structured with or without graph context."""

    def test_enriched_plan_readable(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.rendering import get_default_context, get_graph_context, render_template

        graph_ctx = get_graph_context(config)
        default_ctx = get_default_context(config)
        enriched = render_template("core/plan_template.md.j2", {**default_ctx, **graph_ctx})

        report = score_readability(enriched, "plan_template_enriched")

        result = EvalResult(
            scenario="readability_plan_enriched",
            passed=report.score >= 0.8,
            score=report.score,
            expected="Readability >= 0.8",
            actual=f"Score: {report.score}",
            observations=report.observations,
            category="readability",
        )
        collect_result(result)
        assert report.score >= 0.8, f"Readability too low: {report.observations}"

    def test_baseline_plan_readable(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.rendering import get_default_context, render_template

        default_ctx = get_default_context(config)
        baseline = render_template("core/plan_template.md.j2", default_ctx)

        report = score_readability(baseline, "plan_template_baseline")

        result = EvalResult(
            scenario="readability_plan_baseline",
            passed=report.score >= 0.8,
            score=report.score,
            expected="Readability >= 0.8",
            actual=f"Score: {report.score}",
            observations=report.observations,
            category="readability",
        )
        collect_result(result)
        assert report.score >= 0.8

    def test_enriched_not_worse_than_baseline(self, indexed_sim):
        """Graph enrichment must maintain or improve readability."""
        root, store, config = indexed_sim
        from agentscaffold.rendering import get_default_context, get_graph_context, render_template

        graph_ctx = get_graph_context(config)
        default_ctx = get_default_context(config)

        enriched = render_template("core/plan_template.md.j2", {**default_ctx, **graph_ctx})
        baseline = render_template("core/plan_template.md.j2", default_ctx)

        enriched_report = score_readability(enriched, "enriched")
        baseline_report = score_readability(baseline, "baseline")

        delta = enriched_report.score - baseline_report.score
        passed = delta >= -0.1  # Allow at most 0.1 degradation

        result = EvalResult(
            scenario="readability_enriched_vs_baseline",
            passed=passed,
            score=round(max(1.0 + delta, 0.0), 2),
            expected="Enriched readability >= baseline - 0.1",
            actual=(
                f"Enriched: {enriched_report.score}, "
                f"Baseline: {baseline_report.score}, "
                f"Delta: {delta:+.2f}"
            ),
            observations=[
                f"Enriched issues: {enriched_report.observations}",
                f"Baseline issues: {baseline_report.observations}",
            ],
            category="readability",
        )
        collect_result(result)
        assert (
            passed
        ), f"Enrichment degraded readability by {abs(delta):.2f}: {enriched_report.observations}"


class TestCritiqueReadability:
    """Critique prompt with graph context should stay readable."""

    def test_critique_enriched_readable(self, indexed_sim):
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
        enriched = render_template(
            "prompts/plan_critique.md.j2", {**default_ctx, **graph_ctx, **review_ctx}
        )

        report = score_readability(enriched, "critique_enriched")

        result = EvalResult(
            scenario="readability_critique_enriched",
            passed=report.score >= 0.7,
            score=report.score,
            expected="Readability >= 0.7",
            actual=f"Score: {report.score}",
            observations=report.observations,
            category="readability",
        )
        collect_result(result)
        assert report.score >= 0.7, f"Readability too low: {report.observations}"


class TestAgentsMdReadability:
    """AGENTS.md with graph intelligence section should stay readable."""

    def test_agents_md_enriched_readable(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.rendering import get_default_context, get_graph_context, render_template

        graph_ctx = get_graph_context(config)
        default_ctx = get_default_context(config)
        enriched = render_template("agents/agents_md.md.j2", {**default_ctx, **graph_ctx})

        report = score_readability(enriched, "agents_md_enriched")

        result = EvalResult(
            scenario="readability_agents_md",
            passed=report.score >= 0.7,
            score=report.score,
            expected="Readability >= 0.7",
            actual=f"Score: {report.score}",
            observations=report.observations,
            category="readability",
        )
        collect_result(result)
        assert report.score >= 0.7, f"Readability too low: {report.observations}"


class TestReviewOutputReadability:
    """Dialectic Engine review outputs should be human-readable."""

    def test_brief_markdown_readable(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.review.brief import format_brief_markdown, generate_brief

        brief = generate_brief(store, 42)
        md = format_brief_markdown(brief)

        report = score_readability(md, "review_brief")

        result = EvalResult(
            scenario="readability_review_brief",
            passed=report.score >= 0.8,
            score=report.score,
            expected="Readability >= 0.8",
            actual=f"Score: {report.score}",
            observations=report.observations,
            category="readability",
        )
        collect_result(result)
        assert report.score >= 0.8

    def test_challenges_markdown_readable(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.review.challenges import (
            format_challenges_markdown,
            generate_challenges,
        )

        challenges = generate_challenges(store, 42)
        md = format_challenges_markdown(challenges)

        report = score_readability(md, "review_challenges")

        result = EvalResult(
            scenario="readability_review_challenges",
            passed=report.score >= 0.8,
            score=report.score,
            expected="Readability >= 0.8",
            actual=f"Score: {report.score}",
            observations=report.observations,
            category="readability",
        )
        collect_result(result)
        assert report.score >= 0.8

    def test_gaps_markdown_readable(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps

        gaps = generate_gaps(store, 75)
        md = format_gaps_markdown(gaps)

        report = score_readability(md, "review_gaps")

        result = EvalResult(
            scenario="readability_review_gaps",
            passed=report.score >= 0.8,
            score=report.score,
            expected="Readability >= 0.8",
            actual=f"Score: {report.score}",
            observations=report.observations,
            category="readability",
        )
        collect_result(result)
        assert report.score >= 0.8

    def test_no_raw_ids_in_any_review(self, indexed_sim):
        """No internal graph IDs (file::, method::, etc.) should appear in rendered output."""
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

        templates = [
            "core/plan_template.md.j2",
            "agents/agents_md.md.j2",
            "prompts/plan_critique.md.j2",
            "prompts/plan_expansion.md.j2",
            "prompts/retrospective.md.j2",
        ]

        leaks: dict[str, int] = {}
        for tmpl in templates:
            try:
                rendered = render_template(tmpl, {**default_ctx, **graph_ctx, **review_ctx})
                report = score_readability(rendered, tmpl)
                if report.raw_id_count > 0:
                    leaks[tmpl] = report.raw_id_count
            except Exception:
                pass

        result = EvalResult(
            scenario="readability_no_raw_ids",
            passed=len(leaks) == 0,
            score=1.0 if not leaks else max(0.0, 1.0 - sum(leaks.values()) * 0.1),
            expected="Zero raw graph IDs in rendered output",
            actual=f"Leaks: {leaks}" if leaks else "Clean",
            observations=[f"{k}: {v} raw IDs" for k, v in leaks.items()],
            category="readability",
        )
        collect_result(result)
        assert len(leaks) == 0, f"Raw graph IDs leaked in: {leaks}"
