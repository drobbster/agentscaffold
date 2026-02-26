"""Plan creation from templates."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from agentscaffold.config import load_config
from agentscaffold.rendering import get_default_context, render_template

console = Console()

PLAN_TYPE_TEMPLATES = {
    "feature": "core/plan_template.md.j2",
    "bugfix": "core/plan_template_bugfix.md.j2",
    "refactor": "core/plan_template_refactor.md.j2",
}

PLAN_NUMBER_RE = re.compile(r"^(\d{3})-")


def _next_plan_number(plans_dir: Path) -> int:
    """Scan existing plan files to determine the next available number."""
    max_num = 0
    if plans_dir.is_dir():
        for entry in plans_dir.iterdir():
            m = PLAN_NUMBER_RE.match(entry.name)
            if m:
                max_num = max(max_num, int(m.group(1)))
    return max_num + 1


def _sanitize_name(name: str) -> str:
    """Convert a human-readable name to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "untitled"


def run_plan_create(name: str, plan_type: str) -> None:
    """Create a new plan file from the appropriate template."""
    if plan_type not in PLAN_TYPE_TEMPLATES:
        console.print(
            f"[red]Unknown plan type '{plan_type}'. "
            f"Choose from: {', '.join(PLAN_TYPE_TEMPLATES)}[/red]"
        )
        raise SystemExit(1)

    config = load_config()
    plans_dir = Path("docs/ai/plans")

    if not plans_dir.is_dir():
        console.print(f"[yellow]Warning: {plans_dir} does not exist, creating it.[/yellow]")
        plans_dir.mkdir(parents=True, exist_ok=True)

    plan_number = _next_plan_number(plans_dir)
    slug = _sanitize_name(name)
    filename = f"{plan_number:03d}-{slug}.md"
    dest = plans_dir / filename

    ctx = get_default_context(config)
    ctx.update(
        plan_number=plan_number,
        plan_name=name,
        plan_title=name,
    )

    content = render_template(PLAN_TYPE_TEMPLATES[plan_type], ctx)
    dest.write_text(content)

    console.print(f"[green]Created plan:[/green] {dest}")
