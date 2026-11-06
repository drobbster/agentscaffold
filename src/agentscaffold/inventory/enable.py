"""``scaffold inventory enable``: turn the inventory on in one command.

Each step writes only what is missing, so a second run changes nothing:

1. ``scaffold.yaml``: add the ``inventory:`` block or flip ``enabled`` (a
   targeted edit that keeps comments; keys already set are left alone).
2. The scheduled review workflow, when ``.github/workflows/`` exists (before
   collection, so the workflow is inventoried in the same run).
3. ``init`` when the inventory is absent, else ``refresh``; both derive.
4. The architecture review prompt, when the project lacks it.
5. The Component Lifecycle manual section (insert-only) and its
   ``scaffold.yaml`` step-list entries.
6. Component nodes, when a graph exists.
7. A summary: components by kind, derivation coverage, unresolved items.
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.markup import escape

from agentscaffold.config import CONFIG_FILENAME, load_config
from agentscaffold.inventory import generate
from agentscaffold.inventory.collectors import expand_sources, registered
from agentscaffold.inventory.commands import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_UNREADABLE,
    _rel,
    _write_scaffold_lists,
    run_init,
    run_refresh,
)
from agentscaffold.inventory.project import collectors_of, ignore_patterns, inventory_path
from agentscaffold.inventory.roadmap import find_roadmap

logger = logging.getLogger(__name__)

MANUAL = "AGENTS.md"
REVIEW_PROMPT = ("prompts/architecture_review.md.j2", "architecture_review.md")


@dataclass
class ConfigEdit:
    text: str
    changes: list[str] = field(default_factory=list)
    snippet: str = ""


def detected_collectors(root: Path, config: Any) -> list[str]:
    """Registered collectors not configured whose default sources match a file here."""
    configured = {name for name, _ in collectors_of(config)}
    patterns = ignore_patterns(root, config)
    return [
        name
        for name, spec in sorted(registered().items())
        if name not in configured
        and expand_sources(Path(root), list(spec.default_sources), ignore=patterns)
    ]


def _block_lines(values: dict[str, Any], indent: int) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    for key, value in values.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(_block_lines(value, indent + 2))
        elif isinstance(value, list):
            lines.append(f"{pad}{key}:")
            lines.extend(f"{pad}  - {generate._scalar(item)}" for item in value)
        elif key == "plan_adoption_date":
            lines.append(f'{pad}{key}: "{value}"')
        else:
            lines.append(f"{pad}{key}: {generate._scalar(value)}")
    return lines


def _snippet(values: dict[str, Any]) -> str:
    return "\n".join(["inventory:", *_block_lines(values, 2)]) + "\n"


def edit_scaffold_yaml(
    text: str,
    *,
    today: dt.date,
    roadmap: str | None = None,
    collectors: list[str] | None = None,
    extra_collectors: list[str] | None = None,
) -> ConfigEdit:
    """Enable the inventory in ``scaffold.yaml`` text, adding only what is missing.

    *collectors* is the effective list, written only when *extra_collectors*
    (detected, not yet configured) must join an implicit default list. The
    result is verified by reloading; a shape this cannot edit (flow style)
    leaves the text unchanged and returns a snippet for the human.
    """
    extras = list(extra_collectors or [])
    try:
        loaded = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return ConfigEdit(text, snippet=f"{CONFIG_FILENAME} is not valid YAML; nothing changed")
    if not isinstance(loaded, dict):
        return ConfigEdit(text, snippet=f"{CONFIG_FILENAME} is not a mapping; nothing changed")
    current = loaded.get("inventory")
    current = current if isinstance(current, dict) else {}

    missing: dict[str, Any] = {}
    for key, value in (
        ("enforcement", "warn"),
        ("review_overdue", "error"),
        ("plan_adoption_date", today.isoformat()),
    ):
        if key not in current:
            missing[key] = value
    if roadmap and "roadmap" not in current:
        missing["roadmap"] = {"path": roadmap}
    if extras and "collectors" not in current:
        missing["collectors"] = [*(collectors or []), *extras]
    append = extras if "collectors" in current else []

    expected = copy.deepcopy(loaded)
    target = {**current, "enabled": True, **missing}
    if append:
        target["collectors"] = [*(current.get("collectors") or []), *append]
    expected["inventory"] = target
    changes: list[str] = []
    if current.get("enabled") is not True:
        changes.append("inventory.enabled: true")
    changes += [f"inventory.{key}" for key in missing]
    changes += [f"inventory.collectors + {name}" for name in append]
    if not changes:
        return ConfigEdit(text)

    lines = text.splitlines()
    key_pattern = generate._key_line("inventory", 0)
    index = next((i for i, line in enumerate(lines) if key_pattern.match(line)), None)
    if index is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "# System inventory (scaffold inventory enable)."]
        lines += ["inventory:", *_block_lines({"enabled": True, **missing}, 2)]
    else:
        rest = generate._inline_value(key_pattern.match(lines[index]).group("rest"))  # type: ignore[union-attr]
        if rest not in ("", "null", "~"):
            return ConfigEdit(text, snippet=_snippet(target))
        lines[index] = "inventory:"
        for name in append:
            if not generate._append_list_item(lines, ("inventory", "collectors"), name):
                return ConfigEdit(text, snippet=_snippet(target))
        end = generate._block_end(lines, index, 0)
        children = [i for i in range(index + 1, end) if generate._content(lines[i])]
        indent = generate._indent(lines[children[0]]) if children else 2
        insert_at = generate._last_content(lines, index + 1, end)
        lines[insert_at:insert_at] = _block_lines(missing, indent)
        enabled = generate._key_line("enabled", indent)
        found = next((i for i in range(index + 1, end) if enabled.match(lines[i])), None)
        if found is None:
            lines.insert(index + 1, f"{' ' * indent}enabled: true")
        elif current.get("enabled") is not True:
            lines[found] = f"{' ' * indent}enabled: true"
    candidate = "\n".join(lines) + "\n"
    try:
        ok = yaml.safe_load(candidate) == expected
    except yaml.YAMLError:
        ok = False
    if not ok:
        return ConfigEdit(text, snippet=_snippet(target))
    return ConfigEdit(candidate, changes)


def _install_prompt(root: Path, config: Any, *, dry_run: bool, console: Console) -> None:
    from agentscaffold.paths import ResolvedPaths  # noqa: PLC0415
    from agentscaffold.rendering import get_default_context, render_template  # noqa: PLC0415

    template, name = REVIEW_PROMPT
    target = ResolvedPaths(config, root).prompts_dir / name
    if target.exists():
        return
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_template(template, get_default_context(config)), "utf-8")
    verb = "Would install" if dry_run else "Installed"
    console.print(f"{verb} {escape(_rel(root, target))}.")


def _deliver_manual(
    root: Path, config: Any, *, dry_run: bool, console: Console, lists: bool
) -> None:
    from agentscaffold.agents.manual_diff import (  # noqa: PLC0415
        deliver_section,
        insert_sections,
        render_governance_manual,
    )

    path = root / MANUAL
    if not path.is_file():
        console.print(f"[dim]No {MANUAL}; run `scaffold agents generate` for the manual.[/dim]")
    elif dry_run:
        _, inserted = insert_sections(
            path.read_text(), render_governance_manual(config), [generate.MANUAL_SECTION]
        )
        if inserted:
            console.print(f"Would add '{generate.MANUAL_SECTION}' to {MANUAL}.")
    elif deliver_section(path, config, generate.MANUAL_SECTION):
        console.print(f"Added '{generate.MANUAL_SECTION}' to {MANUAL}.")
    if lists:
        _write_scaffold_lists(root, console, dry_run=dry_run)


def _workflow(root: Path, config: Any, *, dry_run: bool, console: Console) -> None:
    from agentscaffold.ci.setup import write_inventory_review_workflow  # noqa: PLC0415

    if not (root / ".github" / "workflows").is_dir():
        return
    path = write_inventory_review_workflow(root, config, dry_run=dry_run)
    if path is not None:
        verb = "Would write" if dry_run else "Wrote"
        console.print(f"{verb} {escape(_rel(root, path))}.")


def reingest_components(root: Path, config: Any, *, console: Console) -> None:
    """Replace the graph's Component nodes when a graph exists; never fatal."""
    try:
        from agentscaffold.graph import graph_available, open_graph  # noqa: PLC0415
        from agentscaffold.graph.inventory import process_inventory  # noqa: PLC0415
        from agentscaffold.graph.scoping import current_project_name  # noqa: PLC0415
        from agentscaffold.paths import load_workspace  # noqa: PLC0415

        if not graph_available(config, start=root):
            return
        store = open_graph(config, start=root)
        try:
            if load_workspace(root).is_multi_project:
                store.set_write_project(current_project_name(root))
            result = process_inventory(store, root, config)
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 - the inventory is written; the graph can catch up
        logger.warning("Component re-ingest failed: %s", exc)
        console.print(
            f"[yellow]Graph not updated ({escape(str(exc))}); run `scaffold index`.[/yellow]"
        )
        return
    console.print(f"Graph: {result.get('components', 0)} components ingested.")


