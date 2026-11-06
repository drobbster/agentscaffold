"""``scaffold inventory init | refresh | check`` (``enable`` and ``review`` build on these).

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
from agentscaffold.inventory import derive, generate
from agentscaffold.inventory.collectors import Collected, CollectionResult
from agentscaffold.inventory.derived_file import (
    PROVENANCE,
    Derived,
    derived_path,
    render_derived,
)
from agentscaffold.inventory.project import (
    check_project,
    inventory_path,
    run_collectors,
)
from agentscaffold.inventory.schema import InventoryError, parse_inventory

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


def _report_notices(console: Console, notices: list[str]) -> None:
    for notice in notices:
        console.print(f"[dim]notice: {escape(notice)}[/dim]")


def _since_dates(
    history: derive.GitHistory, components: list[Collected], today: dt.date
) -> dict[str, str]:
    return {c.id: derive.since(history, c) or today.isoformat() for c in components}


def coverage(derived: Derived, ids: list[str]) -> dict[str, dict[str, int]]:
    """Per derived field: resolved count and count by rule."""
    out: dict[str, dict[str, int]] = {}
    for name, from_key in PROVENANCE.items():
        counts: dict[str, int] = {}
        for cid in ids:
            entry = derived.components.get(cid)
            rule = getattr(entry, from_key) if entry is not None else None
            if entry is not None and getattr(entry, name):
                counts[rule or "unknown"] = counts.get(rule or "unknown", 0) + 1
        out[name] = {"resolved": sum(counts.values()), "total": len(ids), **counts}
    return out


def _print_coverage(console: Console, derived: Derived, ids: list[str]) -> None:
    for name, counts in coverage(derived, ids).items():
        rules = ", ".join(f"{k} {v}" for k, v in counts.items() if k not in ("resolved", "total"))
        console.print(
            f"  {name}: {counts['resolved']}/{counts['total']} derived"
            + (f" ({escape(rules)})" if rules else ""),
            highlight=False,
        )
    if derived.current_roadmap_stage:
        console.print(
            f"  current roadmap stage: {escape(derived.current_roadmap_stage)} "
            f"(from {derived.current_roadmap_stage_from})",
            highlight=False,
        )


def _same_content(old: str, new: str) -> bool:
    def body(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.startswith("generated_at:")]

    return body(old) == body(new)


def write_derived(
    root: Path,
    config: Any,
    inventory_text: str,
    collected: CollectionResult,
    *,
    today: dt.date,
    console: Console,
    dry_run: bool,
    history: derive.GitHistory | None = None,
) -> Derived | None:
    """Regenerate the derived file for *inventory_text*; None when it cannot be parsed."""
    try:
        inventory = parse_inventory(inventory_text)
    except InventoryError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return None
    derived = derive.derive(root, config, inventory, collected, today=today, history=history)
    path = derived_path(root, config)
    text = render_derived(derived, today)
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    if previous is not None and _same_content(previous, text):
        console.print(f"Derived file {escape(_rel(root, path))} is up to date.")
    elif dry_run:
        console.print(f"[dim]Would write {escape(_rel(root, path))}.[/dim]")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        console.print(f"[green]Wrote {escape(_rel(root, path))}.[/green]")
    _print_coverage(console, derived, [c.id for c in inventory.components if c.id])
    return derived


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def run_init(root: Path, config: Any, *, dry_run: bool, today: dt.date, console: Console) -> int:
    """Write a first inventory from the collectors, and its derived file."""
    path = inventory_path(root, config)
    if path.exists():
        console.print(
            f"[red]{escape(str(path))} already exists; use `scaffold inventory refresh`.[/red]"
        )
        return EXIT_FINDINGS
    collected = run_collectors(root, config)
    _report_problems(console, collected.problems)
    _report_notices(console, collected.notices)
    history = derive.GitHistory(root)
    text = generate.init_text(collected, today, _since_dates(history, collected.components, today))
    if dry_run:
        console.print(text, markup=False, highlight=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        console.print(
            f"[green]Wrote {escape(str(path))} with {len(collected.components)} components.[/green]"
        )
    write_derived(
        root, config, text, collected, today=today, console=console, dry_run=dry_run,
        history=history,
    )  # fmt: skip
    _write_scaffold_lists(root, console, dry_run=dry_run)
    if not config.inventory.enabled:
        console.print(
            f"[dim]Set inventory.enabled: true in {CONFIG_FILENAME} to run the checks in "
            "validate, orient and reviews.[/dim]"
        )
    console.print(
        "[dim]Record lifecycle decisions (paused, deprecated, experimental) in the "
        "inventory; then run `scaffold inventory check`.[/dim]"
    )
    return EXIT_OK


def run_refresh(
    root: Path,
    config: Any,
    *,
    dry_run: bool,
    today: dt.date,
    console: Console,
    pin_derived: bool = False,
) -> int:
    """Add newly collected components, update collector-owned fields, re-derive."""
    path = inventory_path(root, config)
    if not path.is_file():
        console.print(
            f"[red]{escape(str(path))} does not exist; run `scaffold inventory init`.[/red]"
        )
        return EXIT_UNREADABLE
    collected = run_collectors(root, config)
    _report_problems(console, collected.problems)
    _report_notices(console, collected.notices)
    history = derive.GitHistory(root)
    text = path.read_text(encoding="utf-8")
    try:
        declared = {c.id for c in parse_inventory(text).components}
        new = [c for c in collected.components if c.id not in declared]
        result = generate.refresh_text(text, collected, today, _since_dates(history, new, today))
    except InventoryError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return EXIT_UNREADABLE
    if not result.changed:
        console.print("Inventory is up to date with its collectors.")
    for cid in result.added:
        console.print(f"added {escape(cid)}")
    for cid, key, old, new_value in result.updated:
        console.print(
            f"updated {escape(cid)} {key}: {escape(repr(old))} -> {escape(repr(new_value))}"
        )
    if result.changed and not result.in_place:
        console.print(f"[yellow]Not written: {escape(result.problem)}.[/yellow]")
        if result.snippet.strip():
            console.print("Append these entries under components:", markup=False)
            console.print(result.snippet, markup=False, highlight=False)
        if result.updated:
            console.print("Apply the field updates listed above by hand.", markup=False)
        return EXIT_FINDINGS
    if result.changed and not dry_run:
        path.write_text(result.text, encoding="utf-8")
        console.print(f"[green]Updated {escape(str(path))}.[/green]")
    derived = write_derived(
        root, config, result.text, collected, today=today, console=console, dry_run=dry_run,
        history=history,
    )  # fmt: skip
    if derived is None:
        return EXIT_UNREADABLE
    if pin_derived:
        pinned = generate.pin_derived_text(result.text, derived)
        if not pinned.in_place:
            console.print(f"[yellow]Pins not written: {escape(pinned.problem)}.[/yellow]")
            return EXIT_FINDINGS
        if pinned.updated and not dry_run:
            path.write_text(pinned.text, encoding="utf-8")
        verb = "Would pin" if dry_run else "Pinned"
        console.print(f"{verb} {len(pinned.updated)} derived values in {escape(str(path))}.")
    if dry_run:
        console.print("[dim]Dry run; nothing written.[/dim]")
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
    """Run INV-001 to INV-011 and print text or the contract's JSON."""
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


