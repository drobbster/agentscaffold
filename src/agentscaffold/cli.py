"""Main CLI entry point for AgentScaffold."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from agentscaffold import __version__
from agentscaffold.benchmark.cli import app as benchmark_app

app = typer.Typer(
    name="scaffold",
    help="AgentScaffold -- structured AI-assisted development framework.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"agentscaffold {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed agentscaffold version and exit.",
    ),
) -> None:
    """AgentScaffold -- structured AI-assisted development framework."""


# ---------------------------------------------------------------------------
# Sub-command groups
# ---------------------------------------------------------------------------

plan_app = typer.Typer(help="Plan lifecycle management.")
app.add_typer(plan_app, name="plan")

study_app = typer.Typer(help="Study (experiment / A-B test) management.")
app.add_typer(study_app, name="study")

spike_app = typer.Typer(help="Time-boxed research spike management.")
app.add_typer(spike_app, name="spike")

domains_app = typer.Typer(help="Domain pack management.")
app.add_typer(domains_app, name="domains")
# Backward-compatible alias for older usage.
app.add_typer(domains_app, name="domain", hidden=True)

agents_app = typer.Typer(help="Agent integration file generation.")
app.add_typer(agents_app, name="agents")

plugins_app = typer.Typer(help="Plugin packaging and distribution.")
app.add_typer(plugins_app, name="plugins")

graph_app = typer.Typer(help="Knowledge graph operations.")
app.add_typer(graph_app, name="graph")

review_app = typer.Typer(help="Graph-powered review generation.")
app.add_typer(review_app, name="review")

session_app = typer.Typer(help="Cross-session memory management.")
app.add_typer(session_app, name="session")

config_app = typer.Typer(help="Configuration inspection.")
app.add_typer(config_app, name="config")

state_app = typer.Typer(help="Sharded governance-state operations.")
app.add_typer(state_app, name="state")

workspace_app = typer.Typer(help="Multi-project workspace management.")
app.add_typer(workspace_app, name="workspace")

project_app = typer.Typer(help="User-level project registration.")
app.add_typer(project_app, name="project")

app.add_typer(benchmark_app, name="benchmark")


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    directory: Path = typer.Argument(
        Path("."),
        help="Directory to scaffold (defaults to current directory).",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        "-y",
        help="Accept all defaults without prompting.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report what init would write without writing anything.",
    ),
) -> None:
    """Scaffold a new project with the AgentScaffold framework."""
    from agentscaffold.init_cmd import run_init

    run_init(directory=directory, non_interactive=non_interactive, dry_run=dry_run)


@app.command()
def validate(
    check_safety_boundaries: bool = typer.Option(
        False, "--check-safety-boundaries", help="Verify no read-only files were modified."
    ),
    check_session_summary: bool = typer.Option(
        False, "--check-session-summary", help="Verify session summary exists for agent PRs."
    ),
    pre_edit: bool = typer.Option(
        False, "--pre-edit", help="Quick pre-edit check (integration + prohibitions only)."
    ),
    warn_only: bool = typer.Option(
        False, "--warn-only", help="Emit failures as warnings and always exit 0."
    ),
) -> None:
    """Run all enforcement checks (lint, integration, retros, prohibitions, secrets)."""
    from agentscaffold.validate.orchestrator import run_validate

    run_validate(
        check_safety_boundaries=check_safety_boundaries,
        check_session_summary=check_session_summary,
        pre_edit=pre_edit,
        warn_only=warn_only,
    )


@app.command(name="retro")
def retro_check() -> None:
    """Find plans missing retrospectives."""
    from agentscaffold.retro.check import run_retro_check

    run_retro_check()


@app.command(name="import")
def import_conversation(
    file: Path = typer.Argument(..., help="Path to conversation export file."),
    fmt: str = typer.Option(
        "auto", "--format", "-f", help="Format: auto, chatgpt, markdown (claude not yet supported)."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output file path (or directory for --split)."
    ),
    list_only: bool = typer.Option(
        False, "--list", "-l", help="List conversation titles and exit."
    ),
    title: str | None = typer.Option(
        None, "--title", "-t", help="Filter by title (case-insensitive substring match)."
    ),
    select: bool = typer.Option(
        False, "--select", "-s", help="Interactively select conversations to import."
    ),
    split: bool = typer.Option(False, "--split", help="Write each conversation to its own file."),
) -> None:
    """Import an AI conversation into project docs."""
    from agentscaffold.import_cmd.router import run_import

    run_import(
        file=file,
        fmt=fmt,
        output=output,
        list_only=list_only,
        title=title,
        select=select,
        split=split,
    )


@app.command()
def metrics() -> None:
    """Show plan metrics and analytics dashboard."""
    from agentscaffold.metrics.dashboard import run_metrics

    run_metrics()


@config_app.command("show")
def config_show() -> None:
    """Show the effective merged config and its inheritance provenance.

    Surfaces the resolution order from `extends:` (Plan 224): which files
    contributed, base-first, and the final merged values after inheritance and
    the rigor preset are applied.
    """
    import yaml as _yaml

    from agentscaffold.config import find_config, load_config, resolve_config_chain

    path = find_config()
    if path is None:
        console.print("[yellow]No scaffold.yaml found; showing built-in defaults.[/yellow]")
        config = load_config()
        console.print(_yaml.safe_dump(config.model_dump(by_alias=True), sort_keys=False))
        return

    chain = resolve_config_chain(path)
    console.print("[bold]Config inheritance (base first, project last):[/bold]")
    for entry in chain:
        marker = " [dim](this file)[/dim]" if entry == path.resolve() else ""
        console.print(f"  - {entry}{marker}")
    if len(chain) == 1:
        console.print("  [dim](no 'extends'; single config)[/dim]")

    config = load_config(path)
    console.print("\n[bold]Effective configuration:[/bold]")
    console.print(_yaml.safe_dump(config.model_dump(by_alias=True), sort_keys=False))


@app.command()
def version() -> None:
    """Show AgentScaffold version."""
    try:
        resolved_version = package_version("agentscaffold")
    except PackageNotFoundError:
        # Fallback for source-only execution without installed metadata.
        resolved_version = __version__
    console.print(f"agentscaffold {resolved_version}")


# ---------------------------------------------------------------------------
# Plan sub-commands
# ---------------------------------------------------------------------------


@plan_app.command("create")
def plan_create(
    name: str = typer.Argument(..., help="Plan name (used in filename)."),
    plan_type: str = typer.Option(
        "feature",
        "--type",
        "-t",
        help="Plan type: feature, bugfix, refactor.",
    ),
) -> None:
    """Create a new plan from template."""
    from agentscaffold.plan.create import run_plan_create

    run_plan_create(name=name, plan_type=plan_type)


@plan_app.command("lint")
def plan_lint(
    plan: str | None = typer.Option(
        None, "--plan", "-p", help="Specific plan number or filename to lint."
    ),
) -> None:
    """Validate plan structure and cohesion."""
    from agentscaffold.plan.lint import run_plan_lint

    run_plan_lint(plan=plan)


@plan_app.command("status")
def plan_status() -> None:
    """Show all plans with lifecycle state dashboard."""
    from agentscaffold.plan.status import run_plan_status

    run_plan_status()


@plan_app.command("claim")
def plan_claim(
    number: str = typer.Argument(..., help="Plan number to claim (e.g. 225)."),
    owner: str = typer.Option(..., "--owner", "-o", help="Who is claiming the plan."),
) -> None:
    """Record advisory, git-backed ownership of an in-flight plan."""
    from agentscaffold import collab
    from agentscaffold.config import load_config
    from agentscaffold.paths import ResolvedPaths, resolve_root

    paths = ResolvedPaths(load_config(), resolve_root())
    try:
        record = collab.claim_plan(paths.claims_dir, number, owner)
    except collab.CollabError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Plan {record['plan']} claimed by '{record['owner']}'"
        f" at {record['claimed_at']}.[/green]"
    )
    console.print("[dim]Claim is advisory (git-backed visibility, not a hard lock).[/dim]")


@plan_app.command("release")
def plan_release(
    number: str = typer.Argument(..., help="Plan number to release."),
) -> None:
    """Clear an advisory plan claim."""
    from agentscaffold import collab
    from agentscaffold.config import load_config
    from agentscaffold.paths import ResolvedPaths, resolve_root

    paths = ResolvedPaths(load_config(), resolve_root())
    if collab.release_plan(paths.claims_dir, number):
        console.print(f"[green]Released claim on plan {number}.[/green]")
    else:
        console.print(f"[yellow]No claim found for plan {number}.[/yellow]")


@state_app.command("render")
def state_render() -> None:
    """Assemble sharded fragments into canonical workflow_state.md / backlog.md."""
    from agentscaffold import collab
    from agentscaffold.config import load_config
    from agentscaffold.paths import ResolvedPaths, resolve_root

    config = load_config()
    if not config.collab.sharded:
        console.print(
            "[yellow]collab.sharded is false; nothing to render."
            " Enable sharding in scaffold.yaml first.[/yellow]"
        )
        raise typer.Exit(code=0)

    paths = ResolvedPaths(config, resolve_root())
    targets = [
        (paths.workflow_fragments_dir, paths.workflow_state_file),
        (paths.backlog_items_dir, paths.backlog_file),
    ]
    any_written = False
    for frag_dir, target in targets:
        if not frag_dir.is_dir():
            continue
        if collab.render_to_file(frag_dir, target):
            console.print(f"[green]Rendered {target}[/green]")
            any_written = True
        else:
            console.print(f"[dim]{target} already up to date.[/dim]")
    if not any_written:
        console.print("[dim]No fragment directories found; nothing rendered.[/dim]")


@state_app.command("split")
def state_split(
    target: str = typer.Argument(
        "workflow_state",
        help="Which file to shard: 'workflow_state' or 'backlog'.",
    ),
) -> None:
    """Shard an existing governance file into per-entry fragments (reversible)."""
    from agentscaffold import collab
    from agentscaffold.config import load_config
    from agentscaffold.paths import ResolvedPaths, resolve_root

    paths = ResolvedPaths(load_config(), resolve_root())
    mapping = {
        "workflow_state": (
            paths.workflow_state_file,
            paths.workflow_fragments_dir,
            collab.WORKFLOW_STATE_BOUNDARY,
        ),
        "backlog": (paths.backlog_file, paths.backlog_items_dir, collab.BACKLOG_BOUNDARY),
    }
    if target not in mapping:
        console.print(f"[red]Unknown target '{target}'. Use 'workflow_state' or 'backlog'.[/red]")
        raise typer.Exit(code=1)
    source, frag_dir, boundary = mapping[target]
    try:
        written = collab.split_file(source, frag_dir, boundary)
    except collab.CollabError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Split {source} into {len(written)} fragments under {frag_dir}.[/green]")
    console.print("[dim]Reverse with 'scaffold state render'.[/dim]")


# ---------------------------------------------------------------------------
# Spike sub-commands
# ---------------------------------------------------------------------------


@spike_app.command("create")
def spike_create(
    name: str = typer.Argument(..., help="Spike name (used in filename)."),
) -> None:
    """Create a new spike from template."""
    from agentscaffold.spike.create import run_spike_create

    run_spike_create(name=name)


# ---------------------------------------------------------------------------
# Study sub-commands
# ---------------------------------------------------------------------------


@study_app.command("create")
def study_create(
    name: str = typer.Argument(..., help="Study name (used in filename)."),
) -> None:
    """Create a new study from template."""
    from agentscaffold.study.create import run_study_create

    run_study_create(name=name)


@study_app.command("lint")
def study_lint() -> None:
    """Validate study files for template compliance."""
    from agentscaffold.study.lint import run_study_lint

    run_study_lint()


@study_app.command("list")
def study_list() -> None:
    """List and query studies from the registry."""
    from agentscaffold.study.list_cmd import run_study_list

    run_study_list()


@study_app.command("search")
def study_search(
    topic: str = typer.Argument(..., help="Keyword to search in study tags/titles."),
    outcome: str | None = typer.Option(None, "--outcome", "-o", help="Filter by outcome."),
) -> None:
    """Search studies in the knowledge graph by topic or outcome."""
    import json

    from agentscaffold.mcp.server import _tool_find_studies

    _config, store = _require_graph()
    meta = {"source": "cli"}
    args = {"topic": topic}
    if outcome:
        args["outcome"] = outcome
    result = _tool_find_studies(store, args, meta)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


@study_app.command("experiments")
def study_experiments(
    plan: int = typer.Argument(..., help="Plan number to find related experiments for."),
) -> None:
    """Find prior experiments related to a plan."""
    import json

    from agentscaffold.mcp.server import _tool_prior_experiments

    _config, store = _require_graph()
    meta = {"source": "cli"}
    result = _tool_prior_experiments(store, {"plan_number": plan}, meta)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


# ---------------------------------------------------------------------------
# ADR sub-commands
# ---------------------------------------------------------------------------

adr_app = typer.Typer(help="Architecture Decision Record management.")
app.add_typer(adr_app, name="adr")


@adr_app.command("list")
def adr_list() -> None:
    """List all ADRs from the knowledge graph."""
    from rich.table import Table as RichTable

    from agentscaffold.review.queries import get_all_adrs

    _config, store = _require_graph()
    adrs = get_all_adrs(store)
    store.close()

    if not adrs:
        console.print("No ADRs found in the graph.")
        return

    tbl = RichTable(title="Architecture Decision Records", show_header=True)
    tbl.add_column("Number", style="cyan", justify="right")
    tbl.add_column("Title", style="green")
    tbl.add_column("Status")
    tbl.add_column("Date")
    tbl.add_column("Superseded By")

    for a in adrs:
        tbl.add_row(
            str(a.get("a.number", "")),
            a.get("a.title", ""),
            a.get("a.status", ""),
            a.get("a.date", ""),
            a.get("a.supersededBy", "") or "-",
        )
    console.print(tbl)


@adr_app.command("search")
def adr_search(
    topic: str = typer.Argument(..., help="Keyword to search in ADR titles."),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status."),
) -> None:
    """Search ADRs by topic keyword."""
    import json

    from agentscaffold.mcp.server import _tool_find_adrs

    _config, store = _require_graph()
    meta = {"source": "cli"}
    args: dict[str, Any] = {"topic": topic}
    if status:
        args["status"] = status
    result = _tool_find_adrs(store, args, meta)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


@adr_app.command("decision")
def adr_decision(
    plan: int = typer.Argument(..., help="Plan number to get decision context for."),
) -> None:
    """Show full decision chain for a plan (ADRs, spikes, studies)."""
    import json

    from agentscaffold.mcp.server import _tool_decision_context

    _config, store = _require_graph()
    meta = {"source": "cli"}
    result = _tool_decision_context(store, {"plan_number": plan}, meta)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


# ---------------------------------------------------------------------------
# Domain sub-commands
# ---------------------------------------------------------------------------


@domains_app.command("add")
def domain_add(
    pack: str = typer.Argument(..., help="Domain pack name (e.g., trading, webapp, mlops)."),
) -> None:
    """Install a domain pack's templates and standards."""
    from agentscaffold.domain_packs.loader import run_domain_add

    run_domain_add(pack=pack)


