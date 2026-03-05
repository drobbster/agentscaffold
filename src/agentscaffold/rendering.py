"""Template rendering utilities.

Provides Jinja2 environment, default context, and graph-enriched context
for injecting knowledge graph data into templates and prompts.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import ChainableUndefined, Environment, PackageLoader, select_autoescape

from agentscaffold.config import ScaffoldConfig

logger = logging.getLogger(__name__)


def get_jinja_env() -> Environment:
    """Get Jinja2 environment configured for agentscaffold templates."""
    return Environment(
        loader=PackageLoader("agentscaffold", "templates"),
        autoescape=select_autoescape([]),
        undefined=ChainableUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(template_path: str, context: dict) -> str:  # type: ignore[type-arg]
    """Render a template with the given context."""
    env = get_jinja_env()
    template = env.get_template(template_path)
    return template.render(**context)


def get_default_context(config: ScaffoldConfig) -> dict:  # type: ignore[type-arg]
    """Build the default template context from a ScaffoldConfig."""
    domain_reviews: list[str] = config.gates.review_to_ready.domain_reviews
    domain_standards: list[str] = config.standards.domain
    domain_approval_gates: dict[str, list[str]] = {}

    return {
        "config": config,
        "project_name": config.framework.project_name,
        "date": date.today().isoformat(),
        "architecture_layers": config.framework.architecture_layers,
        "domains": config.domains,
        "domain_reviews": domain_reviews,
        "domain_standards": domain_standards,
        "domain_approval_gates": domain_approval_gates,
        "semi_autonomous_enabled": config.semi_autonomous.enabled,
    }


# ---------------------------------------------------------------------------
# Graph-enriched context helpers
# ---------------------------------------------------------------------------


def get_graph_context(config: ScaffoldConfig) -> dict[str, Any]:
    """Build graph-derived context for templates.

    Returns an empty dict (graceful degradation) if the graph is unavailable.
    Templates use conditional blocks: {% if graph_stats %} ... {% endif %}
    """
    try:
        from agentscaffold.graph import graph_available, open_graph
    except ImportError:
        return {}

    if not graph_available(config):
        return {}

    try:
        store = open_graph(config)
    except Exception:
        logger.debug("Graph unavailable for template context")
        return {}

    try:
        stats = store.get_stats()

        from agentscaffold.review.queries import (
            get_all_plans,
            get_hot_files,
            get_volatile_modules,
        )

        hot_files = get_hot_files(store, limit=10)
        volatile = get_volatile_modules(store)
        plans = get_all_plans(store)

        # Architecture layers
        layers = store.query(
            "MATCH (l:ArchitectureLayer) "
            "RETURN l.number, l.name, l.description "
            "ORDER BY l.number"
        )

        # Active contracts
        contracts = store.query("MATCH (c:Contract) RETURN c.name, c.version LIMIT 20")

        return {
            "graph_stats": stats,
            "graph_hot_files": [
                {"path": h.get("f.path", ""), "plan_count": h.get("plan_count", 0)}
                for h in hot_files
            ],
            "graph_volatile_modules": [
                {"path": v.get("f.path", ""), "plan_count": v.get("plan_count", 0)}
                for v in volatile
                if v.get("plan_count", 0) >= 3
            ],
            "graph_plans": [
                {
                    "number": p.get("p.number"),
                    "title": p.get("p.title", ""),
                    "status": p.get("p.status", ""),
                }
                for p in plans[:20]
            ],
            "graph_layers": [
                {
                    "number": la.get("l.number"),
                    "name": la.get("l.name", ""),
                    "description": la.get("l.description", ""),
                }
                for la in layers
            ],
            "graph_contracts": [
                {"name": c.get("c.name", ""), "version": c.get("c.version", "")} for c in contracts
            ],
        }
    except Exception:
        logger.debug("Failed to build graph context", exc_info=True)
        return {}
    finally:
        store.close()


def get_review_context(
    config: ScaffoldConfig,
    plan_number: int,
    review_type: str = "all",
) -> dict[str, Any]:
    """Build review-specific context for a plan.

    review_type: brief, challenges, gaps, verify, retro, all
    Returns empty dict if graph unavailable (graceful degradation).
    """
    try:
        from agentscaffold.graph import graph_available, open_graph
    except ImportError:
        return {}

    if not graph_available(config):
        return {}

    try:
        store = open_graph(config)
    except Exception:
        return {}

    result: dict[str, Any] = {}

    try:
        if review_type in ("brief", "all"):
            from agentscaffold.review.brief import (
                format_brief_markdown,
                generate_brief,
            )

            brief = generate_brief(store, plan_number)
            result["review_brief"] = brief
            result["review_brief_md"] = format_brief_markdown(brief)

        if review_type in ("challenges", "all"):
            from agentscaffold.review.challenges import (
                format_challenges_markdown,
                generate_challenges,
            )

            challenges = generate_challenges(store, plan_number)
            result["adversarial_challenges"] = [
                {"category": c.category, "text": c.text, "severity": c.severity} for c in challenges
            ]
            result["adversarial_challenges_md"] = format_challenges_markdown(challenges)

        if review_type in ("gaps", "all"):
            from agentscaffold.review.gaps import (
                format_gaps_markdown,
                generate_gaps,
            )

            gaps = generate_gaps(store, plan_number)
            result["gap_analysis"] = [
                {"category": g.category, "text": g.text, "severity": g.severity} for g in gaps
            ]
            result["gap_analysis_md"] = format_gaps_markdown(gaps)

        if review_type in ("verify", "all"):
            from agentscaffold.review.verify import (
                format_verification_markdown,
                verify_implementation,
            )

            items = verify_implementation(store, plan_number)
            result["verification"] = [
                {"check": i.check, "status": i.status, "detail": i.detail} for i in items
            ]
            result["verification_md"] = format_verification_markdown(items)

        if review_type in ("retro", "all"):
            from agentscaffold.review.feedback import (
                format_retro_markdown,
                generate_retro_enrichment,
            )

            insights = generate_retro_enrichment(store, plan_number)
            result["retro_enrichment"] = [
                {"category": i.category, "text": i.text} for i in insights
            ]
            result["retro_enrichment_md"] = format_retro_markdown(insights)

    except Exception:
        logger.debug("Failed to build review context", exc_info=True)
    finally:
        store.close()

    return result


def write_if_missing(path: Path, content: str) -> bool:
    """Write *content* to *path* only if the file does not already exist.

    Returns True if the file was written, False if it was skipped.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True
