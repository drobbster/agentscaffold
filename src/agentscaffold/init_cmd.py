"""Project initialization command."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentscaffold.config import CONFIG_FILENAME, load_config
from agentscaffold.rendering import (
    get_default_context,
    render_template,
    write_gitignore_block,
    write_if_missing,
)

console = Console()


@dataclass
class InitWriter:
    """Every mutation init performs, routed through one object (Plan 249, B6).

    A dry run has to be indistinguishable from not running the command, and an
    idempotent re-run has to be able to say truthfully that it wrote nothing.
    Both need the same thing: one place that knows whether a mutation would
    happen. Threading a ``dry_run`` flag through a dozen helpers instead would
    make each of them a place to forget it, which is how a dry run ends up
    creating a directory.
    """

    dry_run: bool = False
    created: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    dirs_created: list[Path] = field(default_factory=list)
    registered: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.dirs_created or self.registered)

    def write_if_missing(self, path: Path, content: str) -> bool:
        if path.exists():
            self.unchanged.append(path)
            return False
        self.created.append(path)
        if not self.dry_run:
            write_if_missing(path, content)
        return True

    def mkdir(self, path: Path) -> bool:
        if path.exists():
            return False
        self.dirs_created.append(path)
        if not self.dry_run:
            path.mkdir(parents=True, exist_ok=True)
        return True

    def gitignore(self, root: Path) -> bool:
        path = root / ".gitignore"
        if self.dry_run:
            # Ask what would happen without writing. The managed-block helper is
            # the only writer here that can legitimately modify an existing file,
            # so "does it exist" is not enough to predict the outcome.
            from agentscaffold.rendering import gitignore_block_status

            status = gitignore_block_status(path)
        else:
            status = write_gitignore_block(path)

        if status == "unchanged":
            self.unchanged.append(path)
            return False
        if status == "created":
            self.created.append(path)
        else:
            self.updated.append(path)
        return True

    def register(self, name: str) -> None:
        self.registered.append(name)


AVAILABLE_DOMAINS = [
    "trading",
    "webapp",
    "mlops",
    "data_engineering",
    "api_services",
    "infrastructure",
    "mobile",
    "game_dev",
    "embedded",
    "research",
]

VALID_PROFILES = ("interactive", "semi_autonomous")
VALID_RIGOR_LEVELS = ("minimal", "standard", "strict")

# Template path -> output path (relative to project root).
# Paths starting with ">" denote directories that only need to be created (empty).
_TEMPLATE_MAP: dict[str, str] = {
    # Core templates -> docs/ai/templates/
    "core/plan_template.md.j2": "docs/ai/templates/plan_template.md",
    "core/plan_template_bugfix.md.j2": "docs/ai/templates/plan_template_bugfix.md",
    "core/plan_template_refactor.md.j2": "docs/ai/templates/plan_template_refactor.md",
    "core/plan_review_checklist.md.j2": "docs/ai/templates/plan_review_checklist.md",
    "core/spike_template.md.j2": "docs/ai/templates/spike_template.md",
    "core/study_template.md.j2": "docs/ai/templates/study_template.md",
    "core/adr_template.md.j2": "docs/ai/adrs/adr_template.md",
    "core/session_summary.md.j2": "docs/ai/templates/session_summary.md",
    # Prompts -> docs/ai/prompts/
    "prompts/plan_critique.md.j2": "docs/ai/prompts/plan_critique.md",
    "prompts/plan_expansion.md.j2": "docs/ai/prompts/plan_expansion.md",
    "prompts/retrospective.md.j2": "docs/ai/prompts/retrospective.md",
    # Standards -> docs/ai/standards/
    "standards/errors.md.j2": "docs/ai/standards/errors.md",
    "standards/logging.md.j2": "docs/ai/standards/logging.md",
    "standards/config.md.j2": "docs/ai/standards/config.md",
    "standards/testing.md.j2": "docs/ai/standards/testing.md",
    # State -> docs/ai/state/
    "state/workflow_state.md.j2": "docs/ai/state/workflow_state.md",
    "state/learnings_tracker.md.j2": "docs/ai/state/learnings_tracker.md",
    "state/plan_completion_log.md.j2": "docs/ai/state/plan_completion_log.md",
    "state/backlog.md.j2": "docs/ai/backlog.md",
    "state/backlog_archive.md.j2": "docs/ai/backlog_archive.md",
    # Contracts
    "contracts/contracts_readme.md.j2": "docs/ai/contracts/README.md",
    "contracts/contract_template.md.j2": "docs/ai/contracts/contract_template.md",
    # Security
    "security/threat_model_template.md.j2": "docs/security/threat_model_template.md",
    # Project-level docs -> docs/ai/
    "project/product_vision.md.j2": "docs/ai/product_vision.md",
    "project/strategy_roadmap.md.j2": "docs/ai/strategy_roadmap.md",
    "project/collaboration_protocol.md.j2": "docs/ai/collaboration_protocol.md",
    "project/commands.md.j2": "docs/ai/commands.md",
    "project/system_architecture.md.j2": "docs/ai/system_architecture.md",
    "project/architectural_design_changelog.md.j2": "docs/ai/architectural_design_changelog.md",
}

# Directories to ensure exist (even if empty).
_EMPTY_DIRS: list[str] = [
    "docs/ai/plans",
    "docs/ai/spikes",
    "docs/runbook",
    "docs/studies",
]

# Output prefixes that are reusable *process* assets. Under a shared_workspace
# layout (Plan 234) these are written once at the workspace root instead of being
# duplicated into every project.
_SHARED_OUTPUT_PREFIXES: tuple[str, ...] = (
    "docs/ai/prompts/",
    "docs/ai/standards/",
    "docs/ai/templates/",
    "docs/security/",
)
_SHARED_OUTPUT_FILES: tuple[str, ...] = (
    "docs/ai/collaboration_protocol.md",
    "docs/ai/commands.md",
)


def _is_shared_output(out_rel: str) -> bool:
    """True when *out_rel* is a reusable process asset (shared_workspace layout)."""
    return out_rel in _SHARED_OUTPUT_FILES or out_rel.startswith(_SHARED_OUTPUT_PREFIXES)


@dataclass
class EnclosingWorkspace:
    """The workspace *directory* sits inside, if any (Plan 249, Step B6)."""

    root: Path
    manifest_path: Path
    is_shared: bool
    #: True when this project is already listed in the manifest, which is what
    #: makes a re-run of init a no-op rather than a second registration.
    already_member: bool
    project_name: str


def _detect_shared_workspace(directory: Path) -> Path | None:
    """Return the workspace root when *directory* sits in a shared_workspace, else None."""
    workspace = _detect_workspace(directory)
    if workspace is not None and workspace.is_shared:
        return workspace.root
    return None


def _detect_workspace(directory: Path, name: str | None = None) -> EnclosingWorkspace | None:
    """Walk up for an enclosing workspace manifest.

    Broader than :func:`_detect_shared_workspace`, which only answers for the
    shared asset layout. Membership governs *registration*; the layout governs
    where reusable assets are written. They are separate questions: a workspace
    on the legacy project-local layout still has members (ADR-024 keeps its asset
    placement untouched).
    """
    from agentscaffold.config import derive_project_name, find_workspace_config

    ws_path = find_workspace_config(directory)
    if ws_path is None:
        return None
    try:
        workspace = _load_manifest(ws_path)
    except Exception:
        return None

    root = ws_path.parent.resolve()
    if root == directory.resolve():
        # Initializing the workspace root itself is not joining a workspace.
        return None

    try:
        project_name = derive_project_name(directory, explicit=name)
    except Exception:
        project_name = directory.resolve().name

    members = {entry.get("name") for entry in workspace.get("projects") or []}
    layout = (workspace.get("asset_layout") or {}).get("layout")

    return EnclosingWorkspace(
        root=root,
        manifest_path=ws_path,
        is_shared=layout == "shared_workspace",
        already_member=project_name in members,
        project_name=project_name,
    )


def _load_manifest(path: Path) -> dict:
    """Read a workspace manifest as plain data.

    Deliberately not the validated model: init has to round-trip the file,
    preserving the ``id`` and anything a future version adds, and rewriting from
    a model silently drops whatever the model does not know about.
    """
    import yaml

    return yaml.safe_load(path.read_text()) or {}


def _join_workspace(workspace: EnclosingWorkspace, directory: Path, writer: InitWriter) -> None:
    """Add this project to the enclosing workspace's manifest and the registry."""
    import yaml

    if workspace.already_member:
        return

    writer.register(workspace.project_name)
    if writer.dry_run:
        return

    manifest = _load_manifest(workspace.manifest_path)
    projects = list(manifest.get("projects") or [])
    try:
        stored_path = str(directory.resolve().relative_to(workspace.root))
    except ValueError:
        stored_path = str(directory.resolve())
    projects.append({"name": workspace.project_name, "path": stored_path})
    manifest["projects"] = projects
    workspace.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    # Mirror into the user-level registry, which is what makes the project
    # resolvable by the single MCP server. A registry failure must not lose the
    # manifest that was just written, so it degrades to a warning.
    try:
        from agentscaffold.workspace_registry import register_workspace

        register_workspace(
            workspace.root,
            projects=[(p["name"], p["path"]) for p in projects],
        )
    except Exception as exc:  # noqa: BLE001 - registration is best-effort during init
        console.print(
            f"[yellow]Registered in workspace.yaml but not in the registry:[/yellow] {exc}\n"
            f"  Run [bold]scaffold project register {workspace.root}[/bold] to retry."
        )