@domains_app.command("list")
def domain_list() -> None:
    """List available and installed domain packs."""
    from agentscaffold.domain_packs.registry import run_domain_list

    run_domain_list()


# ---------------------------------------------------------------------------
# Agents sub-commands
# ---------------------------------------------------------------------------


@agents_app.command("generate")
def agents_generate(
    force: bool = typer.Option(
        False,
        "--force",
        help="Rewrite the entire AGENTS.md instead of updating its managed block (.bak kept).",
    ),
) -> None:
    """Generate AGENTS.md from scaffold.yaml config.

    AGENTS.md is project-owned: generated guidance is written into a managed block,
    so existing/hand-authored content is preserved. --force rewrites the whole file.
    """
    from agentscaffold.agents.generate import run_agents_generate

    run_agents_generate(force=force)


@agents_app.command("cursor")
def agents_cursor(
    force: bool = typer.Option(
        False,
        "--force",
        help="Rewrite the whole .cursor/rules.md instead of its managed block (.bak kept).",
    ),
) -> None:
    """Generate .cursor/rules.md and intent mapping from config.

    The machine-owned .cursor/rules/agentscaffold.mdc routing policy is always
    regenerated; .cursor/rules.md is project-owned and updated via a managed block
    (existing content preserved). --force rewrites the whole file.
    """
    from agentscaffold.agents.cursor import run_cursor_setup

    run_cursor_setup(force=force)


@agents_app.command("windsurf")
def agents_windsurf() -> None:
    """Generate .windsurfrules from TOOL_INTENTS."""
    from agentscaffold.agents.windsurf import run_windsurf_setup

    run_windsurf_setup()


@agents_app.command("claude")
def agents_claude() -> None:
    """Generate CLAUDE.md from TOOL_INTENTS."""
    from agentscaffold.agents.claude import run_claude_setup

    run_claude_setup()


@agents_app.command("prompt")
def agents_prompt() -> None:
    """Export generic system-prompt snippet for any LLM platform."""
    from agentscaffold.agents.prompt import run_prompt_export

    run_prompt_export()


@agents_app.command("hooks")
def agents_hooks(
    platform: str = typer.Option(
        "all",
        "--platform",
        "-p",
        help="Target platform: 'claude-code', 'cursor', 'windsurf', or 'all'.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print paths without writing files."),
) -> None:
    """Generate platform-native lifecycle hooks from enforcement config."""
    from agentscaffold.config import load_config
    from agentscaffold.hooks.generators.claude_code import write_claude_code_hooks
    from agentscaffold.hooks.generators.cursor import (
        generate_cursor_enforcement_files,
        resolve_scaffold_bin,
        write_cursor_hooks,
    )
    from agentscaffold.hooks.generators.windsurf import write_windsurf_hooks

    config = load_config()
    enforcement = config.enforcement
    root = Path.cwd()

    platforms = ["claude-code", "cursor", "windsurf"] if platform == "all" else [platform]

    for plat in platforms:
        if not enforcement.platform_enabled(plat):
            console.print(f"[dim]Skipping {plat} (disabled in config)[/dim]")
            continue

        if plat == "claude-code":
            path = write_claude_code_hooks(
                enforcement,
                root,
                scaffold_bin=resolve_scaffold_bin(),
                min_interval_seconds=config.graph.incremental_min_interval_seconds,
                dry_run=dry_run,
            )
            label = "Would write" if dry_run else "Wrote"
            console.print(f"[green]{label}[/green] {path.relative_to(root)}")
        elif plat == "cursor":
            paths = generate_cursor_enforcement_files(enforcement, output_dir=root, dry_run=dry_run)
            paths += write_cursor_hooks(
                enforcement,
                root,
                scaffold_bin=resolve_scaffold_bin(),
                min_interval_seconds=config.graph.incremental_min_interval_seconds,
                dry_run=dry_run,
            )
            label = "Would write" if dry_run else "Wrote"
            for p in paths:
                console.print(f"[green]{label}[/green] {p.relative_to(root)}")
            if not paths:
                console.print("[dim]No enforcement rules for cursor[/dim]")
        elif plat == "windsurf":
            path = write_windsurf_hooks(enforcement, root, dry_run=dry_run)
            label = "Would write" if dry_run else "Wrote"
            console.print(f"[green]{label}[/green] {path.relative_to(root)}")
        else:
            console.print(f"[red]Unknown platform: {plat}[/red]")


