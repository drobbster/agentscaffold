"""Study listing and querying."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
DATE_FROM_FILENAME_RE = re.compile(r"STU-(\d{4}-\d{2}-\d{2})")


def _extract_field(fm_text: str, field: str) -> str:
    """Extract a simple scalar value from YAML frontmatter text."""
    m = re.search(rf"^\s*{field}\s*:\s*(.+)", fm_text, re.MULTILINE)
    if m:
        return m.group(1).strip().strip("\"'")
    return ""


def run_study_list() -> None:
    """List study files with optional filtering."""
    studies_dir = Path("docs/studies")

    if not studies_dir.is_dir():
        console.print(f"[yellow]Warning: {studies_dir} does not exist.[/yellow]")
        return

    study_files = sorted(studies_dir.glob("STU-*.md"))
    if not study_files:
        console.print("[yellow]No study files (STU-*.md) found.[/yellow]")
        return

    table = Table(title="Studies")
    table.add_column("File", style="cyan")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Date", justify="center")

    for sf in study_files:
        text = sf.read_text()
        title = ""
        status = ""

        fm_match = FRONTMATTER_RE.search(text)
        if fm_match:
            fm_text = fm_match.group(1)
            title = _extract_field(fm_text, "title")
            status = _extract_field(fm_text, "status")

        date_match = DATE_FROM_FILENAME_RE.search(sf.name)
        file_date = date_match.group(1) if date_match else ""

        table.add_row(sf.name, title, status, file_date)

    console.print(table)