def _summary(root: Path, config: Any, today: dt.date, console: Console) -> None:
    from agentscaffold.inventory.review import build_packet  # noqa: PLC0415

    packet = build_packet(root, config, today=today)
    kinds = ", ".join(f"{k} {v}" for k, v in sorted(packet["by_kind"].items()))
    console.print(f"[bold]Inventory: {packet['components']} components[/bold] ({kinds})")
    for name, counts in packet["coverage"].items():
        console.print(f"  {name}: {counts['resolved']}/{counts['total']} resolved", highlight=False)
    check = packet["check"]
    console.print(
        f"  unresolved owner or layer: {len(packet['unresolved'])}; "
        f"check: {check['errors']} errors, {check['warnings']} warnings",
        highlight=False,
    )
    console.print(
        "[dim]Next: run `scaffold inventory review`, add owners at the source for what is "
        f"unresolved, then commit {CONFIG_FILENAME}, the inventory and its derived file.[/dim]"
    )


def run_enable(root: Path, *, dry_run: bool, today: dt.date, console: Console) -> int:
    """Enable the inventory and deliver every asset it needs (see the module docstring)."""
    config_path = root / CONFIG_FILENAME
    if not config_path.is_file():
        console.print(f"[red]No {CONFIG_FILENAME}; run `scaffold init` first.[/red]")
        return EXIT_UNREADABLE
    config = load_config(config_path)

    text = config_path.read_text(encoding="utf-8")
    roadmap = find_roadmap(root, config.inventory.roadmap.path)
    edit = edit_scaffold_yaml(
        text,
        today=today,
        roadmap=roadmap,
        collectors=[name for name, _ in collectors_of(config)],
        extra_collectors=detected_collectors(root, config),
    )
    if edit.snippet:
        console.print(f"[yellow]Edit {CONFIG_FILENAME} by hand; set:[/yellow]")
        console.print(edit.snippet, markup=False, highlight=False)
        return EXIT_FINDINGS
    verb = "Would set" if dry_run else "Set"
    for change in edit.changes:
        console.print(f"{verb} {escape(change)} in {CONFIG_FILENAME}.")
    if dry_run:
        config = load_config(config_path)
        enabled = yaml.safe_load(edit.text)["inventory"]
        config = config.model_copy(
            update={"inventory": type(config.inventory).model_validate(enabled)}
        )
    else:
        if edit.changes:
            config_path.write_text(edit.text, encoding="utf-8")
        config = load_config(config_path)

    # The review workflow is itself a component, so it exists before collection.
    _workflow(root, config, dry_run=dry_run, console=console)
    exists = inventory_path(root, config).is_file()
    runner = run_refresh if exists else run_init
    code = runner(root, config, dry_run=dry_run, today=today, console=console)
    if code != EXIT_OK:
        return code

    _install_prompt(root, config, dry_run=dry_run, console=console)
    # init already added the section to the scaffold.yaml step lists
    _deliver_manual(root, config, dry_run=dry_run, console=console, lists=exists)
    if dry_run:
        console.print("[dim]Dry run; nothing written.[/dim]")
        return EXIT_OK
    reingest_components(root, config, console=console)
    _summary(root, config, today, console)
    return EXIT_OK


__all__ = [
    "ConfigEdit",
    "detected_collectors",
    "edit_scaffold_yaml",
    "reingest_components",
    "run_enable",
]