def _prompt_project_name(directory: Path) -> str:
    default = directory.resolve().name
    return typer.prompt("Project name", default=default)


def _prompt_architecture_layers() -> int:
    value = typer.prompt("Architecture layers", default="6")
    try:
        layers = int(value)
        if layers < 1:
            raise ValueError
        return layers
    except ValueError:
        console.print("[red]Invalid number, using default 6.[/red]")
        return 6


def _prompt_domains() -> list[str]:
    console.print("\nAvailable domain packs:")
    for i, domain in enumerate(AVAILABLE_DOMAINS, 1):
        console.print(f"  {i:2d}. {domain}")
    console.print()
    raw = typer.prompt(
        "Select domains (comma-separated numbers, or 'none')",
        default="none",
    )
    if raw.strip().lower() == "none":
        return []

    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(AVAILABLE_DOMAINS):
                selected.append(AVAILABLE_DOMAINS[idx])
            else:
                console.print(f"[yellow]Skipping invalid index: {part}[/yellow]")
        except ValueError:
            if part in AVAILABLE_DOMAINS:
                selected.append(part)
            else:
                console.print(f"[yellow]Skipping unknown domain: {part}[/yellow]")
    return list(dict.fromkeys(selected))


def _prompt_profile() -> str:
    value = typer.prompt(
        "Execution profile (interactive / semi_autonomous)",
        default="interactive",
    )
    if value in VALID_PROFILES:
        return value
    console.print("[yellow]Invalid profile, using 'interactive'.[/yellow]")
    return "interactive"


