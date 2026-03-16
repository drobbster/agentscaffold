"""Agent prompt and rule generation."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import ScaffoldConfig, find_config, load_config
from agentscaffold.rendering import get_default_context, get_graph_context, render_template

console = Console()


def run_agents_generate() -> None:
    """Generate AGENTS.md from scaffold.yaml config.

    When a knowledge graph is available, the generated AGENTS.md includes
    a Codebase Intelligence section with hot spots, volatile modules,
    architecture layers, and active contracts.
    """
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    config = load_config(config_path)
    context = get_default_context(config)

    graph_ctx = get_graph_context(config)
    if graph_ctx:
        context.update(graph_ctx)
        console.print("[dim]Graph context injected into AGENTS.md.[/dim]")

    content = render_template("agents/agents_md.md.j2", context)

    dest = project_root / "AGENTS.md"
    dest.write_text(content)
    console.print(f"[green]Wrote[/green] {dest.relative_to(Path.cwd())}")


def run_agents_generate_to(project_root: Path, config_path: Path | None = None) -> None:
    """Generate AGENTS.md into a specific directory (used by init)."""
    config = load_config(config_path)
    context = get_default_context(config)
    graph_ctx = get_graph_context(config)
    if graph_ctx:
        context.update(graph_ctx)
    content = render_template("agents/agents_md.md.j2", context)
    dest = project_root / "AGENTS.md"
    dest.write_text(content)


def run_agents_generate_all_platforms(
    config: ScaffoldConfig,
    project_root: Path,
    dry_run: bool = False,
) -> dict[str, list[Path]]:
    """Generate all platform artifacts from a single config.

    Produces:
    - AGENTS.md
    - CLAUDE.md + .claude/agents/*.md (Claude Code)
    - .cursor/rules/*.md + .cursor/mcp.json (Cursor)
    - .windsurfrules + .windsurf/agents/*.md (Windsurf)
    - Lifecycle hooks for all configured platforms

    Returns a dict mapping platform -> list of written paths.
    """
    from agentscaffold.agents.claude import (  # noqa: PLC0415
        generate_claude_rules,
        write_claude_agents,
    )
    from agentscaffold.agents.cursor import (  # noqa: PLC0415
        write_cursor_mcp_json,
        write_cursor_reviewer_rules,
    )
    from agentscaffold.agents.windsurf import write_windsurf_agent_stubs  # noqa: PLC0415
    from agentscaffold.hooks.generators.claude_code import write_claude_code_hooks  # noqa: PLC0415
    from agentscaffold.hooks.generators.cursor import (  # noqa: PLC0415
        generate_cursor_enforcement_files,
    )
    from agentscaffold.hooks.generators.windsurf import write_windsurf_hooks  # noqa: PLC0415

    written: dict[str, list[Path]] = {
        "claude_code": [],
        "cursor": [],
        "windsurf": [],
        "hooks": [],
    }

    # AGENTS.md
    context = get_default_context(config)
    agents_md_path = project_root / "AGENTS.md"
    if not dry_run:
        agents_md_path.write_text(render_template("agents/agents_md.md.j2", context))
        console.print("[green]Wrote[/green] AGENTS.md")
    else:
        console.print("[dim]dry-run[/dim] would write AGENTS.md")
    written["claude_code"].append(agents_md_path)

    # Claude Code: CLAUDE.md + subagents
    claude_md = project_root / "CLAUDE.md"
    if not dry_run:
        claude_md.write_text(generate_claude_rules())
        console.print("[green]Wrote[/green] CLAUDE.md")
    else:
        console.print("[dim]dry-run[/dim] would write CLAUDE.md")
    written["claude_code"].append(claude_md)
    written["claude_code"].extend(write_claude_agents(config, project_root, dry_run=dry_run))

    # Claude Code hooks
    if config.enforcement.platform_enabled("claude_code"):
        p = write_claude_code_hooks(config.enforcement, project_root, dry_run=dry_run)
        written["hooks"].append(p)

    # Cursor: mcp.json + per-reviewer rules + enforcement files
    cursor_dir = project_root / ".cursor"
    if not dry_run:
        cursor_dir.mkdir(parents=True, exist_ok=True)
    write_cursor_mcp_json(cursor_dir)
    written["cursor"].extend(write_cursor_reviewer_rules(config, cursor_dir, dry_run=dry_run))
    if config.enforcement.platform_enabled("cursor"):
        written["cursor"].extend(
            generate_cursor_enforcement_files(
                config.enforcement, output_dir=project_root, dry_run=dry_run
            )
        )

    # Windsurf: .windsurfrules + agent stubs
    written["windsurf"].extend(write_windsurf_agent_stubs(config, project_root, dry_run=dry_run))
    if config.enforcement.platform_enabled("windsurf"):
        p = write_windsurf_hooks(config.enforcement, project_root, dry_run=dry_run)
        written["windsurf"].append(p)

    total = sum(len(v) for v in written.values())
    console.print(f"[green]All-platforms generation complete ({total} artifacts).[/green]")
    return written
