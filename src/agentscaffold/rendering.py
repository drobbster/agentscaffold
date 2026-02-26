"""Template rendering utilities."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import ChainableUndefined, Environment, PackageLoader, select_autoescape

from agentscaffold.config import ScaffoldConfig


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


def write_if_missing(path: Path, content: str) -> bool:
    """Write *content* to *path* only if the file does not already exist.

    Returns True if the file was written, False if it was skipped.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True