def _prompt_rigor() -> str:
    value = typer.prompt(
        "Rigor level (minimal / standard / strict)",
        default="standard",
    )
    if value in VALID_RIGOR_LEVELS:
        return value
    console.print("[yellow]Invalid rigor level, using 'standard'.[/yellow]")
    return "standard"


def _gather_options(directory: Path, non_interactive: bool) -> dict[str, object]:
    """Gather configuration options interactively or with defaults."""
    if non_interactive:
        return {
            "project_name": directory.resolve().name,
            "architecture_layers": 6,
            "domains": [],
            "profile": "interactive",
            "rigor": "standard",
        }

    console.print(
        Panel(
            "AgentScaffold Project Initialization",
            subtitle="Answer the prompts below (press Enter for defaults)",
        )
    )
    return {
        "project_name": _prompt_project_name(directory),
        "architecture_layers": _prompt_architecture_layers(),
        "domains": _prompt_domains(),
        "profile": _prompt_profile(),
        "rigor": _prompt_rigor(),
    }


def _write_scaffold_yaml(directory: Path, options: dict[str, object], writer: InitWriter) -> bool:
    """Render and write scaffold.yaml. Returns True if written."""
    content = render_template("scaffold_yaml.yaml.j2", options)
    return writer.write_if_missing(directory / CONFIG_FILENAME, content)


def _write_templated_files(
    directory: Path, context: dict, writer: InitWriter, shared_root: Path | None = None
) -> tuple[int, int]:  # type: ignore[type-arg]  # noqa: E501
    """Render all templates and write them. Returns (written, skipped) counts.

    When *shared_root* is provided (shared_workspace layout, Plan 234), reusable
    process assets are written once at the workspace root instead of the project.
    """
    written = 0
    skipped = 0
    for tpl_path, out_rel in _TEMPLATE_MAP.items():
        if shared_root is not None and _is_shared_output(out_rel):
            dest = shared_root / out_rel
        else:
            dest = directory / out_rel
        try:
            content = render_template(tpl_path, context)
        except Exception as exc:
            console.print(f"[red]  error rendering {tpl_path}: {exc}[/red]")
            skipped += 1
            continue

        if writer.write_if_missing(dest, content):
            written += 1
        else:
            skipped += 1
    return written, skipped


