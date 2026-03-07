"""Spike creation from templates."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from agentscaffold.config import load_config
from agentscaffold.rendering import get_default_context, get_graph_context, render_template

console = Console()


def _sanitize_name(name: str) -> str:
    """Convert a human-readable name to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "untitled"


def run_spike_create(name: str) -> None:
    """Create a new spike file from the spike template."""
    config = load_config()
    spikes_dir = Path("docs/ai/spikes")

    if not spikes_dir.is_dir():
        console.print(f"[yellow]Warning: {spikes_dir} does not exist, creating it.[/yellow]")
        spikes_dir.mkdir(parents=True, exist_ok=True)

    slug = _sanitize_name(name)
    filename = f"SPIKE-{slug}.md"
    dest = spikes_dir / filename

    if dest.exists():
        console.print(f"[red]Spike already exists: {dest}[/red]")
        raise SystemExit(1)

    ctx = get_default_context(config)
    ctx["spike_name"] = name

    graph_ctx = get_graph_context(config)
    if graph_ctx:
        ctx.update(graph_ctx)
        console.print("[dim]Graph context injected into spike template.[/dim]")

    content = render_template("core/spike_template.md.j2", ctx)
    dest.write_text(content)

    console.print(f"[green]Created spike:[/green] {dest}")
