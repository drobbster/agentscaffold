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
