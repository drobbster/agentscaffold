"""Study linting and template compliance checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
HEADING_RE = re.compile(r"^#{1,4}\s+(.+)", re.MULTILINE)

REQUIRED_FRONTMATTER_FIELDS = ("title", "status", "tags")
REQUIRED_SECTIONS: tuple[str, ...] = (
    "Overview",
    "Hypothesis",
    "Methodology",
    "Results",
    "Conclusion",
)

# "Conclusions" also accepted as alias for "Conclusion"
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "Conclusion": ("Conclusion", "Conclusions"),
}


def _lint_study(path: Path) -> list[str]:
    """Return a list of issues for a single study file."""
    issues: list[str] = []
    text = path.read_text()

    fm_match = FRONTMATTER_RE.search(text)
    if not fm_match:
        issues.append("Missing YAML frontmatter (--- markers)")
    else:
        fm_text = fm_match.group(1)
        for field in REQUIRED_FRONTMATTER_FIELDS:
            if not re.search(rf"^\s*{field}\s*:", fm_text, re.MULTILINE):
                issues.append(f"Frontmatter missing required field: {field}")

    headings = [m.group(1).strip() for m in HEADING_RE.finditer(text)]
    lowered = [h.lower() for h in headings]

    for section in REQUIRED_SECTIONS:
        aliases = SECTION_ALIASES.get(section, (section,))
        if not any(a.lower() in lowered for a in aliases):
            issues.append(f"Missing required section: {section}")

    return issues


def run_study_lint() -> None:
    """Lint study files for template compliance."""
    studies_dir = Path("docs/studies")

    if not studies_dir.is_dir():
        console.print(f"[yellow]Warning: {studies_dir} does not exist. Nothing to lint.[/yellow]")
        return

    study_files = sorted(studies_dir.glob("STU-*.md"))
    if not study_files:
        console.print("[yellow]No study files (STU-*.md) found.[/yellow]")
        return

    table = Table(title="Study Lint Results")
    table.add_column("Study", style="cyan")
    table.add_column("Status")
    table.add_column("Issues")

    any_failure = False
    for sf in study_files:
        issues = _lint_study(sf)
        if issues:
            any_failure = True
            table.add_row(sf.name, "[red]FAIL[/red]", "\n".join(issues))
        else:
            table.add_row(sf.name, "[green]PASS[/green]", "")

    console.print(table)

    if any_failure:
        sys.exit(1)
