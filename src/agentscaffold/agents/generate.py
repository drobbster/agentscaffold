"""Agent prompt and rule generation."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import ScaffoldConfig, find_config, load_config
from agentscaffold.rendering import (
    get_default_context,
    get_graph_context,
    render_template,
    write_managed_block,
)

console = Console()

# Project-owned documents (AGENTS.md, CLAUDE.md, .windsurfrules, .cursor/rules.md)
# may already be curated by an organization or user, so AgentScaffold NEVER
# overwrites them wholesale. The generated guidance is written into a delimited
# "managed block" instead: when the file is absent the block is created, when the
# file already contains the markers only that region is refreshed, and when the
# file exists WITHOUT markers (fully user-owned) a fresh block is appended without
# touching existing content. Machine-owned files (.cursor/rules/agentscaffold.md,
# per-reviewer rules, enforcement hooks, agent stubs) are still regenerated via
# write_text so policy/config updates always land; mcp.json stays skip-if-exists.


def _report_managed_write(status: str, label: str) -> None:
    """Emit a consistent console message for a managed-block write result."""
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
    else:  # unchanged
        console.print(f"[dim]Unchanged[/dim] {label}")


def run_agents_generate(force: bool = False) -> None:
    """Generate AGENTS.md from scaffold.yaml config.

    When a knowledge graph is available, the generated AGENTS.md includes
    a Codebase Intelligence section with hot spots, volatile modules,
    architecture layers, and active contracts.

    AGENTS.md is a project-owned document: the generated guidance is written into
    a managed block so existing/hand-authored content is never destroyed. *force*
    rewrites the whole file (a ``.bak`` snapshot is kept).
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
    status = write_managed_block(dest, content, force=force)
    _report_managed_write(status, str(dest.relative_to(Path.cwd())))


def run_agents_generate_to(
    project_root: Path, config_path: Path | None = None, force: bool = False
) -> None:
    """Generate AGENTS.md into a specific directory (used by init).

    AGENTS.md is project-owned: generated guidance lands in a managed block, so an
    existing/hand-authored AGENTS.md is never clobbered unless *force* is set.
    """
    config = load_config(config_path)
    context = get_default_context(config)
    graph_ctx = get_graph_context(config)
    if graph_ctx:
        context.update(graph_ctx)
    content = render_template("agents/agents_md.md.j2", context)
    dest = project_root / "AGENTS.md"
    write_managed_block(dest, content, force=force)


