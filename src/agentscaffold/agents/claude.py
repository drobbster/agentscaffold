"""Claude Code CLAUDE.md and subagent generation from TOOL_INTENTS."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import ReviewerConfig, ScaffoldConfig, find_config, load_config
from agentscaffold.rendering import render_template

console = Console()


def generate_claude_rules(config: ScaffoldConfig | None = None) -> str:
    """Build CLAUDE.md content from MCP-first policy + intents.

    When *config* is provided it is used directly; otherwise the nearest
    ``scaffold.yaml`` is discovered from the current working directory.
    """
    if config is None:
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


def generate_agent_markdown(reviewer: ReviewerConfig, prompt_body: str = "") -> str:
    """Render a Claude Code agent markdown file for a reviewer."""
    return render_template(
        "agents/agent.md.j2",
        {"reviewer": reviewer, "reviewer_prompt_body": prompt_body},
    )


def write_claude_agents(
    config: ScaffoldConfig,
    project_root: Path,
    dry_run: bool = False,
) -> list[Path]:
    """Generate .claude/agents/*.md for each expert reviewer.

    Returns list of paths written (or that would be written in dry-run mode).
    """
    reviewers = config.reviews.expert_reviewers
    if not reviewers:
        return []

    agents_dir = project_root / ".claude" / "agents"
    written: list[Path] = []

    for reviewer in reviewers:
        prompt_body = _load_prompt_body(reviewer, project_root)
        content = generate_agent_markdown(reviewer, prompt_body)
        dest = agents_dir / f"{reviewer.name}.md"
        written.append(dest)
        if dry_run:
            console.print(f"[dim]dry-run[/dim] would write {dest}")
        else:
            agents_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            console.print(f"[green]Wrote[/green] .claude/agents/{reviewer.name}.md")

    return written


def _load_prompt_body(reviewer: ReviewerConfig, project_root: Path) -> str:
    """Load the reviewer's prompt body from prompt_file if specified."""
    if not reviewer.prompt_file:
        return ""
    prompt_path = project_root / reviewer.prompt_file
    if prompt_path.is_file():
        return prompt_path.read_text()
    return ""


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

    config = load_config(config_path)
    write_claude_agents(config, project_root)
