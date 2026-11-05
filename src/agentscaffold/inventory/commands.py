"""``scaffold inventory init | refresh | check``.

Each command returns its exit code: 0 for success (and for findings in ``warn``
mode), 1 for errors in ``fail`` mode or an edit that needs a human, 2 when the
inventory or configuration cannot be read.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape

from agentscaffold.config import CONFIG_FILENAME
from agentscaffold.inventory import generate
from agentscaffold.inventory.project import (
    check_project,
    inventory_path,
    run_collectors,
)
from agentscaffold.inventory.schema import InventoryError

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNREADABLE = 2


def _report_problems(console: Console, problems: list[str]) -> None:
    for problem in problems:
        console.print(f"[yellow]collector: {escape(problem)}[/yellow]")


def _write_scaffold_lists(root: Path, console: Console, *, dry_run: bool) -> None:
    path = root / CONFIG_FILENAME
    if not path.is_file():
        return
    edit = generate.add_manual_section(path.read_text(encoding="utf-8"))
    if edit.changed_lists:
        verb = "Would add" if dry_run else "Added"
        console.print(
            f"{verb} '{generate.MANUAL_SECTION}' to {CONFIG_FILENAME}: "
            + ", ".join(edit.changed_lists)
        )
        if not dry_run:
            path.write_text(edit.text, encoding="utf-8")
    if edit.needs_human:
        console.print(
            f"[yellow]Add '{generate.MANUAL_SECTION}' to these {CONFIG_FILENAME} lists by hand:"
            "[/yellow]"
        )
        console.print(edit.snippet, markup=False, highlight=False)


def run_init(root: Path, config: Any, *, dry_run: bool, today: dt.date, console: Console) -> int:
    """Write a first inventory from the collectors."""
    path = inventory_path(root, config)
    if path.exists():
        console.print(
            f"[red]{escape(str(path))} already exists; use `scaffold inventory refresh`.[/red]"
        )
        return EXIT_FINDINGS
    collected = run_collectors(root, config)
    _report_problems(console, collected.problems)
    text = generate.init_text(collected, today)
    if dry_run:
        console.print(text, markup=False, highlight=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        console.print(
            f"[green]Wrote {escape(str(path))} with {len(collected.components)} components.[/green]"
        )
    _write_scaffold_lists(root, console, dry_run=dry_run)
    if not config.inventory.enabled:
        console.print(
            f"[dim]Set inventory.enabled: true in {CONFIG_FILENAME} to run the checks in "
            "validate, orient and reviews.[/dim]"
        )
    console.print(
        "[dim]Fill layer, owner_plan, roadmap_stage and the lifecycle fields; "
        "then run `scaffold inventory check`.[/dim]"
    )
    return EXIT_OK


def run_refresh(root: Path, config: Any, *, dry_run: bool, today: dt.date, console: Console) -> int:
    """Add newly collected components and update collector-owned fields."""
    path = inventory_path(root, config)
    if not path.is_file():
        console.print(
            f"[red]{escape(str(path))} does not exist; run `scaffold inventory init`.[/red]"
        )
        return EXIT_UNREADABLE
    collected = run_collectors(root, config)
    _report_problems(console, collected.problems)
    try:
        result = generate.refresh_text(path.read_text(encoding="utf-8"), collected, today)
    except InventoryError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return EXIT_UNREADABLE
    if not result.changed:
        console.print("Inventory is up to date with its collectors.")
        return EXIT_OK
    for cid in result.added:
        console.print(f"added {escape(cid)}")
    for cid, key, old, new in result.updated:
        console.print(f"updated {escape(cid)} {key}: {escape(repr(old))} -> {escape(repr(new))}")
    if not result.in_place:
        console.print(f"[yellow]Not written: {escape(result.problem)}.[/yellow]")
        if result.snippet.strip():
            console.print("Append these entries under components:", markup=False)
            console.print(result.snippet, markup=False, highlight=False)
        if result.updated:
            console.print("Apply the field updates listed above by hand.", markup=False)
        return EXIT_FINDINGS
    if dry_run:
        console.print("[dim]Dry run; nothing written.[/dim]")
    else:
        path.write_text(result.text, encoding="utf-8")
        console.print(f"[green]Updated {escape(str(path))}.[/green]")
    return EXIT_OK


def read_changed_files(source: str) -> list[str]:
    """Paths, one per line, from a file or ``-`` (stdin)."""
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def run_check(
    root: Path,
    config: Any,
    *,
    output: str,
    changed_files: list[str] | None,
    today: dt.date,
    console: Console,
) -> int:
    """Run INV-001 to INV-010 and print text or the contract's JSON."""
    path = inventory_path(root, config)
    if not path.is_file() and not config.inventory.enabled:
        console.print("Inventory is not enabled and has no file; nothing to check.", markup=False)
        return EXIT_OK
    try:
        report = check_project(root, config, today=today, changed_files=changed_files)
    except InventoryError as exc:
        if output == "json":
            print(json.dumps({"schema_version": 1, "error": str(exc)}))
        else:
            console.print(f"[red]{escape(str(exc))}[/red]")
        return EXIT_UNREADABLE
    if output == "json":
        print(json.dumps(report.to_dict(), indent=2))
        return report.exit_code
    _print_report(console, report.to_dict())
    return report.exit_code


def _print_report(console: Console, data: dict[str, Any]) -> None:
    for problem in data.get("problems", []):
        console.print(f"[yellow]collector: {escape(problem)}[/yellow]")
    for finding in data["findings"]:
        color = "red" if finding["severity"] == "error" else "yellow"
        where = f" {finding['component']}" if finding["component"] else ""
        console.print(
            f"[{color}]{finding['id']}[/{color}]{escape(where)}: {escape(finding['message'])}"
        )
    for notice in data.get("notices", []):
        console.print(f"[dim]notice: {escape(notice['message'])}[/dim]")
    summary = data["summary"]
    console.print(
        f"{summary['components']} components, {summary['errors']} errors, "
        f"{summary['warnings']} warnings (mode: {data['mode']})"
    )