def run_agents_generate_all_platforms(
    config: ScaffoldConfig,
    project_root: Path,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, list[Path]]:
    """Generate all platform artifacts from a single config.

    Produces:
    - AGENTS.md
    - CLAUDE.md + .claude/agents/*.md (Claude Code)
    - .cursor/rules/*.md + .cursor/mcp.json (Cursor)
    - .windsurfrules + .windsurf/agents/*.md (Windsurf)
    - Lifecycle hooks for all configured platforms

    Project-owned documents (AGENTS.md, CLAUDE.md, .windsurfrules) are never
    overwritten: the generated guidance is written into a managed block (created,
    block-refreshed, or appended) so org/user content is always preserved. *force*
    rewrites those files wholesale, keeping a ``.bak`` snapshot. Machine-owned files
    (.cursor/rules/agentscaffold.md, per-reviewer rules, enforcement hooks, agent
    stubs) are always regenerated so policy/config updates land; mcp.json remains
    skip-if-exists.

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
    from agentscaffold.agents.rule_policy import (  # noqa: PLC0415
        generate_rule_policy_document,
    )
    from agentscaffold.agents.windsurf import (  # noqa: PLC0415
        generate_windsurf_rules,
        write_windsurf_agent_stubs,
    )
    from agentscaffold.hooks.generators.claude_code import write_claude_code_hooks  # noqa: PLC0415
    from agentscaffold.hooks.generators.cursor import (  # noqa: PLC0415
        generate_cursor_enforcement_files,
        write_cursor_hooks,
        write_embedding_commit_hooks,
    )
    from agentscaffold.hooks.generators.cursor import (
        resolve_scaffold_bin as _resolve_scaffold_bin,
    )
    from agentscaffold.hooks.generators.windsurf import write_windsurf_hooks  # noqa: PLC0415

    written: dict[str, list[Path]] = {
        "claude_code": [],
        "cursor": [],
        "windsurf": [],
        "hooks": [],
    }

    # AGENTS.md (project-owned -- managed block, never clobbered unless force)
    context = get_default_context(config)
    agents_md_path = project_root / "AGENTS.md"
    if not dry_run:
        status = write_managed_block(
            agents_md_path, render_template("agents/agents_md.md.j2", context), force=force
        )
        _report_managed_write(status, "AGENTS.md")
    else:
        console.print(
            "[dim]dry-run[/dim] would update AGENTS.md managed block (existing content preserved)"
        )
    written["claude_code"].append(agents_md_path)

    # Claude Code: CLAUDE.md (project-owned -- managed block) + subagents
    claude_md = project_root / "CLAUDE.md"
    if not dry_run:
        status = write_managed_block(claude_md, generate_claude_rules(config), force=force)
        _report_managed_write(status, "CLAUDE.md")
    else:
        console.print(
            "[dim]dry-run[/dim] would update CLAUDE.md managed block (existing content preserved)"
        )
    written["claude_code"].append(claude_md)
    written["claude_code"].extend(write_claude_agents(config, project_root, dry_run=dry_run))

    # Claude Code hooks
    if config.enforcement.platform_enabled("claude_code"):
        p = write_claude_code_hooks(
            config.enforcement,
            project_root,
            scaffold_bin=_resolve_scaffold_bin(),
            min_interval_seconds=config.graph.incremental_min_interval_seconds,
            dry_run=dry_run,
        )
        written["hooks"].append(p)

    # Cursor: mcp.json + per-reviewer rules + enforcement files
    cursor_dir = project_root / ".cursor"
    if not dry_run:
        cursor_dir.mkdir(parents=True, exist_ok=True)
    write_cursor_mcp_json(cursor_dir)
    # MCP routing + graph trust discipline doc (kept in parity with `agents cursor`).
    # Cursor only loads rules with the `.mdc` extension; a plain `.md` in
    # `.cursor/rules/` is ignored. Emit `.mdc` with `alwaysApply: true` so the
    # MCP routing + multi-project discipline is always in agent context. Remove a
    # stale `.md` from older generations so the two do not diverge.
    intent_dest = cursor_dir / "rules" / "agentscaffold.mdc"
    legacy_md = cursor_dir / "rules" / "agentscaffold.md"
    if not dry_run:
        intent_dest.parent.mkdir(parents=True, exist_ok=True)
        intent_dest.write_text(
            generate_rule_policy_document(
                config=config,
                title="AgentScaffold MCP Rule Routing",
                intro_lines=[
                    "Use this file for MCP routing behavior and fallback discipline.",
                    "For full process governance, also follow `.cursor/rules.md` and `AGENTS.md`.",
                ],
                quote_intents=True,
                always_apply=True,
            )
        )
        if legacy_md.exists():
            legacy_md.unlink()
        console.print("[green]Wrote[/green] .cursor/rules/agentscaffold.mdc")
    else:
        console.print("[dim]dry-run[/dim] would write .cursor/rules/agentscaffold.mdc")
    written["cursor"].append(intent_dest)
    written["cursor"].extend(write_cursor_reviewer_rules(config, cursor_dir, dry_run=dry_run))
    if config.enforcement.platform_enabled("cursor"):
        written["cursor"].extend(
            generate_cursor_enforcement_files(
                config.enforcement, output_dir=project_root, dry_run=dry_run
            )
        )
        written["cursor"].extend(
            write_cursor_hooks(
                config.enforcement,
                project_root,
                scaffold_bin=_resolve_scaffold_bin(),
                min_interval_seconds=config.graph.incremental_min_interval_seconds,
                dry_run=dry_run,
            )
        )
    if getattr(config.graph, "async_embeddings", "off") == "commit":
        written["hooks"].extend(
            write_embedding_commit_hooks(
                project_root,
                scaffold_bin=_resolve_scaffold_bin(),
                min_interval_seconds=config.graph.embedding_min_interval_seconds,
                dry_run=dry_run,
            )
        )

    # Windsurf: .windsurfrules (project-owned -- managed block) + agent stubs
    windsurf_rules = project_root / ".windsurfrules"
    if not dry_run:
        status = write_managed_block(windsurf_rules, generate_windsurf_rules(config), force=force)
        _report_managed_write(status, ".windsurfrules")
    else:
        console.print(
            "[dim]dry-run[/dim] would update .windsurfrules managed block (content preserved)"
        )
    written["windsurf"].append(windsurf_rules)
    written["windsurf"].extend(write_windsurf_agent_stubs(config, project_root, dry_run=dry_run))
    if config.enforcement.platform_enabled("windsurf"):
        p = write_windsurf_hooks(config.enforcement, project_root, dry_run=dry_run)
        written["windsurf"].append(p)

    total = sum(len(v) for v in written.values())
    console.print(f"[green]All-platforms generation complete ({total} artifacts).[/green]")
    return written