def run_review(
    root: Path,
    config: Any,
    *,
    output: str,
    record: bool,
    exit_code: bool,
    today: dt.date,
    console: Console,
) -> int:
    """Print the architecture review packet; optionally stamp the review date."""
    from agentscaffold.inventory.review import build_packet, render_markdown  # noqa: PLC0415

    path = inventory_path(root, config)
    if not path.is_file():
        console.print(
            f"[red]{escape(str(path))} does not exist; run `scaffold inventory enable`.[/red]"
        )
        return EXIT_UNREADABLE
    try:
        packet = build_packet(root, config, today=today)
    except InventoryError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return EXIT_UNREADABLE
    if output == "json":
        print(json.dumps(packet, indent=2))
    else:
        console.print(render_markdown(packet), markup=False, highlight=False)
    if record:
        text = generate.set_top_level(
            path.read_text(encoding="utf-8"), "last_architecture_review", today.isoformat()
        )
        if text is None:
            console.print(
                "[yellow]Could not record the review in place; set "
                f"last_architecture_review: {today.isoformat()} by hand.[/yellow]"
            )
            return EXIT_FINDINGS
        path.write_text(text, encoding="utf-8")
        target = sys.stderr if output == "json" else None
        message = f"Recorded last_architecture_review: {today.isoformat()} in {path}."
        if target is None:
            console.print(escape(message))
        else:
            print(message, file=target)
    return EXIT_FINDINGS if exit_code and packet["has_debt"] else EXIT_OK


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
