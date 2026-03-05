"""Main CLI entry point for AgentScaffold."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from agentscaffold import __version__

app = typer.Typer(
    name="scaffold",
    help="AgentScaffold -- structured AI-assisted development framework.",
    no_args_is_help=True,
)
console = Console()

# ---------------------------------------------------------------------------
# Sub-command groups
# ---------------------------------------------------------------------------

plan_app = typer.Typer(help="Plan lifecycle management.")
app.add_typer(plan_app, name="plan")

study_app = typer.Typer(help="Study (experiment / A-B test) management.")
app.add_typer(study_app, name="study")

spike_app = typer.Typer(help="Time-boxed research spike management.")
app.add_typer(spike_app, name="spike")

domain_app = typer.Typer(help="Domain pack management.")
app.add_typer(domain_app, name="domain")

agents_app = typer.Typer(help="Agent integration file generation.")
app.add_typer(agents_app, name="agents")

graph_app = typer.Typer(help="Knowledge graph operations.")
app.add_typer(graph_app, name="graph")

review_app = typer.Typer(help="Graph-powered review generation.")
app.add_typer(review_app, name="review")


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
) -> None:
    """Scaffold a new project with the AgentScaffold framework."""
    from agentscaffold.init_cmd import run_init

    run_init(directory=directory, non_interactive=non_interactive)


@app.command()
def validate(
    check_safety_boundaries: bool = typer.Option(
        False, "--check-safety-boundaries", help="Verify no read-only files were modified."
    ),
    check_session_summary: bool = typer.Option(
        False, "--check-session-summary", help="Verify session summary exists for agent PRs."
    ),
) -> None:
    """Run all enforcement checks (lint, integration, retros, prohibitions, secrets)."""
    from agentscaffold.validate.orchestrator import run_validate

    run_validate(
        check_safety_boundaries=check_safety_boundaries,
        check_session_summary=check_session_summary,
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
        "auto", "--format", "-f", help="Format: auto, chatgpt, claude, markdown."
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


@app.command()
def version() -> None:
    """Show AgentScaffold version."""
    console.print(f"agentscaffold {__version__}")


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


# ---------------------------------------------------------------------------
# Domain sub-commands
# ---------------------------------------------------------------------------


@domain_app.command("add")
def domain_add(
    pack: str = typer.Argument(..., help="Domain pack name (e.g., trading, webapp, mlops)."),
) -> None:
    """Install a domain pack's templates and standards."""
    from agentscaffold.domain.loader import run_domain_add

    run_domain_add(pack=pack)


@domain_app.command("list")
def domain_list() -> None:
    """List available and installed domain packs."""
    from agentscaffold.domain.registry import run_domain_list

    run_domain_list()


# ---------------------------------------------------------------------------
# Agents sub-commands
# ---------------------------------------------------------------------------


@agents_app.command("generate")
def agents_generate() -> None:
    """Generate AGENTS.md from scaffold.yaml config."""
    from agentscaffold.agents.generate import run_agents_generate

    run_agents_generate()


@agents_app.command("cursor")
def agents_cursor() -> None:
    """Generate .cursor/rules.md from config."""
    from agentscaffold.agents.cursor import run_cursor_setup

    run_cursor_setup()


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
) -> None:
    """Build or rebuild the knowledge graph."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import index

    config = load_config()
    index(
        path=path,
        config=config,
        incremental=incremental,
        embeddings=with_embeddings,
        audit=audit,
    )


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
    table.add_row("Review findings", str(stats["review_findings"]))
    table.add_row("Parsing warnings", str(stats["parsing_warnings"]))

    console.print(table)


@graph_app.command("query")
def graph_query(
    cypher: str = typer.Argument(..., help="Cypher query to execute."),
) -> None:
    """Execute a raw Cypher query against the graph."""
    import json

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    try:
        results = store.query(cypher)
        console.print(json.dumps(results, indent=2, default=str))
    except Exception as exc:
        console.print(f"[red]Query error: {exc}[/red]")
        raise SystemExit(1) from exc
    finally:
        store.close()


@graph_app.command("verify")
def graph_verify(
    deep: bool = typer.Option(False, "--deep", help="Re-parse a sample of files for deep check."),
) -> None:
    """Spot-check graph accuracy against the filesystem."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.verify import print_verification_report, verify_graph

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
    report = verify_graph(store, Path.cwd(), deep=deep)
    store.close()
    print_verification_report(report)


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
# MCP server command
# ---------------------------------------------------------------------------


@app.command(name="mcp")
def mcp_cmd() -> None:
    """Start MCP server (stdio mode for Cursor/Claude)."""
    from agentscaffold.mcp.server import run_mcp_server

    run_mcp_server()