@agents_app.command("skills")
def agents_skills(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print paths without writing files."),
    if_standards_changed: bool = typer.Option(
        False,
        "--if-standards-changed",
        help="Only regenerate if standards files are newer than existing skills.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Overwrite skill files even if they look user/org-authored "
            "(no managed_by marker). A .bak snapshot is kept."
        ),
    ),
) -> None:
    """Generate SKILL.md files into .claude/skills/ and .cursor/skills/.

    User/org-authored skill files (those without a ``managed_by: agentscaffold``
    frontmatter marker) are preserved and never overwritten unless ``--force``.
    """
    from agentscaffold.skills.catalog import write_catalog
    from agentscaffold.skills.generator import generate_skills_from_standards_dir

    root = Path.cwd()
    standards_dir = root / "docs" / "ai" / "standards"
    claude_skills = root / ".claude" / "skills"
    cursor_skills = root / ".cursor" / "skills"

    # Quick mtime check: skip if no standards are newer than the marker
    if if_standards_changed:
        marker = root / ".scaffold" / ".skills_generated"
        if marker.is_file() and standards_dir.is_dir():
            marker_mtime = marker.stat().st_mtime
            any_newer = any(f.stat().st_mtime > marker_mtime for f in standards_dir.glob("*.md"))
            if not any_newer:
                return  # nothing changed, skip silently

    written: list[Path] = []
    for output_dir in (claude_skills, cursor_skills):
        paths = generate_skills_from_standards_dir(
            standards_dir, output_dir, dry_run=dry_run, force=force
        )
        written.extend(paths)
        label = "Would write" if dry_run else "Wrote"
        for p in paths:
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            console.print(f"[green]{label}[/green] {rel}")

    if not dry_run and written:
        for skills_dir in (claude_skills, cursor_skills):
            catalog_path = skills_dir / "SKILLS_CATALOG.md"
            write_catalog([skills_dir], catalog_path, dry_run=dry_run)
            try:
                rel = catalog_path.relative_to(root)
            except ValueError:
                rel = catalog_path
            console.print(f"[green]Wrote[/green] {rel}")

        # Update marker timestamp
        marker = root / ".scaffold" / ".skills_generated"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

    if not written:
        console.print("[dim]No standards found in docs/ai/standards/[/dim]")


@agents_app.command("generate-all")
def agents_generate_all(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print paths without writing files."),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Rewrite project-owned docs (AGENTS.md, CLAUDE.md, .windsurfrules) whole "
            "instead of updating their managed block; a .bak snapshot is kept for each."
        ),
    ),
) -> None:
    """Generate all platform artifacts (AGENTS.md, CLAUDE.md, Cursor rules, Windsurf, hooks).

    Project-owned docs (AGENTS.md, CLAUDE.md, .windsurfrules) are never clobbered:
    generated guidance is written into a managed block (created/refreshed/appended)
    so existing content is preserved. --force rewrites them whole. Machine-owned
    files (.cursor/rules/agentscaffold.mdc, reviewer rules, enforcement hooks) are
    always regenerated.
    """
    from agentscaffold.agents.generate import run_agents_generate_all_platforms
    from agentscaffold.config import load_config

    config = load_config()
    run_agents_generate_all_platforms(config, Path.cwd(), dry_run=dry_run, force=force)


# ---------------------------------------------------------------------------
# Plugin commands
# ---------------------------------------------------------------------------


@plugins_app.command("package")
def plugins_package(
    domain: str = typer.Option(..., "--domain", "-d", help="Domain pack name to package."),
    output: str = typer.Option("dist/plugins", "--output", "-o", help="Output directory."),
    version: str = typer.Option("0.1.0", "--version", "-v", help="Package version (semver)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print output path without writing."),
) -> None:
    """Package a domain pack into a pip-installable plugin."""
    from agentscaffold.plugins.packaging import package_domain_plugin

    output_dir = Path(output)
    pkg_dir = package_domain_plugin(domain, output_dir, version=version, dry_run=dry_run)
    if dry_run:
        console.print(f"[dim]dry-run: would create {pkg_dir}[/dim]")
    else:
        console.print(f"[green]Plugin package created:[/green] {pkg_dir}")


# ---------------------------------------------------------------------------
# CI / Task runner (top-level commands)
# ---------------------------------------------------------------------------


@app.command(name="ci")
def ci_setup(
    provider: str = typer.Option("github", "--provider", "-p", help="CI provider: github."),
) -> None:
    """Generate CI workflow files."""
    from agentscaffold.ci.setup import run_ci_setup

    run_ci_setup(provider=provider)


@app.command(name="taskrunner")
def taskrunner_setup(
    fmt: str = typer.Option("both", "--format", "-f", help="Format: both, justfile, makefile."),
) -> None:
    """Generate justfile and/or Makefile with framework commands."""
    from agentscaffold.taskrunner.setup import run_taskrunner_setup

    run_taskrunner_setup(fmt=fmt)


@app.command(name="notify")
def notify(
    event: str = typer.Argument(..., help="Event name (e.g. plan_complete, escalation)."),
    message: str = typer.Argument(..., help="Notification body text."),
) -> None:
    """Send a notification via the configured channel."""
    from agentscaffold.notify.sender import send_notification

    send_notification(event=event, message=message)


# ---------------------------------------------------------------------------
# Knowledge graph commands
# ---------------------------------------------------------------------------


