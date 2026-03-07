"""Windsurf IDE rule generation from TOOL_INTENTS."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config

console = Console()


def generate_windsurf_rules() -> str:
    """Build .windsurfrules content from TOOL_INTENTS."""
    from agentscaffold.mcp.server import TOOL_INTENTS

    lines: list[str] = [
        "# AgentScaffold MCP Tool Routing",
        "",
        "This project uses AgentScaffold MCP tools for code intelligence.",
        "When the user request matches a pattern below, call the MCP tool.",
        "",
    ]

    for tool_name, intents in TOOL_INTENTS.items():
        lines.append(f"## {tool_name}")
        lines.append("")
        for intent in intents:
            lines.append(f"- {intent}")
        lines.append("")

    return "\n".join(lines)


def run_windsurf_setup() -> None:
    """Generate .windsurfrules from TOOL_INTENTS."""
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    dest = project_root / ".windsurfrules"
    dest.write_text(generate_windsurf_rules())
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")
