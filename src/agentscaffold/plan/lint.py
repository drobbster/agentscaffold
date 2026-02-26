"""Plan linting and cohesion checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from agentscaffold.config import load_config

console = Console()

REQUIRED_SECTIONS: list[tuple[str, ...]] = [
    ("Objective", "Goal", "Purpose"),
    ("File Impact Map", "Files Changed", "Impact"),
    ("Execution Steps", "Steps", "Implementation"),
    ("Tests", "Test Plan", "Testing"),
    ("Validation Commands", "Validation"),
    ("Rollback Plan", "Rollback"),
]

HEADING_RE = re.compile(r"^#{1,4}\s+(?:\d+\.\s*)?(.+)", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^-\s+\[[ xX]\]\s+", re.MULTILINE)
FILE_REF_RE = re.compile(r"\|\s*\S+\.\w+\s*\|")
TEST_FILE_RE = re.compile(r"test[_s]?\S*\.py|\.test\.\w+|_test\.\w+|spec\.\w+")


def _extract_headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in HEADING_RE.finditer(text)]


def _has_section(headings: list[str], aliases: tuple[str, ...]) -> bool:
    lowered = [h.lower() for h in headings]
    return any(alias.lower() in lowered for alias in aliases)


def _lint_plan(path: Path) -> list[str]:
    """Return a list of issue strings for a single plan file."""
    issues: list[str] = []
    text = path.read_text()
    headings = _extract_headings(text)

    has_yaml_front = text.startswith("---")
    has_metadata_heading = any("metadata" in h.lower() for h in headings)
    if not has_yaml_front and not has_metadata_heading:
        issues.append("Missing metadata section (## Metadata or YAML frontmatter)")

    for aliases in REQUIRED_SECTIONS:
        if not _has_section(headings, aliases):
            issues.append(f"Missing required section: {aliases[0]}")

    if not CHECKBOX_RE.search(text):
        issues.append("Execution steps should use checkbox format (- [ ] or - [x])")

    if not FILE_REF_RE.search(text):
        issues.append("File Impact Map should list at least one file")

    if not TEST_FILE_RE.search(text):
        issues.append("Tests section should reference at least one test file")

    return issues


def run_plan_lint(plan: str | None) -> None:
    """Lint a plan file for cohesion and template compliance."""
    load_config()
    plans_dir = Path("docs/ai/plans")

    if not plans_dir.is_dir():
        console.print(f"[yellow]Warning: {plans_dir} does not exist. Nothing to lint.[/yellow]")
        return

    if plan is not None:
        candidates = list(plans_dir.glob(f"*{plan}*"))
        if not candidates:
            console.print(f"[red]No plan matching '{plan}' found in {plans_dir}[/red]")
            raise SystemExit(1)
        plan_files = sorted(candidates)
    else:
        plan_files = sorted(plans_dir.glob("*.md"))

    if not plan_files:
        console.print("[yellow]No plan files found.[/yellow]")
        return

    table = Table(title="Plan Lint Results")
    table.add_column("Plan", style="cyan")
    table.add_column("Status")
    table.add_column("Issues")

    any_failure = False
    for pf in plan_files:
        issues = _lint_plan(pf)
        if issues:
            any_failure = True
            table.add_row(pf.name, "[red]FAIL[/red]", "\n".join(issues))
        else:
            table.add_row(pf.name, "[green]PASS[/green]", "")

    console.print(table)

    if any_failure:
        sys.exit(1)