@app.command(name="index")
def index_cmd(
    path: Path = typer.Argument(Path("."), help="Root directory to index."),
    incremental: bool = typer.Option(False, "--incremental", help="Only re-index changed files."),
    with_embeddings: bool = typer.Option(False, "--embeddings", help="Generate code embeddings."),
    audit: bool = typer.Option(False, "--audit", help="Log all resolution decisions."),
    update_rules: bool = typer.Option(
        False, "--update-rules", help="Regenerate agent rule files after indexing."
    ),
    force_rebuild: bool = typer.Option(
        False,
        "--force-rebuild",
        help="On a schema-version rebuild, proceed even if preserving existing "
        "findings/sessions/backlog fails. WARNING: discards that data permanently.",
    ),
) -> None:
    """Build or rebuild the knowledge graph."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import index

    config = load_config()
    # Honor the config default (graph.embeddings) when the flag is not passed,
    # so embeddings can be enabled repo-wide via scaffold.yaml without requiring
    # --embeddings on every index invocation (including the PostToolUse hook).
    embeddings = with_embeddings or bool(getattr(config.graph, "embeddings", False))
    if embeddings:
        # Pin the embedding model + weights cache before indexing so the model
        # loads from the deterministic, offline-capable location (Plan 227).
        from agentscaffold.graph.embeddings import configure_embeddings

        configure_embeddings(config.search.embedding_model, config.search.cache_dir)
    summary = index(
        path=path,
        config=config,
        incremental=incremental,
        embeddings=embeddings,
        audit=audit,
        force_rebuild=force_rebuild,
    )

    # Plan 223: on a fresh/ephemeral cache, governance is rebuilt from the
    # committed artifact. Point the operator at where the durable record lives.
    if summary.get("restored_from_artifact"):
        from agentscaffold.graph.governance_store import resolve_governance_artifact

        artifact = resolve_governance_artifact(config)
        console.print(
            f"[dim]Governance system of record: {artifact} "
            "(committed to git; rebuilt the cache from it).[/dim]"
        )

    if update_rules:
        console.print("\n[bold]Regenerating agent rule files...[/bold]")
        from agentscaffold.agents.cursor import run_cursor_setup

        try:
            run_cursor_setup()
        except SystemExit:
            console.print("[yellow]Skipped cursor rules (no scaffold.yaml).[/yellow]")


@graph_app.command("stats")
def graph_stats() -> None:
    """Show codebase statistics and health dashboard."""
    from rich.table import Table

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    stats = store.get_stats()
    store.close()

    table = Table(title="Graph Statistics", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Schema version", str(stats["schema_version"]))
    table.add_row("Last indexed", stats.get("last_indexed", "never") or "never")
    table.add_row("Pipeline state", stats.get("pipeline_state", "unknown"))
    table.add_row("Files", str(stats["files"]))
    table.add_row("Folders", str(stats["folders"]))
    table.add_row("Functions", str(stats["functions"]))
    table.add_row("Classes", str(stats["classes"]))
    table.add_row("Methods", str(stats["methods"]))
    table.add_row("Interfaces", str(stats["interfaces"]))
    table.add_row("Import edges", str(stats["imports_edges"]))
    table.add_row("Call edges", str(stats["calls_edges"]))
    table.add_row("Communities", str(stats["communities"]))
    table.add_row("Plans", str(stats["plans"]))
    table.add_row("Contracts", str(stats["contracts"]))
    table.add_row("Learnings", str(stats["learnings"]))
    table.add_row("Studies", str(stats.get("studies", 0)))
    table.add_row("ADRs", str(stats.get("adrs", 0)))
    table.add_row("Spikes", str(stats.get("spikes", 0)))
    table.add_row("Review findings", str(stats["review_findings"]))
    table.add_row("Parsing warnings", str(stats["parsing_warnings"]))

    console.print(table)


@graph_app.command("query")
def graph_query(
    sql: str = typer.Argument(..., help="SQL query to execute."),
) -> None:
    """Execute a raw SQL query against the graph."""
    import json

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    try:
        results = store.query(sql)
        console.print(json.dumps(results, indent=2, default=str))
    except Exception as exc:
        console.print(f"[red]Query error: {exc}[/red]")
        raise SystemExit(1) from exc
    finally:
        store.close()


@graph_app.command("search")
def graph_search(
    query: str = typer.Argument(..., help="Natural language search query."),
    mode: str = typer.Option(
        "hybrid", "--mode", "-m", help="Search mode: keyword, semantic, hybrid."
    ),
    top_k: int = typer.Option(10, "--top", "-k", help="Number of results."),
    kind: str = typer.Option("code", "--kind", help="Search corpus: code, governance, or all."),
    rerank: bool = typer.Option(
        False, "--rerank", help="Rerank final results with the configured cross-encoder."
    ),
    table: str = typer.Option(
        "",
        "--table",
        "-t",
        help=(
            "Limit to a specific table (Function, Class, Method, File, Plan, "
            "Learning, ReviewFinding, Study, ADR, Spike, BacklogItem)."
        ),
    ),
    project: str = typer.Option(
        "", "--project", "-p", help="Target a specific project (multi-project workspace)."
    ),
    all_projects: bool = typer.Option(
        False, "--all-projects", help="Search across every project in the workspace."
    ),
) -> None:
    """Search the knowledge graph using natural language.

    In a multi-project workspace results default to the current project; use
    ``--project NAME`` to target a sibling or ``--all-projects`` to federate.
    """
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.scoping import ScopingError
    from agentscaffold.graph.search import (
        CODE_TABLES,
        GOVERNANCE_TABLES,
        evaluate_retrieval,
        format_search_results,
        hybrid_search,
    )

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    if (mode or "hybrid").lower() in ("semantic", "hybrid"):
        # Pin model + cache before any semantic load so query-time and index-time
        # use the same weights location (Plan 227).
        from agentscaffold.graph.embeddings import configure_embeddings

        configure_embeddings(config.search.embedding_model, config.search.cache_dir)

    store = open_graph(config)

    retrieval = evaluate_retrieval(store, mode)
    if retrieval["retrieval_status"] != "available":
        console.print(
            f"[yellow]Retrieval {retrieval['retrieval_status']}: "
            f"{retrieval['retrieval_reason']}.[/yellow]\n"
        )
    effective_mode = retrieval["retrieval_effective_mode"]
    if effective_mode in ("keyword", "semantic", "hybrid"):
        mode = effective_mode

    if table:
        tables = [table]
    elif kind == "code":
        tables = CODE_TABLES
    elif kind == "governance":
        tables = GOVERNANCE_TABLES
    elif kind == "all":
        tables = [*CODE_TABLES, *GOVERNANCE_TABLES]
    else:
        store.close()
        console.print("[red]--kind must be one of: code, governance, all[/red]")
        raise SystemExit(1)
    try:
        results = hybrid_search(
            store,
            query,
            mode=mode,
            top_k=top_k,
            tables=tables,
            rerank=rerank or config.search.rerank,
            rerank_model=config.search.rerank_model,
            project=project or None,
            all_projects=all_projects,
        )
    except ScopingError as exc:
        store.close()
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    store.close()
    console.print(format_search_results(results))


@graph_app.command("warm")
def graph_warm() -> None:
    """Provision (download + cache) the embedding model so search works offline.

    Installing ``agentscaffold[search]`` gets the library but NOT the model
    weights, which are otherwise downloaded lazily on first index/search (a
    runtime failure when offline). Run this once, with network access, to cache
    the configured model into the workspace-pinned cache dir.
    """
    from agentscaffold.config import load_config
    from agentscaffold.graph import embeddings as _embeddings

    config = load_config()
    _embeddings.configure_embeddings(config.search.embedding_model, config.search.cache_dir)

    if not _embeddings._st_available:
        console.print(
            "[red]sentence-transformers is not installed.[/red] "
            "Install it with: [bold]pip install 'agentscaffold\\[search]'[/bold]"
        )
        raise SystemExit(1)

    model = config.search.embedding_model
    cache = _embeddings._active_cache_dir() or "default Hugging Face cache (~/.cache/huggingface)"
    console.print(f"[dim]Provisioning embedding model '{model}' into {cache} ...[/dim]")
    try:
        _embeddings.warm_model()
    except Exception as exc:  # noqa: BLE001 - report any download/load failure cleanly
        console.print(
            f"[red]Could not provision the model:[/red] {exc}\n"
            "Check your network connection and try again."
        )
        raise SystemExit(1) from exc
    console.print(f"[green]Model ready[/green] -- '{model}' is cached and loads offline.")


@graph_app.command("model-status")
def graph_model_status() -> None:
    """Report embedding-search readiness: package installed and weights cached."""
    from rich.table import Table

    from agentscaffold.config import load_config
    from agentscaffold.graph import embeddings as _embeddings

    config = load_config()
    _embeddings.configure_embeddings(config.search.embedding_model, config.search.cache_dir)

    package_ok = _embeddings._st_available
    weights_ok = _embeddings.model_ready() if package_ok else False
    cache = _embeddings._active_cache_dir() or "~/.cache/huggingface (default)"

    table = Table(title="Semantic search readiness")
    table.add_column("Check")
    table.add_column("Status")
    table.add_row(
        "sentence-transformers package",
        "[green]installed[/green]" if package_ok else "[red]missing[/red]",
    )
    table.add_row("embedding model", config.search.embedding_model)
    table.add_row("weights cache dir", str(cache))
    table.add_row(
        "model weights cached (offline-ready)",
        "[green]yes[/green]" if weights_ok else "[yellow]no[/yellow]",
    )
    console.print(table)

    if not package_ok:
        console.print(
            "\nInstall search support: [bold]pip install 'agentscaffold\\[search]'[/bold]"
        )
    elif not weights_ok:
        console.print(
            "\nProvision the weights once (needs network): [bold]scaffold graph warm[/bold]\n"
            "Until then, semantic/hybrid search degrades to keyword-only."
        )


@graph_app.command("duplicates")
def graph_duplicates(
    table: str = typer.Option(
        "Function", "--table", "-t", help="Definition type (Function, Class, Method, File)."
    ),
    threshold: float = typer.Option(
        0.92, "--threshold", help="Minimum cosine similarity to report (0-1)."
    ),
    top_n: int = typer.Option(50, "--top", "-n", help="Maximum pairs to show."),
) -> None:
    """Surface cross-project near-duplicate definitions to drive shared-library reuse.

    Only meaningful in a multi-project workspace; a single-project repo has no
    cross-project pairs and reports nothing. Requires embeddings
    ('scaffold index --embeddings'). Quality is bounded by embedding text;
    Plan 227 improves precision.
    """
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.embeddings import configure_embeddings, find_duplicates

    config = load_config()
    configure_embeddings(config.search.embedding_model, config.search.cache_dir)
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    try:
        pairs = find_duplicates(store, table=table, threshold=threshold, top_n=top_n)
    finally:
        store.close()

    if not pairs:
        console.print(
            "No cross-project duplicates found "
            "(single-project workspace, no embeddings, or none above threshold)."
        )
        return

    from rich.table import Table

    tbl = Table(title=f"Cross-project {table} duplicates", show_header=True)
    tbl.add_column("Similarity", justify="right", style="cyan")
    tbl.add_column("Project A", style="green")
    tbl.add_column("Definition A")
    tbl.add_column("Project B", style="green")
    tbl.add_column("Definition B")
    for p in pairs:
        tbl.add_row(
            f"{p['similarity']:.4f}",
            p.get("project_a", ""),
            p.get("id_a", ""),
            p.get("project_b", ""),
            p.get("id_b", ""),
        )
    console.print(tbl)


@graph_app.command("communities")
def graph_communities() -> None:
    """Show detected module communities."""
    from rich.table import Table

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.communities import get_communities

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    communities = get_communities(store)
    store.close()

    if not communities:
        console.print("No communities detected. Run 'scaffold index' to detect them.")
        return

    tbl = Table(title="Module Communities", show_header=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Label", style="green")
    tbl.add_column("Files", justify="right")
    tbl.add_column("Functions", justify="right")
    tbl.add_column("Members")

    for c in communities:
        files = c.get("files", [])
        preview = ", ".join(files[:3])
        if len(files) > 3:
            preview += f" (+{len(files) - 3} more)"
        tbl.add_row(
            str(c.get("c.id", "")),
            str(c.get("c.label", "")),
            str(c.get("c.fileCount", 0)),
            str(c.get("c.functionCount", 0)),
            preview,
        )

    console.print(tbl)


@graph_app.command("orient")
def graph_orient() -> None:
    """Composite: session orientation with stats, workflow state, and recent activity."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.mcp.server import _build_meta, _tool_orient

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    root = Path.cwd()
    meta = _build_meta(store, root)
    result = _tool_orient(store, meta, root, config)
    store.close()

    ws = result.get("workflow_state", {})
    console.print("[bold]Workflow State[/bold]")
    console.print(f"  Blockers: {ws.get('blockers', 'None')}")
    console.print(f"  Next Steps: {ws.get('next_steps', 'None')}")
    console.print(f"  In-Progress Plans: {ws.get('in_progress_plans', [])}")

    console.print("\n[bold]Recent Plans:[/bold]")
    for p in result.get("recent_plans", [])[:5]:
        console.print(f"  Plan {p.get('p.number')}: {p.get('p.title')} [{p.get('p.status')}]")

    hot = result.get("hot_files", [])
    if hot:
        console.print("\n[bold]Hot Files:[/bold]")
        for h in hot:
            console.print(f"  {h.get('f.path')} ({h.get('plan_count')} plans)")

    studies = result.get("recent_studies", [])
    if studies:
        console.print("\n[bold]Recent Studies:[/bold]")
        for s in studies:
            console.print(f"  {s.get('s.studyId')}: {s.get('s.title')}")

    adrs = result.get("active_adrs", [])
    if adrs:
        console.print("\n[bold]Active ADRs:[/bold]")
        for a in adrs:
            console.print(f"  ADR-{a.get('a.number')}: {a.get('a.title')} [{a.get('a.status')}]")


