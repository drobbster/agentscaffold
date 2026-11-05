"""Plan status and workflow state queries."""

from __future__ import annotations

import re

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentscaffold.config import load_config
from agentscaffold.paths import ResolvedPaths, resolve_root

console = Console()

PLAN_FILENAME_RE = re.compile(r"^(\d{3})-(.+)\.md$")
CHECKBOX_TOTAL_RE = re.compile(r"^-\s+\[[ xX]\]\s+", re.MULTILINE)
CHECKBOX_DONE_RE = re.compile(r"^-\s+\[[xX]\]\s+", re.MULTILINE)

#: Status metadata in the forms the graph indexer reads (list, table, heading).
STATUS_LINE_RE = re.compile(
    r"^(?:[ \t]*-[ \t]+Status:[ \t]*(?P<list>.*)"
    r"|\|[ \t]*Status[ \t]*\|[ \t]*(?P<table>[^|\n]*)\|"
    r"|##[ \t]+STATUS:[ \t]*(?P<heading>.*))$",
    re.MULTILINE | re.IGNORECASE,
)
#: The indexer reads metadata from the first 4,000 characters; so does this.
_HEADER_CHARS = 4000


def _infer_status(total: int, done: int) -> str:
    if total == 0:
        return "Draft"
    if done == total:
        return "Complete"
    if done > 0:
        return "In Progress"
    return "Ready"


def status_lines(text: str) -> list[str]:
    """Raw values of every Status metadata line in the plan's header."""
    return [
        (m.group("list") or m.group("table") or m.group("heading") or "").strip()
        for m in STATUS_LINE_RE.finditer(text[:_HEADER_CHARS])
    ]


def plan_status(text: str) -> str:
    """The plan's Status line through ``normalize_plan_status``, else checkbox inference.

    The same reading the orient plan cards use, so a plan marked
    Complete with unchecked steps reports Complete.
    """
    from agentscaffold.review.filters import normalize_plan_status

    for raw in status_lines(text):
        status = normalize_plan_status(raw)
        if status != "Unknown":
            return status
    total = len(CHECKBOX_TOTAL_RE.findall(text))
    done = len(CHECKBOX_DONE_RE.findall(text))
    return _infer_status(total, done)


def _status_style(status: str) -> str:
    return {
        "Complete": "[green]Complete[/green]",
        "In Progress": "[yellow]In Progress[/yellow]",
        "Ready": "[cyan]Ready[/cyan]",
        "Review": "[blue]Review[/blue]",
        "Draft": "[dim]Draft[/dim]",
        "Superseded": "[dim]Superseded[/dim]",
    }.get(status, status)


def run_plan_status() -> None:
    """Show plan status and workflow state."""
    from agentscaffold import collab

    config = load_config()
    paths = ResolvedPaths(config, resolve_root())
    plans_dir = paths.plans_dir

    if not plans_dir.is_dir():
        console.print(f"[yellow]Warning: {plans_dir} does not exist.[/yellow]")
        return

    # Advisory plan claims: map plan number -> owner for the dashboard.
    claims = {
        str(c.get("plan", "")): str(c.get("owner", ""))
        for c in collab.list_claims(paths.claims_dir)
    }

    plan_files = sorted(plans_dir.glob("*.md"))
    if not plan_files:
        console.print("[yellow]No plan files found.[/yellow]")
        return

    table = Table(title="Plan Status Dashboard")
    table.add_column("Plan", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status", justify="center")
    table.add_column("Steps", justify="right")
    if claims:
        table.add_column("Owner", style="magenta")

    counts: dict[str, int] = {}

    for pf in plan_files:
        m = PLAN_FILENAME_RE.match(pf.name)
        if not m:
            continue

        plan_num = m.group(1)
        title = m.group(2).replace("-", " ").title()
        text = pf.read_text()

        total = len(CHECKBOX_TOTAL_RE.findall(text))
        done = len(CHECKBOX_DONE_RE.findall(text))
        status = plan_status(text)
        counts[status] = counts.get(status, 0) + 1

        row = [plan_num, title, _status_style(status), f"{done}/{total}"]
        if claims:
            row.append(claims.get(plan_num, ""))
        table.add_row(*row)

    console.print(table)

    summary_parts = [f"{status}: {n}" for status, n in sorted(counts.items())]
    total_plans = sum(counts.values())
    console.print(
        Panel(
            f"Total plans: {total_plans}  |  " + "  |  ".join(summary_parts),
            title="Summary",
        )
    )
