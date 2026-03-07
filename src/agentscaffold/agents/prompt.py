"""Generic system prompt snippet generation from TOOL_INTENTS.

Produces a plain-text block suitable for injection into any LLM
system prompt, independent of IDE or platform.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config

console = Console()


def generate_prompt_snippet() -> str:
    """Build a system-prompt snippet from TOOL_INTENTS."""
    from agentscaffold.mcp.server import TOOL_INTENTS

    lines: list[str] = [
        "You have access to AgentScaffold MCP tools for code intelligence.",
        "When the user's request matches one of the patterns below,",
        "call the specified tool automatically.",
        "",
    ]

    for tool_name, intents in TOOL_INTENTS.items():
        examples = " | ".join(f'"{i}"' for i in intents[:3])
        lines.append(f"  {tool_name}: {examples}")

    lines.append("")
    return "\n".join(lines)


def run_prompt_export() -> None:
    """Export system-prompt snippet to a file."""
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    dest = project_root / ".scaffold" / "prompt_snippet.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(generate_prompt_snippet())
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")