@graph_app.command("verify")
def graph_verify(
    deep: bool = typer.Option(False, "--deep", help="Re-parse a sample of files for deep check."),
) -> None:
    """Spot-check graph accuracy against the filesystem."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.verify import (
        print_verification_report,
        verify_graph,
    )

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    report = verify_graph(store, Path.cwd(), deep=deep)
    store.close()
    print_verification_report(report)


@graph_app.command("prune")
def graph_prune(
    resolved_findings_before: str | None = typer.Option(
        None,
        "--resolved-findings-before",
        help="Prune resolved review findings (age spec like '30d'; findings have no"
        " timestamp, so all resolved findings are selected).",
    ),
    sessions_before: str | None = typer.Option(
        None,
        "--sessions-before",
        help="Prune sessions older than this age (e.g. '90d').",
    ),
    archived_backlog_before: str | None = typer.Option(
        None,
        "--archived-backlog-before",
        help="Prune archived backlog items older than this age (e.g. '90d').",
    ),
    malformed_findings: bool = typer.Option(
        False,
        "--malformed-findings",
        help="Prune plan-appendix findings whose body is a mid-sentence fragment "
        "(manufactured by the pre-0.9.7 unanchored extractor).",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Actually delete the selected rows. Without this flag, runs a dry run.",
    ),
) -> None:
    """Selectively prune old governance knowledge (dry-run by default).

    Only status-eligible rows are ever selected: resolved findings, archived
    backlog items, sessions past the cutoff, and malformed plan-appendix
    findings. Nothing is deleted unless --apply is given.
    """
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.prune import apply_prune, select_prunable

    if not any(
        [resolved_findings_before, sessions_before, archived_backlog_before, malformed_findings]
    ):
        console.print(
            "[yellow]Nothing to prune: specify at least one of "
            "--resolved-findings-before, --sessions-before, --archived-backlog-before, "
            "--malformed-findings.[/yellow]"
        )
        raise SystemExit(1)

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    try:
        try:
            selection = select_prunable(
                store,
                resolved_findings_before=resolved_findings_before,
                sessions_before=sessions_before,
                archived_backlog_before=archived_backlog_before,
                malformed_findings=malformed_findings,
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1) from exc

        totals = {k: len(v) for k, v in selection.items()}
        grand_total = sum(totals.values())

        console.print("[bold]Prune selection:[/bold]")
        console.print(f"  resolved findings: {totals['resolved_findings']}")
        console.print(f"  sessions:          {totals['sessions']}")
        console.print(f"  archived backlog:  {totals['archived_backlog']}")
        if resolved_findings_before is not None:
            console.print(
                "[dim]Note: ReviewFinding has no timestamp; all resolved findings are"
                " selected regardless of the age value.[/dim]"
            )

        if grand_total == 0:
            console.print("[green]Nothing eligible for pruning.[/green]")
            return

        if not apply:
            console.print(
                f"\n[yellow]Dry run: {grand_total} record(s) would be deleted. "
                "Re-run with --apply to delete.[/yellow]"
            )
            return

        counts = apply_prune(store, selection)
        deleted = sum(counts.values())
        console.print(f"\n[green]Pruned {deleted} record(s).[/green]")
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Review sub-commands (Dialectic Engine)
# ---------------------------------------------------------------------------


def _require_graph():
    """Load config, verify graph exists, return (config, store)."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)
    return config, open_graph(config)


@review_app.command("brief")
def review_brief(
    plan: int = typer.Argument(..., help="Plan number to generate brief for."),
) -> None:
    """Generate a pre-review brief from the knowledge graph."""
    from agentscaffold.review.brief import format_brief_markdown, generate_brief

    _config, store = _require_graph()
    brief = generate_brief(store, plan)
    store.close()
    console.print(format_brief_markdown(brief))


@review_app.command("challenges")
def review_challenges(
    plan: int = typer.Argument(..., help="Plan number to generate challenges for."),
    template: bool = typer.Option(
        False, "--template", help="Output full devil's advocate prompt with evidence."
    ),
) -> None:
    """Generate graph-evidence adversarial challenges for devil's advocate review."""
    config, store = _require_graph()

    if template:
        from agentscaffold.rendering import (
            get_default_context,
            get_review_context,
            render_template,
        )

        store.close()
        ctx = get_default_context(config)
        ctx.update(get_review_context(config, plan, review_type="challenges"))
        console.print(render_template("prompts/plan_critique.md.j2", ctx))
    else:
        from agentscaffold.review.challenges import (
            format_challenges_markdown,
            generate_challenges,
        )

        challenges = generate_challenges(store, plan)
        store.close()
        console.print(format_challenges_markdown(challenges))


@review_app.command("gaps")
def review_gaps(
    plan: int = typer.Argument(..., help="Plan number to analyze for gaps."),
    template: bool = typer.Option(
        False, "--template", help="Output full expansion prompt with evidence."
    ),
) -> None:
    """Generate graph-derived gap analysis for expansion review."""
    config, store = _require_graph()

    if template:
        from agentscaffold.rendering import (
            get_default_context,
            get_review_context,
            render_template,
        )

        store.close()
        ctx = get_default_context(config)
        ctx.update(get_review_context(config, plan, review_type="gaps"))
        console.print(render_template("prompts/plan_expansion.md.j2", ctx))
    else:
        from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps

        gaps = generate_gaps(store, plan)
        store.close()
        console.print(format_gaps_markdown(gaps))


@review_app.command("verify")
def review_verify_impl(
    plan: int = typer.Argument(..., help="Plan number to verify implementation for."),
) -> None:
    """Verify post-implementation compliance against a plan."""
    from agentscaffold.review.verify import (
        format_verification_markdown,
        verify_implementation,
    )

    _config, store = _require_graph()
    items = verify_implementation(store, plan)
    store.close()
    console.print(format_verification_markdown(items))


@review_app.command("retro")
def review_retro(
    plan: int = typer.Argument(..., help="Plan number to enrich retrospective for."),
    template: bool = typer.Option(
        False, "--template", help="Output full retrospective prompt with evidence."
    ),
) -> None:
    """Generate graph-enriched retrospective context."""
    config, store = _require_graph()

    if template:
        from agentscaffold.rendering import (
            get_default_context,
            get_review_context,
            render_template,
        )

        store.close()
        ctx = get_default_context(config)
        ctx.update(get_review_context(config, plan, review_type="retro"))
        console.print(render_template("prompts/retrospective.md.j2", ctx))
    else:
        from agentscaffold.review.feedback import (
            format_retro_markdown,
            generate_retro_enrichment,
        )

        insights = generate_retro_enrichment(store, plan)
        store.close()
        console.print(format_retro_markdown(insights))


@review_app.command("prepare")
def review_prepare(
    plan: int = typer.Argument(..., help="Plan number to prepare review for."),
) -> None:
    """Composite: full review context (brief + challenges + gaps + ADRs + studies)."""
    from agentscaffold.mcp.server import _tool_prepare_review

    config, store = _require_graph()
    root = Path.cwd()
    meta = {"source": "cli"}
    result = _tool_prepare_review(store, {"plan_number": plan}, meta, root, config)
    store.close()

    if "brief_markdown" in result:
        console.print(result["brief_markdown"])
    if "challenges_markdown" in result:
        console.print("\n" + result["challenges_markdown"])
    if "gaps_markdown" in result:
        console.print("\n" + result["gaps_markdown"])

    adrs = result.get("governing_adrs", [])
    if adrs:
        console.print("\n[bold]Governing ADRs:[/bold]")
        for a in adrs:
            console.print(f"  ADR-{a.get('a.number')}: {a.get('a.title')} ({a.get('a.status')})")

    spikes = result.get("validation_spikes", [])
    if spikes:
        console.print("\n[bold]Validation Spikes:[/bold]")
        for s in spikes:
            console.print(f"  {s.get('sp.title')} ({s.get('sp.status')})")

    studies = result.get("related_studies", [])
    if studies:
        console.print("\n[bold]Related Studies:[/bold]")
        for s in studies:
            console.print(f"  {s.get('s.studyId')}: {s.get('s.title')} -> {s.get('s.outcome')}")


