"""Cursor IDE setup and configuration."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from agentscaffold.agents.rule_policy import generate_rule_policy_document
from agentscaffold.config import ReviewerConfig, ScaffoldConfig, find_config, load_config
from agentscaffold.rendering import get_default_context, render_template, write_managed_block

console = Console()


def _mcp_json_content(
    workspace_root: str | None = None,
    project_name: str | None = None,
) -> dict[str, object]:
    """Build the mcp.json body, adding ``--workspace``/``--project`` when known.

    In a multi-project workspace the generated config pins the resolution anchor
    so no-argument MCP tools resolve the intended project even when the IDE opens
    a parent folder (Plan 234). A lone repo keeps the bare ``["mcp"]`` args.
    """
    args = ["mcp"]
    if workspace_root:
        args += ["--workspace", workspace_root]
    if project_name:
        args += ["--project", project_name]
    return {
        "mcpServers": {
            "agentscaffold": {
                "command": "scaffold",
                "args": args,
            }
        }
    }


def _detect_workspace_context(project_root: Path) -> tuple[str | None, str | None]:
    """Return (workspace_root, project_name) for a registered multi-project repo.

    Returns ``(None, None)`` for a lone/single-project repo so the generated
    mcp.json stays byte-for-byte the same as before.
    """
    try:
        from agentscaffold.graph.scoping import current_project_name
        from agentscaffold.paths import load_workspace, resolve_workspace_root

        workspace = load_workspace(project_root)
        if not workspace.is_multi_project:
            return None, None
        workspace_root = resolve_workspace_root(project_root)
        project_name = current_project_name(project_root)
        if project_name is None:
            return str(workspace_root), None
        return str(workspace_root), project_name
    except Exception:
        return None, None


def _canonical_entry_installed() -> bool:
    """True when the shared server is registered in the default client config.

    Registering a project and installing the server are separate steps:
    ``scaffold project register`` only writes a registry row. Skipping the
    per-project config on the strength of registration alone could therefore
    leave a project with no server at all, so the skip checks and says so.

    Answers False on any read failure, which at worst prints an extra pointer to
    a harmless command.
    """
    try:
        from agentscaffold.mcp.install import (
            CANONICAL_ENTRY_NAME,
            SERVERS_KEY,
            default_config_path,
            load_config,
        )

        document = load_config(default_config_path())
    except Exception:  # noqa: BLE001 - advisory only; never block generation
        return False
    return CANONICAL_ENTRY_NAME in (document.get(SERVERS_KEY) or {})


def write_cursor_mcp_json(
    cursor_dir: Path,
    workspace_root: str | None = None,
    project_name: str | None = None,
    *,
    dry_run: bool = False,
) -> None:
    """Write ``.cursor/mcp.json`` with the agentscaffold MCP server config.

    Skipped when a shared server already covers this repo -- either because the
    root is registered, or because the canonical entry is installed in the client
    config. Since 0.10 one project-aware server serves every registered project,
    so a per-project config alongside it is the legacy registration that
    ``scaffold mcp install --migrate`` exists to retire; generating one undoes
    that migration, which is what this guard prevents (Plan 253).

    Both conditions are needed, and each catches a case the other misses.
    Registration alone misses a fresh project created after ``scaffold mcp
    install``, which is never registered yet and would otherwise get a duplicate
    server on the documented quick-start path. An installed entry alone misses a
    registered project on a machine whose client config lives elsewhere.

    A lone repo with neither still gets the file, because where no shared server
    covers it, this is the only registration there is -- that is what makes
    ``scaffold init`` work with no further setup.

    When *workspace_root*/*project_name* are not supplied they are auto-detected
    from ``cursor_dir``'s parent, so a registered project in a multi-project
    workspace emits ``["mcp", "--workspace", ..., "--project", ...]`` (Plan 234).

    If the file already exists, skip writing and emit a diff-suggestion to
    stdout so existing custom configs are not overwritten. *dry_run* reports what
    would happen and touches nothing, the parent directory included.
    """
    from agentscaffold.mcp.install import is_registered_root

    mcp_path = cursor_dir / "mcp.json"

    def _display(p: Path) -> str:
        try:
            return str(p.relative_to(Path.cwd()))
        except ValueError:
            return str(p)

    registered = is_registered_root(cursor_dir.parent)
    shared_installed = _canonical_entry_installed()
    if registered or shared_installed:
        reason = "registered project" if registered else "shared server already installed"
        console.print(
            f"[dim]Skipping[/dim] {_display(mcp_path)} "
            f"({reason} — one shared AgentScaffold server serves it)"
        )
        if mcp_path.exists():
            console.print(
                "  This file is a legacy per-project registration. Remove it so the "
                "client loads only the shared server."
            )
        if not shared_installed:
            console.print(
                "  [yellow]No shared server is registered with the client.[/yellow] "
                "Run `scaffold mcp install` so this project has one."
            )
        return

    if workspace_root is None and project_name is None:
        workspace_root, project_name = _detect_workspace_context(cursor_dir.parent)

    content = _mcp_json_content(workspace_root, project_name)

    if mcp_path.exists():
        console.print(
            f"[yellow]Skipping[/yellow] {_display(mcp_path)} "
            "(already exists — verify it contains the agentscaffold server entry)"
        )
        console.print("  Suggested content:\n" + json.dumps(content, indent=2))
        return

    if dry_run:
        console.print(f"[dim]dry-run[/dim] would write {_display(mcp_path)}")
        return

    cursor_dir.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(json.dumps(content, indent=2) + "\n")
    console.print(f"[green]Wrote[/green] {_display(mcp_path)}")


def run_cursor_setup(force: bool = False) -> None:
    """Generate Cursor rule files from scaffold.yaml config.

    ``.cursor/rules.md`` is a project-owned document: the generated guidance is
    written into a managed block, so an existing/hand-authored file is never
    clobbered (created, block-refreshed, or appended). *force* rewrites it whole,
    keeping a ``.bak`` snapshot. The machine-owned routing/trust policy
    ``.cursor/rules/agentscaffold.mdc`` and the per-reviewer rules are always
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
    # Cursor only loads `.mdc` rules; a plain `.md` here is ignored. Emit `.mdc`
    # with `alwaysApply: true` and remove any stale `.md` from older runs.
    intent_dest = rules_dir / "agentscaffold.mdc"
    legacy_md = rules_dir / "agentscaffold.md"
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
    console.print(f"[green]Wrote[/green] {intent_dest.relative_to(Path.cwd())}")

    write_cursor_mcp_json(cursor_dir)

    write_cursor_reviewer_rules(config, cursor_dir)

    if config.enforcement.platform_enabled("cursor"):
        from agentscaffold.hooks.generators.cursor import (
            resolve_scaffold_bin,
            write_cursor_hooks,
            write_embedding_commit_hooks,
        )

        for path in write_cursor_hooks(
            config.enforcement,
            project_root,
            scaffold_bin=resolve_scaffold_bin(),
            min_interval_seconds=config.graph.incremental_min_interval_seconds,
        ):
            console.print(f"[green]Wrote[/green] {path.relative_to(project_root)}")
        if getattr(config.graph, "async_embeddings", "off") == "commit":
            for path in write_embedding_commit_hooks(
                project_root,
                scaffold_bin=resolve_scaffold_bin(),
                min_interval_seconds=config.graph.embedding_min_interval_seconds,
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
        # Reviewer rules are agent-requested (`description` frontmatter); Cursor
        # only honors them with the `.mdc` extension. Emit `.mdc` and clean up a
        # stale `.md` from older generations.
        dest = rules_dir / f"{reviewer.name}.mdc"
        legacy_md = rules_dir / f"{reviewer.name}.md"
        written.append(dest)
        if dry_run:
            console.print(f"[dim]dry-run[/dim] would write {dest}")
        else:
            rules_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            if legacy_md.exists():
                legacy_md.unlink()
            console.print(f"[green]Wrote[/green] .cursor/rules/{reviewer.name}.mdc")

    return written


def _load_prompt_body_for_cursor(reviewer: ReviewerConfig, project_root: Path) -> str:
    """Load the reviewer's prompt body from prompt_file if specified."""
    if not reviewer.prompt_file:
        return ""
    prompt_path = project_root / reviewer.prompt_file
    if prompt_path.is_file():
        return prompt_path.read_text()
    return ""
