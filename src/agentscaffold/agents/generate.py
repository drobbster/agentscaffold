"""Agent prompt and rule generation."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config, load_config
from agentscaffold.rendering import get_default_context, get_graph_context, render_template

console = Console()


def run_agents_generate() -> None:
    """Generate AGENTS.md from scaffold.yaml config.

    When a knowledge graph is available, the generated AGENTS.md includes
    a Codebase Intelligence section with hot spots, volatile modules,
    architecture layers, and active contracts.
    """
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    config = load_config(config_path)
    context = get_default_context(config)

    graph_ctx = get_graph_context(config)
    if graph_ctx:
        context.update(graph_ctx)
        console.print("[dim]Graph context injected into AGENTS.md.[/dim]")

    content = render_template("agents/agents_md.md.j2", context)

    dest = project_root / "AGENTS.md"
    dest.write_text(content)
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")


def run_agents_generate_to(project_root: Path, config_path: Path | None = None) -> None:
    """Generate AGENTS.md into a specific directory (used by init)."""
    config = load_config(config_path)
    context = get_default_context(config)
    graph_ctx = get_graph_context(config)
    if graph_ctx:
        context.update(graph_ctx)
    content = render_template("agents/agents_md.md.j2", context)
    dest = project_root / "AGENTS.md"
    dest.write_text(content)