@review_app.command("implement")
def review_implement(
    plan: int = typer.Argument(..., help="Plan number to prepare implementation for."),
) -> None:
    """Composite: implementation context (brief + blast radius + contracts + deps)."""
    import json

    from agentscaffold.mcp.server import _tool_prepare_implementation

    config, store = _require_graph()
    root = Path.cwd()
    meta = {"source": "cli"}
    result = _tool_prepare_implementation(store, {"plan_number": plan}, meta, root)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


@review_app.command("compare")
def review_compare(
    plan_a: int = typer.Argument(..., help="First plan number."),
    plan_b: int = typer.Argument(..., help="Second plan number."),
) -> None:
    """Composite: compare two plans for overlap and conflicts."""
    import json

    from agentscaffold.mcp.server import _tool_compare_plans

    _config, store = _require_graph()
    meta = {"source": "cli"}
    result = _tool_compare_plans(store, {"plan_a": plan_a, "plan_b": plan_b}, meta)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


@review_app.command("staleness")
def review_staleness(
    plan: int = typer.Argument(..., help="Plan number to check for staleness."),
) -> None:
    """Composite: check if a plan is stale."""
    import json

    from agentscaffold.mcp.server import _tool_staleness_check

    _config, store = _require_graph()
    meta = {"source": "cli"}
    result = _tool_staleness_check(store, {"plan_number": plan}, meta)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


@review_app.command("rewrite")
def review_rewrite(
    plan: int = typer.Argument(..., help="Plan number to prepare rewrite for."),
) -> None:
    """Composite: staleness check plus rewrite context."""
    import json

    from agentscaffold.mcp.server import _tool_prepare_rewrite

    _config, store = _require_graph()
    meta = {"source": "cli"}
    result = _tool_prepare_rewrite(store, {"plan_number": plan}, meta)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


@review_app.command("history")
def review_history(
    target: str = typer.Argument(..., help="File path or module name."),
) -> None:
    """Show all review findings and plan history for a file or module."""
    import json

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.review.queries import (
        get_findings_for_file,
        get_learnings_for_file,
        get_plans_impacting_file,
    )

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    plans = get_plans_impacting_file(store, target)
    learnings = get_learnings_for_file(store, target)
    findings = get_findings_for_file(store, target)
    store.close()

    console.print(
        json.dumps(
            {
                "file": target,
                "plans": plans,
                "learnings": learnings,
                "findings": findings,
            },
            indent=2,
            default=str,
        )
    )


# ---------------------------------------------------------------------------
# Session commands
# ---------------------------------------------------------------------------


@session_app.command("start")
def session_start(
    summary_arg: str = typer.Argument("", help="Session description (positional shorthand)."),
    plan: list[int] = typer.Option(
        [], "--plan", "-p", help="Plan number(s) to associate with this session."
    ),
    summary: str = typer.Option("", "--summary", "-s", help="Session description."),
) -> None:
    """Start a new coding session for cross-session memory."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.sessions import start_session

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    session_id = start_session(store, plan_numbers=plan, summary=summary or summary_arg)
    store.close()
    console.print(f"[green]Session started:[/green] {session_id}")
    console.print(f"  To end this session: [bold]scaffold session end {session_id}[/bold]")


@session_app.command("end")
def session_end(
    session_id: str = typer.Argument("", help="Session ID to finalize (omit to end most recent)."),
    summary: str = typer.Option("", "--summary", "-s", help="Final session summary."),
) -> None:
    """Finalize a coding session."""
    import json

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.sessions import end_session, list_sessions

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    if not session_id:
        sessions = list_sessions(store, limit=1)
        if not sessions:
            console.print("[red]No sessions found.[/red]")
            store.close()
            raise SystemExit(1)
        session_id = sessions[0].get("id", "")
        if not session_id:
            console.print("[red]Could not determine most recent session.[/red]")
            store.close()
            raise SystemExit(1)
    result = end_session(store, session_id, summary=summary)
    store.close()
    console.print(json.dumps(result, indent=2, default=str))


@session_app.command("list")
def session_list(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of sessions to show."),
) -> None:
    """List recent coding sessions."""
    from rich.table import Table

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.sessions import list_sessions

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    sessions = list_sessions(store, limit=limit)
    store.close()

    if not sessions:
        console.print("No sessions recorded.")
        return

    tbl = Table(title="Recent Sessions", show_header=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Date", style="green")
    tbl.add_column("Plans")
    tbl.add_column("Files", justify="right")
    tbl.add_column("Summary")

    for s in sessions:
        plans = ", ".join(str(p) for p in s.get("plan_numbers", []))
        files = s.get("files_modified", [])
        tbl.add_row(
            s.get("id", ""),
            s.get("date", "")[:19],
            plans or "-",
            str(len(files)),
            (s.get("summary", "") or "-")[:50],
        )

    console.print(tbl)


@session_app.command("context")
def session_context() -> None:
    """Show cross-session context for template injection."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.sessions import (
        format_session_context_markdown,
        get_session_context,
    )

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    ctx = get_session_context(store)
    store.close()

    if not ctx:
        console.print("No session history available.")
        return

    console.print(format_session_context_markdown(ctx))


# ---------------------------------------------------------------------------
# MCP server command
# ---------------------------------------------------------------------------


mcp_app = typer.Typer(
    help="MCP server: run it (bare `scaffold mcp`) or install its client entry.",
    invoke_without_command=True,
)
app.add_typer(mcp_app, name="mcp")


@mcp_app.callback(invoke_without_command=True)
def mcp_cmd(
    ctx: typer.Context,
    workspace: str = typer.Option(
        "",
        "--workspace",
        help=(
            "Workspace root to anchor MCP resolution (overrides launch cwd). "
            "Use when the IDE opens a parent folder instead of the project."
        ),
    ),
    project: str = typer.Option(
        "",
        "--project",
        help=(
            "Registered project name to resolve within the workspace. "
            "No-argument tools then read this project's governance."
        ),
    ),
    restrict_to: list[str] = typer.Option(
        [],
        "--restrict-to",
        help=(
            "Limit this server to the named projects. Repeat or comma-separate. "
            "Calls resolving elsewhere are refused with 'restricted_project'."
        ),
    ),
) -> None:
    """Start MCP server (stdio mode for Cursor/Claude).

    ``--workspace`` / ``--project`` (or the ``AGENTSCAFFOLD_WORKSPACE_ROOT`` /
    ``AGENTSCAFFOLD_PROJECT`` env vars) pin the resolution anchor so no-argument
    tools resolve the intended project even when the MCP process cwd is a parent
    directory.

    ``--restrict-to`` narrows the blast radius. One server process can read every
    registered project, so a user who wants a tighter boundary can bind it to an
    explicit allowlist; anything resolving outside is refused rather than served.

    This is a group callback so that ``scaffold mcp install`` can exist alongside
    it, but bare ``scaffold mcp`` still starts the server -- which is what every
    already-installed ``mcp.json`` entry invokes.
    """
    if ctx.invoked_subcommand is not None:
        return

    from agentscaffold.mcp.server import configure_restrict_to, run_mcp_server
    from agentscaffold.paths import configure_mcp_start

    configure_mcp_start(workspace=workspace or None, project=project or None)
    configure_restrict_to(restrict_to)
    run_mcp_server()


@mcp_app.command("install")
def mcp_install(
    config: str = typer.Option(
        "",
        "--config",
        help="Client MCP config to write (default: ~/.cursor/mcp.json).",
    ),
    migrate: bool = typer.Option(
        False,
        "--migrate",
        help="Also remove legacy per-project agentscaffold entries (backs up first).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change and write nothing."
    ),
) -> None:
    """Install the single AgentScaffold MCP server entry.

    One entry serves every registered project, so registering more projects adds
    no further entries. Existing per-project entries keep working and are only
    removed by an explicit ``--migrate``, which backs the file up first.

    ``mcp.json`` is shared with the user and with other tools, so an unrelated
    server entry is never modified: the resulting document is verified against
    the original before anything is written, and a config that cannot be parsed
    is refused outright rather than guessed at.
    """
    from agentscaffold.mcp.install import (
        CANONICAL_ENTRY_NAME,
        McpConfigError,
        backup_path,
        canonical_entry,
        default_config_path,
        load_config,
        plan_changes,
        render,
        verify_unrelated_preserved,
    )

    target = Path(config).expanduser() if config else default_config_path()

    try:
        original = load_config(target)
    except McpConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        import json as _json

        console.print("\nAdd this entry by hand:")
        console.print(
            _json.dumps({"mcpServers": {CANONICAL_ENTRY_NAME: canonical_entry()}}, indent=2)
        )
        raise SystemExit(1) from exc

    plan = plan_changes(original, migrate=migrate)

    try:
        verify_unrelated_preserved(original, plan.document)
    except McpConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    if plan.legacy and not migrate:
        console.print(
            f"[yellow]Legacy per-project entries still present: {', '.join(plan.legacy)}.[/yellow]"
        )
        console.print(
            "They keep working for now. Collapse them with "
            "[cyan]scaffold mcp install --migrate[/cyan]."
        )

    if not plan.changed:
        console.print(f"[green]No changes needed[/green] — {target} is already correct.")
        return

    if dry_run:
        console.print(f"[cyan]Dry run[/cyan] — would write {target}:")
        console.print(render(plan.document))
        if plan.removed:
            console.print(f"[yellow]Would remove: {', '.join(plan.removed)}[/yellow]")
        console.print("Nothing was written. Re-run without --dry-run to apply.")
        return

    if target.exists():
        backup = backup_path(target)
        backup.write_bytes(target.read_bytes())
        console.print(f"[dim]Backed up prior config to {backup}[/dim]")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(plan.document))

    console.print(f"[green]Installed the {CANONICAL_ENTRY_NAME!r} entry[/green] in {target}.")
    if plan.removed:
        console.print(f"[green]Removed legacy entries:[/green] {', '.join(plan.removed)}")
    console.print("Restart your MCP client to pick up the change.")


