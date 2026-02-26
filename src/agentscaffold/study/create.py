"""Study creation from templates."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from rich.console import Console

from agentscaffold.config import load_config
from agentscaffold.rendering import get_default_context, render_template

console = Console()


def _sanitize_name(name: str) -> str:
    """Convert a human-readable name to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "untitled"


def run_study_create(name: str) -> None:
    """Create a new study file from the study template."""
    config = load_config()
    studies_dir = Path("docs/studies")

    if not studies_dir.is_dir():
        console.print(f"[yellow]Warning: {studies_dir} does not exist, creating it.[/yellow]")
        studies_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    slug = _sanitize_name(name)
    filename = f"STU-{today}-{slug}.md"
    dest = studies_dir / filename

    if dest.exists():
        console.print(f"[red]Study already exists: {dest}[/red]")
        raise SystemExit(1)

    ctx = get_default_context(config)
    ctx["study_name"] = name

    content = render_template("core/study_template.md.j2", ctx)
    dest.write_text(content)

    console.print(f"[green]Created study:[/green] {dest}")
