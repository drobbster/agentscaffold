"""Retrospective check and verification."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

PLAN_FILENAME_RE = re.compile(r"^(\d{3})-(.+)\.md$")
CHECKBOX_TOTAL_RE = re.compile(r"^-\s+\[[ xX]\]\s+", re.MULTILINE)
CHECKBOX_DONE_RE = re.compile(r"^-\s+\[[xX]\]\s+", re.MULTILINE)
RETRO_HEADING_RE = re.compile(r"^#{1,4}\s+Retrospective", re.MULTILINE)


def _plan_is_complete(text: str) -> bool:
    """A plan is complete when it has checkboxes and all are checked."""
    total = len(CHECKBOX_TOTAL_RE.findall(text))
    done = len(CHECKBOX_DONE_RE.findall(text))
    return total > 0 and done == total


def _has_retro_section(text: str) -> bool:
    return bool(RETRO_HEADING_RE.search(text))


def _referenced_in_learnings(plan_number: str, learnings_path: Path) -> bool:
    if not learnings_path.is_file():
        return False
    content = learnings_path.read_text()
    return bool(re.search(rf"\b{re.escape(plan_number)}\b", content))


def run_retro_check() -> None:
    """Check for missing retrospectives across completed plans."""
    plans_dir = Path("docs/ai/plans")
    learnings_path = Path("docs/ai/state/learnings_tracker.md")

    if not plans_dir.is_dir():
        console.print(f"[yellow]Warning: {plans_dir} does not exist.[/yellow]")
        return

    plan_files = sorted(plans_dir.glob("*.md"))
    if not plan_files:
        console.print("[yellow]No plan files found.[/yellow]")
        return

    table = Table(title="Retrospective Check")
    table.add_column("Plan", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Retro Status")

    any_missing = False
    complete_count = 0

    for pf in plan_files:
        m = PLAN_FILENAME_RE.match(pf.name)
        if not m:
            continue

        plan_num = m.group(1)
        title = m.group(2).replace("-", " ").title()
        text = pf.read_text()

        if not _plan_is_complete(text):
            continue

        complete_count += 1
        has_retro = _has_retro_section(text)
        in_learnings = _referenced_in_learnings(plan_num, learnings_path)

        if has_retro or in_learnings:
            status = "[green]Present[/green]"
        else:
            status = "[red]MISSING[/red]"
            any_missing = True

        table.add_row(plan_num, title, status)

    if complete_count == 0:
        console.print("[yellow]No completed plans found.[/yellow]")
        return

    console.print(table)

    if any_missing:
        console.print("[red]Some completed plans are missing retrospectives.[/red]")
        sys.exit(1)
    else:
        console.print("[green]All completed plans have retrospectives.[/green]")