# ---------------------------------------------------------------------------
# Health checks and reclamation (Plan 249, Step B8)
# ---------------------------------------------------------------------------


_STATUS_STYLE = {
    "ok": ("[green]ok[/green]", "green"),
    "warn": ("[yellow]warn[/yellow]", "yellow"),
    "fail": ("[red]FAIL[/red]", "red"),
    "skip": ("[dim]skip[/dim]", "dim"),
    # Distinct from both ok and fail on purpose: another process holding the
    # graph is transient, and telling someone their tools are broken when an
    # index is running in the next terminal is how a diagnostic loses trust.
    "busy": ("[yellow]busy[/yellow]", "yellow"),
}


def _print_tool_probes(context: Any, include_writes: bool) -> bool:
    """Print the per-tool table. Returns True if any tool actually failed."""
    from agentscaffold.doctor_tools import probe_tools, summarize

    probes = probe_tools(context, include_writes=include_writes)
    console.print("\n[bold]MCP tools[/bold]")
    for probe in probes:
        label, _style = _STATUS_STYLE[probe.status]
        line = f"{label} {probe.name}"
        if probe.status != "skip" and probe.elapsed_ms:
            line += f" [dim]({probe.elapsed_ms:.0f} ms)[/dim]"
        console.print(line)
        if probe.detail and probe.status in {"fail", "busy"}:
            console.print(f"      [dim]{probe.detail}[/dim]", soft_wrap=True)

    counts = summarize(probes)
    console.print(
        "  ".join(f"{status}: {count}" for status, count in sorted(counts.items())),
        style="dim",
    )
    if not include_writes and counts.get("skip"):
        console.print(
            "[dim]Write tools were not exercised. "
            "Add --include-writes to probe them against a scratch project.[/dim]"
        )
    return bool(counts.get("fail"))


@app.command("doctor")
def doctor(
    project_root: str = typer.Option(
        "", "--project-root", help="Project to diagnose (default: current directory)."
    ),
    mcp_config: str = typer.Option(
        "", "--mcp-config", help="Client MCP config to inspect (default: ~/.cursor/mcp.json)."
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero if any check is not clean (for CI)."
    ),
    tools: bool = typer.Option(
        False, "--tools", help="Also call every MCP tool and report how each behaved."
    ),
    include_writes: bool = typer.Option(
        False,
        "--include-writes",
        help="With --tools, also exercise write tools against a scratch project.",
    ),
) -> None:
    """Diagnose an AgentScaffold installation. Reads only; changes nothing.

    The default exit code is always 0, so this is safe in a shell profile or a
    git hook. ``--strict`` is the CI gate.
    """
    from agentscaffold.doctor import (
        DoctorContext,
        default_mcp_config_path,
        run_checks,
        worst_status,
    )

    context = DoctorContext(
        project_root=Path(project_root).expanduser() if project_root else Path.cwd(),
        mcp_config_path=Path(mcp_config).expanduser() if mcp_config else default_mcp_config_path(),
    )

    results = run_checks(context)
    for check, result in results:
        label, _style = _STATUS_STYLE[result.status]
        console.print(f"{label} [bold]{check.title}[/bold] — {result.summary}")
        for detail in result.details:
            # Details carry paths and ids. Wrapping one mid-token makes it
            # unusable for the copy-paste it exists to enable.
            console.print(f"      [dim]{detail}[/dim]", soft_wrap=True)
        if result.remediation and result.status in {"warn", "fail"}:
            console.print(f"      [cyan]{result.remediation}[/cyan]")

    tools_failed = _print_tool_probes(context, include_writes) if tools else False

    worst = worst_status(results)
    if tools_failed and strict:
        raise SystemExit(1)
    if worst in {"warn", "fail"}:
        console.print(
            "\nRun [cyan]scaffold doctor --strict[/cyan] in CI to make these block a build."
            if not strict
            else ""
        )
        if strict:
            raise SystemExit(1)
    else:
        console.print("\n[green]Everything checks out.[/green]")


@app.command("gc")
def gc(
    apply: bool = typer.Option(
        False, "--apply", help="Actually delete. Without this, gc only reports."
    ),
) -> None:
    """Reclaim state left behind by workspaces that no longer exist.

    Removes only what it can prove is orphaned: a state directory whose recorded
    workspace root is gone or now resolves to a different id, and registry
    entries pointing at roots that no longer exist. A state directory with no
    record of where it came from is reported and kept -- an unnecessary
    directory costs disk space, a wrongly deleted one costs a full re-index.
    """
    from agentscaffold.gc import apply_gc, plan_gc

    plan = plan_gc()

    for directory, reason in plan.orphaned_state:
        console.print(f"[yellow]orphaned state[/yellow] {directory.name} — {reason}")
        console.print(f"      [dim]{directory}[/dim]", soft_wrap=True)
    for workspace_id, root in plan.stale_registry:
        console.print(
            f"[yellow]stale registry entry[/yellow] {workspace_id} — {root} is gone",
            soft_wrap=True,
        )
    for directory in plan.unverifiable_state:
        console.print(
            f"[dim]kept[/dim] {directory.name} — no record of its workspace, so it is not "
            "provably orphaned"
        )

    if not plan.has_work:
        console.print("[green]Nothing to reclaim.[/green]")
        return

    if not apply:
        console.print("\nNothing was deleted. Re-run with [cyan]--apply[/cyan] to reclaim these.")
        return

    apply_gc(plan)
    console.print(
        f"\n[green]Reclaimed[/green] {len(plan.orphaned_state)} state directory(ies) "
        f"and {len(plan.stale_registry)} registry entry(ies)."
    )


# ---------------------------------------------------------------------------
# Project registration commands (Plan 249)
# ---------------------------------------------------------------------------


@project_app.command("register")
def project_register(
    root: str = typer.Argument(..., help="Project or workspace root directory to register."),
    name: str = typer.Option(
        "", "--name", help="Project name (defaults to the directory basename)."
    ),
) -> None:
    """Record a root in the user-level registry so one MCP server can resolve it.

    This writes the registry and nothing else. In particular it does not touch
    any client's ``mcp.json``: installing the server entry is a separate command
    so that widening what a server can read is never a side effect of onboarding
    a project (threat model, Vector 1).
    """
    from agentscaffold.workspace_registry import RegistryError, register_workspace

    target = Path(root).expanduser()
    if not target.is_dir():
        console.print(f"[red]Not a directory: {target}[/red]")
        raise SystemExit(1)

    try:
        entry = register_workspace(target, name=name or None)
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    registered = ", ".join(p.name for p in entry.projects)
    console.print(f"[green]Registered {registered!r} at {entry.root}.[/green]")
    console.print("Run [cyan]scaffold mcp install[/cyan] if the MCP server is not yet installed.")


@project_app.command("unregister")
def project_unregister(
    name: str = typer.Argument(..., help="Registered project name to forget."),
) -> None:
    """Forget a registered project.

    Only the registry entry is removed -- never the project directory. Removing
    something absent reports the fact but succeeds, so teardown scripts can run
    this blind without special-casing.
    """
    from agentscaffold.workspace_registry import RegistryError, unregister_project

    try:
        removed = unregister_project(name)
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    if removed:
        console.print(f"[green]Unregistered {name!r}.[/green]")
    else:
        console.print(f"[yellow]No registered project named {name!r}; nothing to do.[/yellow]")


@project_app.command("list")
def project_list() -> None:
    """List every registered project and the root it resolves to.

    This is the server's entire read surface, so it is worth being able to see
    at a glance (threat model, Vector 1).
    """
    from rich.table import Table

    from agentscaffold.workspace_registry import RegistryError, load_registry, registry_path

    try:
        registry = load_registry()
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    if not registry.workspaces:
        console.print("[yellow]No projects registered.[/yellow]")
        console.print(
            "Register one with [cyan]scaffold project register <path>[/cyan]. "
            "A lone repo does not need to be registered."
        )
        return

    tbl = Table(title=f"Registered projects ({registry_path()})", show_header=True)
    tbl.add_column("Project", style="green")
    tbl.add_column("Root")
    tbl.add_column("Workspace ID", style="dim")
    for workspace in registry.workspaces:
        for entry in workspace.projects:
            tbl.add_row(entry.name, str(workspace.project_root(entry)), workspace.id)
    console.print(tbl)


# ---------------------------------------------------------------------------
# Workspace commands (Plan 225)
# ---------------------------------------------------------------------------