def _create_empty_dirs(directory: Path, writer: InitWriter) -> int:
    """Ensure empty scaffold directories exist. Returns count created."""
    return sum(1 for rel in _EMPTY_DIRS if writer.mkdir(directory / rel))


def _write_agents_md(directory: Path, context: dict, writer: InitWriter) -> bool:  # type: ignore[type-arg]
    """Write AGENTS.md at the project root."""
    content = render_template("agents/agents_md.md.j2", context)
    return writer.write_if_missing(directory / "AGENTS.md", content)


def _write_cursor_rules(directory: Path, context: dict, writer: InitWriter) -> bool:  # type: ignore[type-arg]
    """Write .cursor/rules.md."""
    content = render_template("agents/cursor_rules.md.j2", context)
    return writer.write_if_missing(directory / ".cursor" / "rules.md", content)


def _write_session_dir(directory: Path, semi_autonomous: bool, writer: InitWriter) -> bool:
    """Create sessions directory if semi-autonomous is enabled."""
    if not semi_autonomous:
        return False
    return writer.mkdir(directory / "docs" / "ai" / "state" / "sessions")


def _write_gitignore(directory: Path, writer: InitWriter) -> bool:
    """Ensure the project .gitignore ignores AgentScaffold runtime artifacts.

    Returns True when the managed block was created or refreshed, False when it
    was already present and unchanged. Never clobbers an existing .gitignore.
    """
    return writer.gitignore(directory)


def _write_empty_readmes(directory: Path, writer: InitWriter) -> int:
    """Write minimal README.md files in empty scaffold directories."""
    stubs: dict[str, str] = {
        "docs/runbook/README.md": "# Runbook\n\nOperational documentation.\n",
        "docs/studies/README.md": "# Studies\n\nExperiment and A/B test documentation.\n",
    }
    return sum(
        1 for rel, content in stubs.items() if writer.write_if_missing(directory / rel, content)
    )


