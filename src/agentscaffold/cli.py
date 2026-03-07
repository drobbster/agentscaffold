"""Main CLI entry point for AgentScaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

session_app = typer.Typer(help="Cross-session memory management.")
app.add_typer(session_app, name="session")


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
    """Generate .cursor/rules.md and intent mapping from config."""
    from agentscaffold.agents.cursor import run_cursor_setup

    run_cursor_setup()


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


@graph_app.command("search")
def graph_search(
    query: str = typer.Argument(..., help="Natural language search query."),
    mode: str = typer.Option(
        "hybrid", "--mode", "-m", help="Search mode: cypher, semantic, hybrid."
    ),
    top_k: int = typer.Option(10, "--top", "-k", help="Number of results."),
    table: str = typer.Option(
        "", "--table", "-t", help="Limit to specific table (Function, Class, Method, File)."
    ),
) -> None:
    """Search the knowledge graph using natural language."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.search import format_search_results, hybrid_search

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found. Run 'scaffold index' first.[/red]")
        raise SystemExit(1)

    store = open_graph(config)

    if mode in ("semantic", "hybrid"):
        from agentscaffold.graph.embeddings import _st_available, embeddings_available

        if not _st_available:
            console.print(
                "[yellow]Warning: sentence-transformers not installed. "
                "Falling back to keyword search only.[/yellow]\n"
                "[dim]Install with: pip install agentscaffold[search][/dim]\n"
            )
            mode = "cypher"
        elif not embeddings_available(store):
            console.print(
                "[yellow]Warning: No embeddings found in graph. "
                "Falling back to keyword search only.[/yellow]\n"
                "[dim]Generate embeddings with: scaffold index --embeddings[/dim]\n"
            )
            mode = "cypher"

    tables = [table] if table else None
    results = hybrid_search(store, query, mode=mode, top_k=top_k, tables=tables)
    store.close()
    console.print(format_search_results(results))


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
    session_id = start_session(store, plan_numbers=plan, summary=summary)
    store.close()
    console.print(f"[green]Session started:[/green] {session_id}")
    console.print(f"  To end this session: [bold]scaffold session end {session_id}[/bold]")


@session_app.command("end")
def session_end(
    session_id: str = typer.Argument(..., help="Session ID to finalize."),
    summary: str = typer.Option("", "--summary", "-s", help="Final session summary."),
) -> None:
    """Finalize a coding session."""
    import json

    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.sessions import end_session

    config = load_config()
    if not graph_available(config):
        console.print("[red]No knowledge graph found.[/red]")
        raise SystemExit(1)

    store = open_graph(config)
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


@app.command(name="mcp")
def mcp_cmd() -> None:
    """Start MCP server (stdio mode for Cursor/Claude)."""
    from agentscaffold.mcp.server import run_mcp_server

    run_mcp_server()
