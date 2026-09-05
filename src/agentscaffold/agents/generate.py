"""Agent prompt and rule generation."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from agentscaffold.agents.manual_diff import parse_h2_sections
from agentscaffold.config import ScaffoldConfig, WorkspaceConfig, find_config, load_config
from agentscaffold.rendering import (
    MANAGED_BLOCK_BEGIN,
    MANAGED_BLOCK_END,
    canonical_guidance_document,
    canonical_guidance_path,
    get_default_context,
    get_graph_context,
    guidance_hash,
    render_template,
    stamp_guidance,
    write_canonical_guidance,
    write_gitignore_block,
    write_managed_block,
)

console = Console()

# Project-owned documents (AGENTS.md, CLAUDE.md, .windsurfrules, .cursor/rules.md)
# may already be curated by an organization or user, so AgentScaffold NEVER
# overwrites them wholesale. The generated guidance is written into a delimited
# "managed block" instead: when the file is absent the block is created, when the
# file already contains the markers only that region is refreshed, and when the
# file exists WITHOUT markers (fully user-owned) a fresh block is appended without
# touching existing content. Machine-owned files (.cursor/rules/agentscaffold.mdc,
# per-reviewer rules, enforcement hooks, agent stubs) are still regenerated via
# write_text so policy/config updates always land; mcp.json stays skip-if-exists.


def _shared_workspace_context(
    project_root: Path,
) -> tuple[bool, WorkspaceConfig | None, Path | None]:
    """Return (is_shared, workspace, workspace_root) for a project (Plan 234).

    Detects whether the project belongs to a workspace whose ``asset_layout``
    opts into ``shared_workspace``. Returns ``(False, None, None)`` for a lone or
    ``project_local`` repo so generation stays byte-for-byte the same.
    """
    try:
        from agentscaffold.paths import load_workspace, resolve_workspace_root

        workspace = load_workspace(project_root)
        if workspace.is_shared_workspace:
            return True, workspace, resolve_workspace_root(project_root)
    except Exception:
        pass
    return False, None, None


def render_agents_routing(config: ScaffoldConfig) -> str:
    """Routing-only managed-block body for a lone-project AGENTS.md."""
    from agentscaffold.agents.rule_policy import generate_rule_policy_document

    return generate_rule_policy_document(
        config=config,
        title="AgentScaffold Tool Routing",
        intro_lines=[
            "Use this file for MCP routing behavior and fallback discipline.",
            "The governance manual above the managed markers is project-owned.",
        ],
        quote_intents=True,
    )


def _render_project_agents_md(config: ScaffoldConfig, project_root: Path, context: dict) -> str:  # type: ignore[type-arg]
    """Render the AGENTS.md managed body.

    Shared-workspace projects stay stub-first (Plan 234). A lone project gets
    routing only; the governance manual is scaffolded once by init.
    """
    is_shared, workspace, _ = _shared_workspace_context(project_root)
    if is_shared and workspace is not None:
        from agentscaffold.config import effective_asset_layout

        layout = effective_asset_layout(workspace)
        return render_template(
            "agents/project_agents_stub.md.j2",
            {
                "project_name": config.framework.project_name,
                "shared": layout.shared,
                "project": layout.project,
            },
        )
    return render_agents_routing(config)


_LEGACY_MANUAL_MARKERS = ("## Planning Rules", "## Plan Lifecycle")
_ROUTING_HEADINGS_DROP_IF_EXACT = (
    "## AgentScaffold MCP Tools",
    "## Multi-Project Workspace Discipline",
)


def _is_legacy_governance_block(body: str) -> bool:
    return any(marker in body for marker in _LEGACY_MANUAL_MARKERS)


def _norm_section(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _drop_exact_routing_sections(lifted: str, routing_body: str) -> str:
    """Keep lifted sections unless a known routing heading matches exactly."""
    routing = {
        section.heading: section.body
        for section in parse_h2_sections(routing_body)
        if section.heading
    }
    kept = []
    preamble = ""
    for section in parse_h2_sections(lifted):
        if not section.heading:
            preamble = section.body
            continue
        drop_candidate = (
            section.heading in _ROUTING_HEADINGS_DROP_IF_EXACT or section.heading in routing
        )
        if drop_candidate and section.heading in routing:
            if _norm_section(section.body) == _norm_section(routing[section.heading]):
                continue
        kept.append(section)
    parts: list[str] = []
    if preamble.strip():
        parts.append(preamble.strip())
    for section in kept:
        parts.append(section.heading)
        if section.body:
            parts.append(section.body)
        parts.append("")
    rendered = "\n".join(parts).strip()
    return rendered + "\n" if rendered else ""


def _lift_legacy_agents_block(path: Path, routing_body: str) -> bool:
    """Move a pre-260 governance block out of the markers. Keeps a ``.bak``."""
    if not path.exists():
        return False
    text = path.read_text()
    begin = text.find(MANAGED_BLOCK_BEGIN)
    end = text.find(MANAGED_BLOCK_END)
    if begin == -1 or end == -1 or end <= begin:
        return False
    inner = text[begin:end]
    if not _is_legacy_governance_block(inner):
        return False
    path.with_suffix(path.suffix + ".bak").write_text(text)
    body = inner[len(MANAGED_BLOCK_BEGIN) :]
    if "-->" in body:
        body = body[body.find("-->") + 3 :]
    lifted = _drop_exact_routing_sections(body, routing_body)
    prefix = text[:begin].rstrip()
    suffix = text[end + len(MANAGED_BLOCK_END) :].lstrip("\n")
    parts = [part for part in (prefix, lifted.rstrip(), suffix.rstrip()) if part]
    path.write_text("\n\n".join(parts) + "\n")
    console.print(
        f"[yellow]Migrated[/yellow] legacy managed manual out of {path.name} "
        "[dim](.bak saved)[/dim]"
    )
    return True


def write_workspace_agents_router(
    workspace_root: Path,
    workspace: WorkspaceConfig,
    *,
    force: bool = False,
    allow_append: bool = False,
) -> str:
    """Write the thin workspace-root AGENTS.md router (Plan 234).

    Written into a managed block so a hand-authored workspace AGENTS.md is never
    clobbered. Returns the write status.
    """
    from agentscaffold.config import effective_asset_layout

    layout = effective_asset_layout(workspace)
    content = render_template(
        "agents/workspace_agents_md.md.j2",
        {
            "shared": layout.shared,
            "projects": workspace.projects,
        },
    )
    dest = workspace_root / "AGENTS.md"
    return write_managed_block(dest, content, force=force, allow_append=allow_append)


def _guidance_stamper(config: ScaffoldConfig, project_root: Path) -> Callable[[str], str]:
    """Return a function that stamps rule content with the canonical hash.

    Identity for a lone or ``project_local`` repo, which has no canonical file to
    cite and whose generated output must stay byte-for-byte as before (ADR-024).
    """
    canonical = canonical_guidance_path(project_root)
    if canonical is None:
        return lambda content: content

    sha = guidance_hash(canonical_guidance_document(config))
    source = os.path.relpath(canonical, project_root).replace(os.sep, "/")
    return lambda content: stamp_guidance(content, sha, source)


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
    elif status == "skipped":
        console.print(f"[dim]Skipped[/dim] {label} [dim](managed=false)[/dim]")
    else:  # unchanged
        console.print(f"[dim]Unchanged[/dim] {label}")


def run_agents_generate(force: bool = False, allow_append: bool = False) -> None:
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

    content = _render_project_agents_md(config, project_root, context)

    dest = project_root / "AGENTS.md"
    if not force:
        _lift_legacy_agents_block(dest, content)
    status = write_managed_block(dest, content, force=force, allow_append=allow_append)
    _report_managed_write(status, str(dest.relative_to(Path.cwd())))


def run_agents_generate_to(
    project_root: Path,
    config_path: Path | None = None,
    force: bool = False,
    allow_append: bool = False,
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
    content = _render_project_agents_md(config, project_root, context)
    dest = project_root / "AGENTS.md"
    if not force:
        _lift_legacy_agents_block(dest, content)
    write_managed_block(dest, content, force=force, allow_append=allow_append)


def run_agents_generate_all_platforms(
    config: ScaffoldConfig,
    project_root: Path,
    dry_run: bool = False,
    force: bool = False,
    allow_append: bool = False,
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
    (.cursor/rules/agentscaffold.mdc, per-reviewer rules, enforcement hooks, agent
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
        "project": [],
    }

    # Canonical routing guidance (shared workspaces only). Written before the
    # per-project rule files so the hash they are stamped with cites a file that
    # already exists on disk.
    if not dry_run:
        canonical_result = write_canonical_guidance(project_root, config)
        if canonical_result is not None:
            canonical_path, canonical_status = canonical_result
            if canonical_status == "unchanged":
                console.print(f"[dim]Unchanged[/dim] {canonical_path}")
            else:
                console.print(f"[green]Wrote[/green] {canonical_path} [dim](canonical)[/dim]")
            written["project"].append(canonical_path)
    elif canonical_guidance_path(project_root) is not None:
        console.print("[dim]dry-run[/dim] would write canonical routing guidance")
    stamp = _guidance_stamper(config, project_root)

    # .gitignore (co-owned -- managed block ignoring runtime artifacts; never clobbered)
    gitignore_path = project_root / ".gitignore"
    if not dry_run:
        status = write_gitignore_block(gitignore_path)
        _report_managed_write(status, ".gitignore")
    else:
        console.print(
            "[dim]dry-run[/dim] would update .gitignore managed block (existing content preserved)"
        )
    written["project"].append(gitignore_path)

    # AGENTS.md (project-owned -- managed block, never clobbered unless force).
    # Under shared_workspace the project AGENTS.md is stub-first (pointers to the
    # workspace shared process assets), and a thin workspace-root router AGENTS.md
    # is generated too (Plan 234).
    context = get_default_context(config)
    agents_md_path = project_root / "AGENTS.md"
    is_shared, ws, ws_root = _shared_workspace_context(project_root)
    if not dry_run:
        agents_body = _render_project_agents_md(config, project_root, context)
        if not force:
            _lift_legacy_agents_block(agents_md_path, agents_body)
        status = write_managed_block(
            agents_md_path,
            agents_body,
            force=force,
            allow_append=allow_append,
        )
        _report_managed_write(status, "AGENTS.md")
    else:
        console.print(
            "[dim]dry-run[/dim] would update AGENTS.md managed block (existing content preserved)"
        )
    written["claude_code"].append(agents_md_path)

    if is_shared and ws is not None and ws_root is not None and ws_root != project_root:
        router_path = ws_root / "AGENTS.md"
        if not dry_run:
            status = write_workspace_agents_router(
                ws_root, ws, force=force, allow_append=allow_append
            )
            _report_managed_write(status, str(router_path))
        else:
            console.print("[dim]dry-run[/dim] would update workspace-root AGENTS.md router")
        written["project"].append(router_path)

    # Claude Code: CLAUDE.md (project-owned -- managed block) + subagents
    claude_md = project_root / "CLAUDE.md"
    if not dry_run:
        status = write_managed_block(
            claude_md, stamp(generate_claude_rules(config)), force=force, allow_append=allow_append
        )
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
    write_cursor_mcp_json(cursor_dir, dry_run=dry_run)
    # MCP routing + graph trust discipline doc (kept in parity with `agents cursor`).
    # Cursor only loads rules with the `.mdc` extension; a plain `.md` in
    # `.cursor/rules/` is ignored. Emit `.mdc` with `alwaysApply: true` so the
    # MCP routing + multi-project discipline is always in agent context. Remove a
    # stale `.md` from older generations so the two do not diverge.
    intent_dest = cursor_dir / "rules" / "agentscaffold.mdc"
    legacy_md = cursor_dir / "rules" / "agentscaffold.md"
    if not dry_run:
        intent_dest.parent.mkdir(parents=True, exist_ok=True)
        cursor_intro = [
            "Use this file for MCP routing behavior and fallback discipline.",
            "For full process governance, also follow `.cursor/rules.md` and `AGENTS.md`.",
        ]
        intent_dest.write_text(
            stamp(
                generate_rule_policy_document(
                    config=config,
                    title="AgentScaffold MCP Rule Routing",
                    intro_lines=cursor_intro,
                    quote_intents=True,
                    always_apply=True,
                )
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
        status = write_managed_block(
            windsurf_rules,
            stamp(generate_windsurf_rules(config)),
            force=force,
            allow_append=allow_append,
        )
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