def _print_summary(
    directory: Path,
    options: dict[str, object],
    written: int,
    skipped: int,
    dirs_created: int,
    writer: InitWriter | None = None,
) -> None:
    """Print a rich summary of what was created."""
    table = Table(title="Scaffold Summary", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Project", str(options["project_name"]))
    table.add_row("Directory", str(directory.resolve()))
    table.add_row("Architecture layers", str(options["architecture_layers"]))
    domains = options.get("domains", [])
    table.add_row("Domains", ", ".join(domains) if domains else "(none)")  # type: ignore[arg-type]
    table.add_row("Profile", str(options["profile"]))
    table.add_row("Rigor", str(options["rigor"]))
    table.add_row("Files written", str(written))
    table.add_row("Files skipped (exist)", str(skipped))
    table.add_row("Directories created", str(dirs_created))
    if writer is not None and writer.registered:
        table.add_row("Registered in workspace", ", ".join(writer.registered))

    console.print()
    console.print(table)
    console.print()
    console.print("[green]Initialization complete.[/green]")
    console.print("Next steps:")
    console.print("  1. Review scaffold.yaml and adjust settings")
    console.print("  2. Edit docs/ai/system_architecture.md to define your layers")
    console.print(
        "  3. Run [bold]scaffold index[/bold] to build the knowledge graph"
        " (enables search, reviews, and session memory)"
    )
    console.print(
        "  4. Rule files (AGENTS.md, .cursor/rules/, CLAUDE.md, .windsurfrules) were"
        " generated automatically; run [bold]scaffold agents generate-all[/bold] to"
        " regenerate them after changing scaffold.yaml"
    )


def run_init(directory: Path, non_interactive: bool = False, dry_run: bool = False) -> None:
    """Initialize a new project in the given directory.

    Safe to re-run: with nothing to change it writes zero bytes and says so.
    Inside an existing workspace it joins that workspace rather than cloning it.
    With *dry_run* it reports the same plan and mutates nothing at all.
    """
    directory = directory.resolve()
    writer = InitWriter(dry_run=dry_run)
    if not directory.exists() and not dry_run:
        directory.mkdir(parents=True, exist_ok=True)

    options = _gather_options(directory, non_interactive)

    yaml_written = _write_scaffold_yaml(directory, options, writer)

    config_path = directory / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else load_config(None)

    context = get_default_context(config)
    context.update(
        {
            "profile": options["profile"],
            "rigor": options["rigor"],
        }
    )

    workspace = _detect_workspace(directory, name=str(options["project_name"]))
    shared_root = workspace.root if workspace is not None and workspace.is_shared else None
    if shared_root is not None:
        console.print(
            f"[cyan]Shared workspace layout detected[/cyan]: writing reusable process "
            f"assets once at {shared_root}"
        )
    written, skipped = _write_templated_files(directory, context, writer, shared_root=shared_root)
    dirs_created = _create_empty_dirs(directory, writer)

    if _write_agents_md(directory, context, writer):
        written += 1
    else:
        skipped += 1

    if _write_cursor_rules(directory, context, writer):
        written += 1
    else:
        skipped += 1

    semi_auto = options.get("profile") == "semi_autonomous"
    if _write_session_dir(directory, semi_auto, writer):
        dirs_created += 1

    readme_count = _write_empty_readmes(directory, writer)
    written += readme_count

    if _write_gitignore(directory, writer):
        written += 1

    if yaml_written:
        written += 1

    if workspace is not None:
        _join_workspace(workspace, directory, writer)

    # On a fresh init (scaffold.yaml was just created) generate the full,
    # platform-specific rule set: the MCP routing + graph trust discipline doc
    # (.cursor/rules/agentscaffold.mdc), .cursor/mcp.json, per-reviewer rules,
    # lifecycle hooks, CLAUDE.md + .claude/agents, and Windsurf artifacts.
    # This is gated on a fresh init so that re-running `scaffold init` stays
    # idempotent. Project-owned docs (AGENTS.md, CLAUDE.md, .windsurfrules) are
    # written via write_managed_block with force=False: a pre-existing org/user
    # copy is never clobbered -- the generated guidance is appended as a managed
    # block (or refreshed in place if markers already exist). Only machine-owned
    # rule files are regenerated outright. Use `scaffold agents generate-all
    # [--force]` to fully rewrite on an existing project.
    if yaml_written and not dry_run:
        _generate_platform_rules(directory, config)

    if dry_run:
        _print_dry_run(directory, writer)
        return

    if not writer.changed:
        _print_no_changes(directory, writer)
        return

    _print_summary(directory, options, written, skipped, dirs_created, writer)


def _print_dry_run(directory: Path, writer: InitWriter) -> None:
    """Report the plan without having touched anything."""
    console.print(f"\n[bold]Dry run[/bold] for {directory}")
    if not writer.changed:
        console.print("[green]no changes[/green] -- this project is already initialized.")
        return

    for path in writer.created:
        console.print(f"  would create  {_display(directory, path)}")
    for path in writer.updated:
        console.print(f"  would update  {_display(directory, path)}")
    for path in writer.dirs_created:
        console.print(f"  would create  {_display(directory, path)}/")
    for name in writer.registered:
        console.print(f"  would register  {name} in the enclosing workspace")
    console.print(
        f"\n{len(writer.created)} file(s), {len(writer.dirs_created)} directory(ies), "
        f"{len(writer.unchanged)} already present."
    )
    console.print("[dim]Nothing was written. Re-run without --dry-run to apply.[/dim]")


def _print_no_changes(directory: Path, writer: InitWriter) -> None:
    """A re-run with nothing to do should not read like it did work."""
    console.print(
        f"\n[green]no changes[/green] -- {directory} is already initialized "
        f"({len(writer.unchanged)} files already present, 0 written)."
    )


def _display(directory: Path, path: Path) -> str:
    """Show a path relative to the project when it is inside it."""
    try:
        return str(path.relative_to(directory))
    except ValueError:
        return str(path)


def _generate_platform_rules(directory: Path, config) -> None:  # type: ignore[no-untyped-def]
    """Generate the full platform rule set for a freshly initialized project.

    Failures here are non-fatal: the core scaffold has already been written, so
    we warn and point the user at ``scaffold agents generate-all`` rather than
    aborting init.
    """
    try:
        from agentscaffold.agents.generate import run_agents_generate_all_platforms

        console.print("\n[dim]Generating platform rule files (Cursor, Claude, Windsurf)...[/dim]")
        run_agents_generate_all_platforms(config, directory)
    except Exception as exc:  # noqa: BLE001 - generation is best-effort during init
        console.print(
            f"[yellow]Rule generation skipped:[/yellow] {exc}\n"
            "  Run [bold]scaffold agents generate-all[/bold] to generate platform rules."
        )
