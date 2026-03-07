"""Claude Code CLAUDE.md generation from TOOL_INTENTS."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config

console = Console()


def generate_claude_rules() -> str:
    """Build CLAUDE.md content from TOOL_INTENTS."""
    from agentscaffold.mcp.server import TOOL_INTENTS

    lines: list[str] = [
        "# AgentScaffold Tool Routing",
        "",
        "This project uses AgentScaffold MCP tools. When the user makes",
        "a request matching the patterns below, call the corresponding tool.",
        "",
    ]

    for tool_name, intents in TOOL_INTENTS.items():
        examples = ", ".join(f'"{i}"' for i in intents[:3])
        lines.append(f"- **{tool_name}**: {examples}")

    lines.append("")
    return "\n".join(lines)


def run_claude_setup() -> None:
    """Generate CLAUDE.md from TOOL_INTENTS."""
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    dest = project_root / "CLAUDE.md"
    dest.write_text(generate_claude_rules())
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")
