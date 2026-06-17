"""Cursor IDE setup and configuration."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import ReviewerConfig, ScaffoldConfig, find_config, load_config
from agentscaffold.rendering import get_default_context, render_template, write_managed_block

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


def run_cursor_setup(force: bool = False) -> None:
    """Generate Cursor rule files from scaffold.yaml config.

    ``.cursor/rules.md`` is a project-owned document: the generated guidance is
    written into a managed block, so an existing/hand-authored file is never
    clobbered (created, block-refreshed, or appended). *force* rewrites it whole,
    keeping a ``.bak`` snapshot. The machine-owned routing/trust policy
    ``.cursor/rules/agentscaffold.md`` and the per-reviewer rules are always
    regenerated so policy updates land.
    """
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
    status = write_managed_block(dest, content, force=force)
    label = str(dest.relative_to(Path.cwd()))
    if status == "created":
        console.print(f"[green]Wrote[/green] {label}")
    elif status == "block-updated":
        console.print(f"[green]Updated[/green] AgentScaffold managed section in {label}")
    elif status == "appended":
        console.print(
            f"[green]Appended[/green] AgentScaffold managed section to {label} "
            "[dim](existing content preserved)[/dim]"
        )
    elif status == "overwritten":
        console.print(f"[yellow]Overwrote[/yellow] {label} [dim](.bak saved)[/dim]")
    else:
        console.print(f"[dim]Unchanged[/dim] {label}")

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

    write_cursor_reviewer_rules(config, cursor_dir)

    if config.enforcement.platform_enabled("cursor"):
        from agentscaffold.hooks.generators.cursor import (
            resolve_scaffold_bin,
            write_cursor_hooks,
        )

        for path in write_cursor_hooks(
            config.enforcement,
            project_root,
            scaffold_bin=resolve_scaffold_bin(),
        ):
            console.print(f"[green]Wrote[/green] {path.relative_to(project_root)}")


def generate_cursor_reviewer_rule(reviewer: ReviewerConfig, prompt_body: str = "") -> str:
    """Render a Cursor agent-requested rule file for a reviewer."""
    return render_template(
        "agents/cursor_agent.md.j2",
        {"reviewer": reviewer, "reviewer_prompt_body": prompt_body},
    )


def write_cursor_reviewer_rules(
    config: ScaffoldConfig,
    cursor_dir: Path,
    dry_run: bool = False,
) -> list[Path]:
    """Generate .cursor/rules/<reviewer>.md for each expert reviewer.

    Returns list of paths written (or that would be written in dry-run mode).
    """
    reviewers = config.reviews.expert_reviewers
    if not reviewers:
        return []

    rules_dir = cursor_dir / "rules"
    written: list[Path] = []

    for reviewer in reviewers:
        prompt_body = _load_prompt_body_for_cursor(reviewer, cursor_dir.parent)
        content = generate_cursor_reviewer_rule(reviewer, prompt_body)
        dest = rules_dir / f"{reviewer.name}.md"
        written.append(dest)
        if dry_run:
            console.print(f"[dim]dry-run[/dim] would write {dest}")
        else:
            rules_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            console.print(f"[green]Wrote[/green] .cursor/rules/{reviewer.name}.md")

    return written


def _load_prompt_body_for_cursor(reviewer: ReviewerConfig, project_root: Path) -> str:
    """Load the reviewer's prompt body from prompt_file if specified."""
    if not reviewer.prompt_file:
        return ""
    prompt_path = project_root / reviewer.prompt_file
    if prompt_path.is_file():
        return prompt_path.read_text()
    return ""
