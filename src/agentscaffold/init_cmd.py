"""Project initialization command."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentscaffold.config import CONFIG_FILENAME, load_config
from agentscaffold.rendering import get_default_context, render_template, write_if_missing

console = Console()

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


def _write_scaffold_yaml(directory: Path, options: dict[str, object]) -> bool:
    """Render and write scaffold.yaml. Returns True if written."""
    dest = directory / CONFIG_FILENAME
    if dest.exists():
        console.print(f"[dim]  skip (exists)[/dim] {CONFIG_FILENAME}")
        return False

    content = render_template("scaffold_yaml.yaml.j2", options)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    return True


def _write_templated_files(directory: Path, context: dict) -> tuple[int, int]:  # type: ignore[type-arg]
    """Render all templates and write them. Returns (written, skipped) counts."""
    written = 0
    skipped = 0
    for tpl_path, out_rel in _TEMPLATE_MAP.items():
        dest = directory / out_rel
        try:
            content = render_template(tpl_path, context)
        except Exception as exc:
            console.print(f"[red]  error rendering {tpl_path}: {exc}[/red]")
            skipped += 1
            continue

        if write_if_missing(dest, content):
            written += 1
        else:
            skipped += 1
    return written, skipped


def _create_empty_dirs(directory: Path) -> int:
    """Ensure empty scaffold directories exist. Returns count created."""
    created = 0
    for rel in _EMPTY_DIRS:
        d = directory / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created += 1
    return created


def _write_agents_md(directory: Path, context: dict) -> bool:  # type: ignore[type-arg]
    """Write AGENTS.md at the project root."""
    dest = directory / "AGENTS.md"
    content = render_template("agents/agents_md.md.j2", context)
    return write_if_missing(dest, content)


def _write_cursor_rules(directory: Path, context: dict) -> bool:  # type: ignore[type-arg]
    """Write .cursor/rules.md."""
    dest = directory / ".cursor" / "rules.md"
    content = render_template("agents/cursor_rules.md.j2", context)
    return write_if_missing(dest, content)


def _write_session_dir(directory: Path, semi_autonomous: bool) -> bool:
    """Create sessions directory if semi-autonomous is enabled."""
    if not semi_autonomous:
        return False
    sessions = directory / "docs" / "ai" / "state" / "sessions"
    if sessions.exists():
        return False
    sessions.mkdir(parents=True, exist_ok=True)
    return True


def _write_empty_readmes(directory: Path) -> int:
    """Write minimal README.md files in empty scaffold directories."""
    count = 0
    stubs: dict[str, str] = {
        "docs/runbook/README.md": "# Runbook\n\nOperational documentation.\n",
        "docs/studies/README.md": "# Studies\n\nExperiment and A/B test documentation.\n",
    }
    for rel, content in stubs.items():
        if write_if_missing(directory / rel, content):
            count += 1
    return count


def _print_summary(
    directory: Path,
    options: dict[str, object],
    written: int,
    skipped: int,
    dirs_created: int,
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

    console.print()
    console.print(table)
    console.print()
    console.print("[green]Initialization complete.[/green]")
    console.print("Next steps:")
    console.print("  1. Review scaffold.yaml and adjust settings")
    console.print("  2. Edit docs/ai/system_architecture.md to define your layers")
    console.print("  3. Run [bold]scaffold agents generate[/bold] to regenerate AGENTS.md")
    console.print("  4. Run [bold]scaffold agents cursor[/bold] to regenerate .cursor/rules.md")
    console.print(
        "  5. Run [bold]scaffold index[/bold] to build the knowledge graph"
        " (enables search, reviews, and session memory)"
    )


def run_init(directory: Path, non_interactive: bool = False) -> None:
    """Initialize a new project in the given directory."""
    directory = directory.resolve()
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)

    options = _gather_options(directory, non_interactive)

    yaml_written = _write_scaffold_yaml(directory, options)

    config = load_config(directory / CONFIG_FILENAME)

    context = get_default_context(config)
    context.update(
        {
            "profile": options["profile"],
            "rigor": options["rigor"],
        }
    )

    written, skipped = _write_templated_files(directory, context)
    dirs_created = _create_empty_dirs(directory)

    if _write_agents_md(directory, context):
        written += 1
    else:
        skipped += 1

    if _write_cursor_rules(directory, context):
        written += 1
    else:
        skipped += 1

    semi_auto = options.get("profile") == "semi_autonomous"
    if _write_session_dir(directory, semi_auto):
        dirs_created += 1

    readme_count = _write_empty_readmes(directory)
    written += readme_count

    if yaml_written:
        written += 1

    _print_summary(directory, options, written, skipped, dirs_created)
