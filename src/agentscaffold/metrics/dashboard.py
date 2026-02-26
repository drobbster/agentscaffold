"""Metrics dashboard and reporting."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentscaffold.config import load_config

console = Console()

PLAN_FILENAME_RE = re.compile(r"^(\d{3})-(.+)\.md$")
CHECKBOX_TOTAL_RE = re.compile(r"^-\s+\[[ xX]\]\s+", re.MULTILINE)
CHECKBOX_DONE_RE = re.compile(r"^-\s+\[[xX]\]\s+", re.MULTILINE)
RETRO_HEADING_RE = re.compile(r"^##\s+.*[Rr]etrospective", re.MULTILINE)
TEST_REF_RE = re.compile(r"tests?/", re.IGNORECASE)
TYPE_BUGFIX_RE = re.compile(r"bugfix|bug.fix", re.IGNORECASE)
TYPE_REFACTOR_RE = re.compile(r"refactor", re.IGNORECASE)


def _infer_status(total: int, done: int) -> str:
    if total == 0:
        return "Draft"
    if done == total:
        return "Complete"
    if done > 0:
        return "In Progress"
    return "Ready"


def _infer_type(text: str) -> str:
    """Detect plan type from metadata or content heuristics."""
    first_block = text[:600]
    if TYPE_BUGFIX_RE.search(first_block):
        return "bugfix"
    if TYPE_REFACTOR_RE.search(first_block):
        return "refactor"
    return "feature"


def _status_style(status: str) -> str:
    return {
        "Complete": "[green]Complete[/green]",
        "In Progress": "[yellow]In Progress[/yellow]",
        "Ready": "[cyan]Ready[/cyan]",
        "Draft": "[dim]Draft[/dim]",
    }.get(status, status)


def run_metrics() -> None:
    """Run metrics dashboard and display results."""
    load_config()
    plans_dir = Path("docs/ai/plans")

    if not plans_dir.is_dir():
        console.print(f"[yellow]Warning: {plans_dir} does not exist.[/yellow]")
        return

    plan_files = sorted(plans_dir.glob("*.md"))
    if not plan_files:
        console.print("[yellow]No plan files found.[/yellow]")
        return

    table = Table(title="Plan Metrics Dashboard")
    table.add_column("Plan", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Type", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Steps", justify="right")
    table.add_column("Retro", justify="center")
    table.add_column("Tests", justify="center")

    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    retro_count = 0
    test_count = 0
    total_steps = 0
    plans_with_steps = 0

    for pf in plan_files:
        m = PLAN_FILENAME_RE.match(pf.name)
        if not m:
            continue

        plan_num = m.group(1)
        title = m.group(2).replace("-", " ").title()
        text = pf.read_text()

        total = len(CHECKBOX_TOTAL_RE.findall(text))
        done = len(CHECKBOX_DONE_RE.findall(text))
        status = _infer_status(total, done)
        plan_type = _infer_type(text)
        has_retro = bool(RETRO_HEADING_RE.search(text))
        has_tests = bool(TEST_REF_RE.search(text))

        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[plan_type] = type_counts.get(plan_type, 0) + 1
        if has_retro:
            retro_count += 1
        if has_tests:
            test_count += 1
        if total > 0:
            total_steps += total
            plans_with_steps += 1

        retro_mark = "[green]yes[/green]" if has_retro else "[dim]no[/dim]"
        test_mark = "[green]yes[/green]" if has_tests else "[dim]no[/dim]"
        table.add_row(
            plan_num,
            title,
            plan_type,
            _status_style(status),
            f"{done}/{total}",
            retro_mark,
            test_mark,
        )

    console.print(table)

    total_plans = sum(status_counts.values())
    avg_steps = total_steps / plans_with_steps if plans_with_steps else 0

    lines = [
        f"Total plans: {total_plans}",
        "  ".join(f"{s}: {n}" for s, n in sorted(status_counts.items())),
        "",
        "By type:  " + "  ".join(f"{t}: {n}" for t, n in sorted(type_counts.items())),
        f"Average steps per plan: {avg_steps:.1f}",
        f"With retrospective: {retro_count}/{total_plans}",
        f"With test references: {test_count}/{total_plans}",
    ]

    console.print(Panel("\n".join(lines), title="Summary"))