@workspace_app.command("list")
def workspace_list() -> None:
    """List the projects in the current workspace.

    A lone repo with no ``workspace.yaml`` shows a single synthesized project
    (its directory basename), so the command always works.
    """
    from rich.table import Table

    from agentscaffold.paths import load_workspace, resolve_workspace_root

    ws = load_workspace()
    root = resolve_workspace_root()
    mode = "multi-project" if ws.is_multi_project else "single-project"
    tbl = Table(title=f"Workspace ({mode}) at {root}", show_header=True)
    tbl.add_column("Project", style="green")
    tbl.add_column("Path")
    for entry in ws.projects:
        tbl.add_row(entry.name, entry.path)
    console.print(tbl)


@workspace_app.command("onboard")
def workspace_onboard(
    path: str = typer.Argument(..., help="Project directory to register (relative to cwd)."),
    name: str = typer.Option("", "--name", help="Project name (defaults to directory basename)."),
    migrate_existing: str = typer.Option(
        "",
        "--migrate-existing",
        help=(
            "Re-key the existing shared graph cache in place into the named project "
            "(the single->multi flip). Destructive; prefer re-indexing if unsure."
        ),
    ),
    shared_layout: bool = typer.Option(
        False,
        "--shared-layout",
        help=(
            "Write asset_layout: shared_workspace into workspace.yaml so reusable "
            "process assets are shared at the workspace root."
        ),
    ),
) -> None:
    """Register a project into the workspace manifest (creating it if needed).

    The manifest lives at the workspace root (cwd, or the nearest existing
    ``workspace.yaml``). Once a second project is registered the workspace
    becomes multi-project: every node is ID-prefixed by project and reads scope
    to the current project. An existing single-project cache can be re-keyed in
    place with ``--migrate-existing NAME`` (atomic); otherwise re-index.
    """
    import yaml

    from agentscaffold.config import (
        ProjectEntry,
        WorkspaceConfig,
        derive_project_name,
        find_workspace_config,
        load_workspace_manifest,
        validate_workspace,
    )

    cwd = Path.cwd().resolve()
    ws_path = find_workspace_config(cwd)
    ws_root = ws_path.parent.resolve() if ws_path is not None else cwd
    manifest_path = ws_path if ws_path is not None else (ws_root / "workspace.yaml")

    workspace = load_workspace_manifest(manifest_path) if ws_path is not None else WorkspaceConfig()

    project_dir = (cwd / path).resolve()
    if not project_dir.is_dir():
        console.print(f"[red]Project directory not found: {project_dir}[/red]")
        raise SystemExit(1)

    try:
        proj_name = derive_project_name(project_dir, explicit=name or None)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    if workspace.find_by_name(proj_name) is not None:
        console.print(f"[yellow]Project {proj_name!r} is already registered.[/yellow]")
        raise SystemExit(0)

    # Store the path relative to the workspace root when possible (portable).
    try:
        rel = project_dir.relative_to(ws_root)
        stored_path = str(rel)
    except ValueError:
        stored_path = str(project_dir)

    workspace.projects.append(ProjectEntry(name=proj_name, path=stored_path))
    try:
        validate_workspace(workspace)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    # Generate the workspace id on first write and never regenerate it: it keys
    # this workspace's state directory, so a new id would orphan the graph
    # (ADR-025, which is also why it is opaque rather than derived from the path).
    # An already-registered root adopts the id the registry gave it, because that
    # is the id its existing state is keyed to -- minting a fresh one here is the
    # dangerous direction, and the reason the id is adopted rather than assigned.
    if not workspace.id:
        from agentscaffold.workspace_ids import generate_workspace_id

        registered_id = None
        try:
            from agentscaffold.workspace_registry import load_registry

            existing_entry = load_registry().find_workspace_by_root(ws_root)
            registered_id = existing_entry.id if existing_entry is not None else None
        except Exception:
            registered_id = None

        workspace.id = registered_id or generate_workspace_id()

    manifest_out: dict = {
        "id": workspace.id,
        "projects": [{"name": p.name, "path": p.path} for p in workspace.projects],
    }
    existing_layout = workspace.asset_layout
    if shared_layout:
        from agentscaffold.config import AssetLayoutConfig

        manifest_out["asset_layout"] = AssetLayoutConfig(layout="shared_workspace").model_dump()
    elif existing_layout is not None:
        manifest_out["asset_layout"] = existing_layout.model_dump()
    manifest_path.write_text(yaml.safe_dump(manifest_out, sort_keys=False))

    # Mirror the manifest into the user-level registry so the single project-aware
    # MCP server can resolve these projects (Plan 249). Onboarding is an explicit
    # user action, which is the only context in which registration may happen
    # (threat model, Vector 1). A registry failure must not lose the manifest that
    # was just written, so it degrades to a warning.
    try:
        from agentscaffold.workspace_registry import register_workspace

        register_workspace(
            ws_root,
            projects=[(p.name, p.path) for p in workspace.projects],
        )
    except Exception as exc:  # noqa: BLE001 - manifest is written; this is advisory
        console.print(f"[yellow]Manifest written, but registry update failed: {exc}[/yellow]")
        console.print("Run [cyan]scaffold project register[/cyan] to retry.")

    console.print(f"[green]Registered project {proj_name!r} at {stored_path}.[/green]")
    if shared_layout:
        console.print("[cyan]Wrote asset_layout: shared_workspace.[/cyan]")
    console.print(f"Workspace manifest: {manifest_path}")
    if workspace.is_multi_project:
        console.print("[cyan]Workspace is now multi-project.[/cyan]")

    if migrate_existing:
        _onboard_migrate(ws_root, migrate_existing)


@workspace_app.command("migrate-state")
def workspace_migrate_state_cmd(
    apply: bool = typer.Option(
        False, "--apply", help="Apply the migration (default is a non-mutating dry-run)."
    ),
    restore: bool = typer.Option(
        False, "--restore", help="Move state back into the tree (the rollback path)."
    ),
) -> None:
    """Move this workspace's graph state out of the source tree.

    Relocates the graph database and the files beside it to the platform state
    directory, keyed by workspace id, by copying, verifying, and only then
    removing the original. Refuses to start while another process holds the
    database. Default posture is a non-mutating dry-run; pass ``--apply``.
    """
    from agentscaffold.workspace_migrate_state import StateMigrationError, migrate_state

    try:
        result = migrate_state(apply=apply, restore=restore)
    except StateMigrationError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    if not result.needed:
        console.print(f"[dim]{result.reason}[/dim]")
        return

    if result.applied:
        console.print(
            f"[green]Moved[/green] {result.source}\n     [green]to[/green] {result.destination}"
        )
        for path in result.copied[1:]:
            console.print(f"[dim]  also moved {path.name}[/dim]")
    else:
        console.print(f"[yellow]dry-run[/yellow] {result.reason}")
        console.print("[dim]Re-run with --apply to perform the move.[/dim]")


@workspace_app.command("migrate-layout")
def workspace_migrate_layout(
    apply: bool = typer.Option(
        False, "--apply", help="Apply the migration (default is a non-mutating dry-run)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Explicitly request the dry-run report (the default)."
    ),
    prefer_project: str = typer.Option(
        "", "--prefer-project", help="For diverged files, promote this project's copy."
    ),
    keep_diverged: bool = typer.Option(
        False, "--keep-diverged", help="Leave diverged files as project-local (do not promote)."
    ),
    force: bool = typer.Option(False, "--force", help="Allow --apply on a dirty git worktree."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the machine-readable report as JSON."
    ),
) -> None:
    """Migrate a multi-project workspace to the shared asset layout.

    Promotes duplicated reusable process assets (prompts, standards, templates,
    protocol, commands, shared security templates) to the workspace root and
    writes ``asset_layout: shared_workspace``. Project system-of-record artifacts
    (plans, ADRs, contracts, state, backlog, architecture) are never moved.
    Default posture is a non-mutating dry-run; pass ``--apply`` to mutate.
    """
    import json as _json

    from agentscaffold.workspace_migrate import run_migrate_layout

    if apply and dry_run:
        console.print("[red]Pass only one of --apply / --dry-run.[/red]")
        raise SystemExit(1)

    report = run_migrate_layout(
        apply=apply,
        prefer_project=prefer_project or None,
        keep_diverged=keep_diverged,
        force=force,
    )

    if json_output:
        console.print_json(_json.dumps(report.to_dict()))
    else:
        for msg in report.messages:
            console.print(msg)
        if report.diverged and not apply:
            console.print("\n[yellow]Diverged process assets:[/yellow]")
            for c in report.diverged:
                console.print(f"  {c.rel_path} (differs across: {', '.join(c.projects)})")
        if report.promoted:
            console.print(f"[green]Promoted:[/green] {len(report.promoted)} file(s).")

    if report.exit_code != 0:
        raise SystemExit(report.exit_code)


def _onboard_migrate(ws_root: Path, project: str) -> None:
    """Atomically re-key the shared cache at *ws_root* into *project* + verify."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        console.print(
            "[yellow]No shared graph cache to migrate; run 'scaffold index' "
            "from each project instead.[/yellow]"
        )
        return
    store = open_graph(config)
    try:
        counts = store.migrate_to_multi_project(project)
        problems = store.verify_integrity()
    finally:
        store.close()
    console.print(
        f"[green]Re-keyed graph into {project!r}: "
        f"{counts['nodes']} nodes, {counts['edges']} edges, "
        f"{counts['embeddings']} embeddings.[/green]"
    )
    if problems:
        console.print(f"[red]Integrity check found {len(problems)} issue(s):[/red]")
        for p in problems[:10]:
            console.print(f"  - {p}")
        raise SystemExit(1)
    console.print("[green]Integrity check passed.[/green]")
