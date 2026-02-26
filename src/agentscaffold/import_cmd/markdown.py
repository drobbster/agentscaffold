"""Markdown file parsing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

console = Console()


def parse_markdown(file: Path) -> str:
    """Read a markdown file and return its contents with import metadata header."""
    try:
        content = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        console.print(f"[red]File not found: {file}[/red]")
        return ""
    except UnicodeDecodeError:
        console.print(f"[red]Cannot read file (encoding error): {file}[/red]")
        return ""

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"<!-- Imported from: {file.name} -->\n" f"<!-- Import date: {now} -->\n" "\n"

    return header + content
