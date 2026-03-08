"""Generic system prompt snippet generation from TOOL_INTENTS.

Produces a plain-text block suitable for injection into any LLM
system prompt, independent of IDE or platform.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import find_config, load_config

console = Console()


def generate_prompt_snippet() -> str:
    """Build a portable system-prompt snippet from scaffold config + intents."""
    config_path = find_config()
    if config_path is None:
        raise RuntimeError("No scaffold.yaml found")
    config = load_config(config_path)
    return generate_rule_policy_document(
        config=config,
        title="AgentScaffold Prompt Routing Snippet",
        intro_lines=[
            "Embed this snippet into system prompts for MCP-capable coding agents.",
            "This policy is MCP-first with explicit fallback protocol.",
        ],
        quote_intents=True,
    )


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
