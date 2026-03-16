"""Cursor IDE setup and configuration."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import find_config, load_config
from agentscaffold.rendering import get_default_context, render_template

console = Console()

_MCP_JSON_CONTENT: dict = {
    "mcpServers": {
        "agentscaffold": {
            "command": "scaffold",
            "args": ["mcp"],
        }
    }
}


def write_cursor_mcp_json(cursor_dir: Path) -> None:
    """Write ``.cursor/mcp.json`` with the agentscaffold MCP server config.

    If the file already exists, skip writing and emit a diff-suggestion to
    stdout so existing custom configs are not overwritten.
    """
    mcp_path = cursor_dir / "mcp.json"

    def _display(p: Path) -> str:
        try:
            return str(p.relative_to(Path.cwd()))
        except ValueError:
            return str(p)

    if mcp_path.exists():
        console.print(
            f"[yellow]Skipping[/yellow] {_display(mcp_path)} "
            "(already exists — verify it contains the agentscaffold server entry)"
        )
        console.print("  Suggested content:\n" + json.dumps(_MCP_JSON_CONTENT, indent=2))
        return

    cursor_dir.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(json.dumps(_MCP_JSON_CONTENT, indent=2) + "\n")
    console.print(f"[green]Wrote[/green] {_display(mcp_path)}")


def run_cursor_setup() -> None:
    """Generate Cursor rule files from scaffold.yaml config."""
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
    intent_dest.write_text(
        generate_rule_policy_document(
            config=config,
            title="AgentScaffold MCP Rule Routing",
            intro_lines=[
                "Use this file for MCP routing behavior and fallback discipline.",
                "For full process governance, also follow `.cursor/rules.md` and `AGENTS.md`.",
            ],
            quote_intents=True,
        )
    )
    console.print(f"[green]Wrote[/green] {intent_dest.relative_to(Path.cwd())}")

    write_cursor_mcp_json(cursor_dir)
