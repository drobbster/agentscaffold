"""Validation orchestrator for integration, prohibitions, secrets, and safety."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

from agentscaffold.config import load_config

console = Console()


def run_validate(
    check_safety_boundaries: bool = False,
    check_session_summary: bool = False,
) -> None:
    """Run validation checks (integration, prohibitions, secrets, optionally safety)."""
    from agentscaffold.validate.integration import check_integration
    from agentscaffold.validate.prohibitions import check_prohibitions
    from agentscaffold.validate.safety import check_safety_boundaries as _check_safety
    from agentscaffold.validate.secrets import check_secrets

    config = load_config()
    results: list[tuple[str, list[str]]] = []

    console.print("\n[bold]Running validation checks...[/bold]\n")

    # Plan lint (best-effort, calls the plan lint module)
    plan_issues: list[str] = []
    try:
        from agentscaffold.plan.lint import run_plan_lint

        run_plan_lint(plan=None)
    except Exception as exc:  # noqa: BLE001
        plan_issues.append(f"Plan lint error: {exc}")
    results.append(("Plan Lint", plan_issues))

    # Integration check
    integration_issues = check_integration()
    results.append(("Integration", integration_issues))

    # Prohibitions check
    prohibitions_issues = check_prohibitions(config=config)
    results.append(("Prohibitions", prohibitions_issues))

    # Secrets check
    secrets_issues = check_secrets()
    results.append(("Secrets", secrets_issues))

    # Retrospective check (if enabled in config gates)
    if config.gates.in_progress_to_complete.retrospective:
        retro_issues: list[str] = []
        try:
            from agentscaffold.retro.check import run_retro_check

            run_retro_check()
        except Exception as exc:  # noqa: BLE001
            retro_issues.append(f"Retrospective check error: {exc}")
        results.append(("Retrospectives", retro_issues))

    # Safety boundary check (opt-in via flag)
    if check_safety_boundaries:
        safety_issues = _check_safety(config=config)
        results.append(("Safety Boundaries", safety_issues))

    # Session summary check (opt-in via flag)
    if check_session_summary:
        session_issues: list[str] = []
        session_issues.append("Session summary check not yet implemented")
        results.append(("Session Summary", session_issues))

    # Display summary table
    table = Table(title="Validation Results")
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Issues", justify="right")

    has_failures = False
    for name, issues in results:
        if issues:
            has_failures = True
            table.add_row(name, "[red]FAIL[/red]", str(len(issues)))
        else:
            table.add_row(name, "[green]PASS[/green]", "0")

    console.print(table)

    # Print details for failures
    if has_failures:
        console.print("\n[bold red]Validation failures:[/bold red]\n")
        for name, issues in results:
            if not issues:
                continue
            console.print(f"[bold]{name}:[/bold]")
            for issue in issues:
                console.print(f"  - {issue}")
            console.print()
        sys.exit(1)
    else:
        console.print("\n[bold green]All validation checks passed.[/bold green]\n")
