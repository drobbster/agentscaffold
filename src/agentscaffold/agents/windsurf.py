"""Windsurf IDE rule generation from TOOL_INTENTS."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import find_config, load_config

console = Console()


def generate_windsurf_rules() -> str:
    """Build .windsurfrules content from MCP-first policy + intents."""
    config_path = find_config()
    if config_path is None:
        raise RuntimeError("No scaffold.yaml found")
    config = load_config(config_path)
    return generate_rule_policy_document(
        config=config,
        title="AgentScaffold MCP Rule Routing",
        intro_lines=[
            "This project uses AgentScaffold MCP tools for code intelligence.",
            "Apply MCP-first routing, then fallback to direct reads/search when needed.",
        ],
        quote_intents=False,
    )


def run_windsurf_setup() -> None:
    """Generate .windsurfrules from scaffold.yaml config."""
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    dest = project_root / ".windsurfrules"
    dest.write_text(generate_windsurf_rules())
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")
