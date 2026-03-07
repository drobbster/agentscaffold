"""Claude Code CLAUDE.md generation from TOOL_INTENTS."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import find_config, load_config

console = Console()


def generate_claude_rules() -> str:
    """Build CLAUDE.md content from MCP-first policy + intents."""
    config_path = find_config()
    if config_path is None:
        raise RuntimeError("No scaffold.yaml found")
    config = load_config(config_path)
    return generate_rule_policy_document(
        config=config,
        title="AgentScaffold Tool Routing",
        intro_lines=[
            "This project uses AgentScaffold MCP tools for planning and code intelligence.",
            "Attempt mapped MCP tools first when intent matches; fall back with a short reason.",
        ],
        quote_intents=True,
    )


def run_claude_setup() -> None:
    """Generate CLAUDE.md from scaffold.yaml config."""
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    dest = project_root / "CLAUDE.md"
    dest.write_text(generate_claude_rules())
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")
