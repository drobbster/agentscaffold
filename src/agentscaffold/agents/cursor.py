"""Cursor IDE setup and configuration.

Generates .cursor/rules/ intent-mapping rules from the TOOL_INTENTS
single source of truth in the MCP server module.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config, load_config
from agentscaffold.rendering import get_default_context, render_template

console = Console()


def _generate_intent_rules() -> str:
    """Build markdown rule content from TOOL_INTENTS."""
    from agentscaffold.mcp.server import TOOL_INTENTS

    lines: list[str] = [
        "# AgentScaffold Tool Intent Mapping",
        "",
        "When the user says something matching one of these patterns,",
        "call the corresponding MCP tool automatically.",
        "",
    ]

    for tool_name, intents in TOOL_INTENTS.items():
        lines.append(f"## {tool_name}")
        lines.append("")
        lines.append("Trigger phrases:")
        for intent in intents:
            lines.append(f'- "{intent}"')
        lines.append("")

    return "\n".join(lines)


def run_cursor_setup() -> None:
    """Generate .cursor/rules.md and intent mapping from scaffold.yaml config."""
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    config = load_config(config_path)
    context = get_default_context(config)

    content = render_template("agents/cursor_rules.md.j2", context)

    cursor_dir = project_root / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)

    dest = cursor_dir / "rules.md"
    dest.write_text(content)
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")

    rules_dir = cursor_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    intent_dest = rules_dir / "agentscaffold.md"
    intent_dest.write_text(_generate_intent_rules())
    console.print(f"[green]Wrote[/green] {intent_dest.relative_to(Path.cwd())}")
