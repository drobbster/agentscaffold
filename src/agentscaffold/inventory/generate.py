"""``scaffold inventory init`` and ``refresh``.

Both work from the collectors. ``init`` writes a new inventory; ``refresh``
adds entries for newly collected components and updates the collector-derived
fields (kind, name, source, entrypoint) of existing ones. Neither touches a
human-set field, and both edit text in place so comments survive. An edit that
cannot be verified by re-reading the result is not written; the caller gets the
YAML to paste instead.

The ``scaffold.yaml`` edit (adding the manual's Component Lifecycle section to
the lifecycle step lists) follows the same rule: a targeted text edit, checked by
re-loading, or a printed snippet when the file's shape is not one it recognizes.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from agentscaffold.inventory.collectors import Collected, CollectionResult
from agentscaffold.inventory.schema import Inventory, InventoryError, parse_inventory

#: Fields a collector owns; refresh may rewrite these and nothing else.
COLLECTOR_FIELDS: tuple[str, ...] = ("kind", "name", "source", "entrypoint")
HUMAN_FIELDS: tuple[str, ...] = (
    "reads",
    "layer",
    "owner_plan",
    "roadmap_stage",
    "lifecycle",
    "since",
    "reason",
    "review_by",
    "exit_criteria",
    "replaced_by",
)
MANUAL_SECTION = "Component Lifecycle"
#: ``scaffold.yaml`` lists that deliver or excuse the manual section.
SCAFFOLD_LISTS: tuple[tuple[str, ...], ...] = (
    ("agents", "governance", "steps", "implementation"),
    ("agents", "governance", "steps", "completion"),
    ("agents", "governance", "optional"),
)

_HEADER = """\
# System inventory: what this project runs, who owns each part, and its lifecycle.
# Contract: docs/ai/contracts/system_inventory_interface.md (v1).
# `scaffold inventory refresh` adds newly collected components and updates
# kind, name, source and entrypoint. Every other field is yours to set.
"""


def _scalar(value: Any) -> str:
    """One YAML scalar or flow collection, quoted only when YAML needs it."""
    text = yaml.safe_dump(value, default_flow_style=True, width=10_000, allow_unicode=True)
    lines = [line for line in text.splitlines() if line != "..."]
    return lines[0] if lines else "null"


def new_entry(component: Collected, today: dt.date) -> dict[str, Any]:
    """An inventory entry for a collected component; humans fill the rest."""
    return {
        "id": component.id,
        "kind": component.kind,
        "name": component.name,
        "source": component.source,
        "entrypoint": component.entrypoint,
        "reads": [],
        "layer": None,
        "owner_plan": None,
        "roadmap_stage": None,
        "lifecycle": "paused" if component.paused else "active",
        "since": today.isoformat(),
    }


def render_entry(entry: dict[str, Any], indent: int = 2) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    for index, (key, value) in enumerate(entry.items()):
        lead = f"{pad}- " if index == 0 else f"{pad}  "
        lines.append(f"{lead}{key}: {_scalar(value)}")
    return lines


def render_inventory(entries: list[dict[str, Any]]) -> str:
    body = [
        _HEADER.rstrip("\n"),
        "schema_version: 1",
        "current_roadmap_stage: null",
        "last_architecture_review: null",
        "review_cadence_days: 30",
    ]
    if not entries:
        body.append("components: []")
    else:
        body.append("components:")
        for entry in entries:
            body.extend(render_entry(entry))
    return "\n".join(body) + "\n"


def init_text(collected: CollectionResult, today: dt.date) -> str:
    """A new inventory holding every collected component."""
    entries = [new_entry(c, today) for c in sorted(collected.components, key=lambda c: c.id)]
    return render_inventory(entries)


# ---------------------------------------------------------------------------
# Block-YAML navigation (no comment-preserving YAML library is a dependency)
# ---------------------------------------------------------------------------


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _block_end(lines: list[str], key_index: int, key_indent: int) -> int:
    """End (exclusive) of the value block under the key at *key_index*.

    A sequence may sit at the key's own indent (``key:`` then ``- item``).
    """
    for index in range(key_index + 1, len(lines)):
        line = lines[index]
        if not _content(line):
            continue
        indent = _indent(line)
        if indent < key_indent or (indent == key_indent and not line.lstrip().startswith("- ")):
            return index
    return len(lines)


def _last_content(lines: list[str], start: int, end: int) -> int:
    """Index after the last content line in ``[start, end)``; *start* when there is none."""
    last = start
    for index in range(start, end):
        if _content(lines[index]):
            last = index + 1
    return last


def _key_line(key: str, indent: int) -> re.Pattern[str]:
    return re.compile(rf"^ {{{indent}}}{re.escape(key)}:(?P<rest>\s.*)?$")


def _inline_value(rest: str | None) -> str:
    text = (rest or "").strip()
    return "" if text.startswith("#") else text


# ---------------------------------------------------------------------------
# Inventory refresh
# ---------------------------------------------------------------------------


@dataclass
class RefreshResult:
    text: str
    added: list[str] = field(default_factory=list)
    updated: list[tuple[str, str, Any, Any]] = field(default_factory=list)
    in_place: bool = True
    snippet: str = ""
    problem: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated)


def _components_block(lines: list[str]) -> tuple[int, int, int] | None:
    """``(key index, block end, item indent)`` of the top-level ``components:`` key."""
    pattern = _key_line("components", 0)
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        end = _block_end(lines, index, 0)
        item_indent = 2
        for inner in range(index + 1, end):
            if _content(lines[inner]) and lines[inner].lstrip().startswith("- "):
                item_indent = _indent(lines[inner])
                break
        return index, end, item_indent
    return None


def _entry_span(
    lines: list[str], start: int, end: int, entry_id: str
) -> tuple[int, int, int] | None:
    """``(first line, end, key indent)`` of the list item whose ``id`` is *entry_id*."""
    item_start = None
    for index in range(start, end):
        line = lines[index]
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:].lstrip()
        match = re.match(r"id:\s*(.+?)\s*$", body)
        if not match:
            continue
        try:
            value = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if str(value) == entry_id:
            item_start = index
            key_indent = len(line) - len(body)
            break
    if item_start is None:
        return None
    item_indent = _indent(lines[item_start])
    stop = end
    for index in range(item_start + 1, end):
        line = lines[index]
        if _content(line) and _indent(line) <= item_indent:
            stop = index
            break
    return item_start, stop, key_indent


def _set_field(lines: list[str], span: tuple[int, int, int], key: str, value: Any) -> bool:
    start, stop, key_indent = span
    pattern = re.compile(rf"^(?P<lead> {{{key_indent}}}{re.escape(key)}:)(?P<rest>.*)$")
    for index in range(start + 1, stop):
        match = pattern.match(lines[index])
        if not match:
            continue
        if (
            index + 1 < stop
            and _content(lines[index + 1])
            and _indent(lines[index + 1]) > key_indent
        ):
            return False
        lines[index] = f"{match.group('lead')} {_scalar(value)}"
        return True
    lines.insert(start + 1, f"{' ' * key_indent}{key}: {_scalar(value)}")
    return True


def _human_view(inventory: Inventory) -> dict[str, dict[str, Any]]:
    return {c.id: {f: getattr(c, f) for f in HUMAN_FIELDS} for c in inventory.components if c.id}


def refresh_text(text: str, collected: CollectionResult, today: dt.date) -> RefreshResult:
    """Add new components and update collector fields in *text*, keeping comments.

    Raises InventoryError when *text* is not a readable inventory.
    """
    before = parse_inventory(text)
    declared = before.by_id()
    found = collected.by_id()
    added = [c for c in sorted(collected.components, key=lambda c: c.id) if c.id not in declared]
    updates: list[tuple[str, str, Any, Any]] = []
    for cid, comp in sorted(found.items()):
        entry = declared.get(cid)
        if entry is None:
            continue
        for key in COLLECTOR_FIELDS:
            new = getattr(comp, key)
            if key == "entrypoint" and new is None:
                continue
            if getattr(entry, key) != new:
                updates.append((cid, key, getattr(entry, key), new))
    result = RefreshResult(text=text, updated=updates, added=[c.id for c in added])
    if not result.changed:
        return result

    entries = [new_entry(c, today) for c in added]
    lines = text.splitlines()
    block = _components_block(lines)
    ok = block is not None
    if block is not None:
        inline = lines[block[0]].split(":", 1)[1].split("#", 1)[0].strip()
        if inline == "[]" and not before.components:
            lines[block[0]] = "components:"
        elif inline:
            ok = False
    if ok:
        for cid, key, _old, new in updates:
            block = _components_block(lines)
            span = _entry_span(lines, block[0] + 1, block[1], cid) if block else None
            if span is None or not _set_field(lines, span, key, new):
                ok = False
                break
    if ok and entries:
        block = _components_block(lines)
        assert block is not None
        at = _last_content(lines, block[0] + 1, block[1])
        new_lines = [line for entry in entries for line in render_entry(entry, block[2])]
        lines[at:at] = new_lines
    candidate = "\n".join(lines) + ("\n" if text.endswith("\n") or not text else "")
    if ok and _verified(before, candidate, found, result):
        result.text = candidate
        return result
    result.in_place = False
    result.problem = "the inventory's layout is not one refresh can edit in place"
    result.snippet = "\n".join(line for entry in entries for line in render_entry(entry)) + "\n"
    return result


def _verified(
    before: Inventory, candidate: str, found: dict[str, Collected], result: RefreshResult
) -> bool:
    try:
        after = parse_inventory(candidate)
    except InventoryError:
        return False
    if _human_view(after) != {**_human_view(before), **_human_view(_only(after, result.added))}:
        return False
    if [c.id for c in after.components] != [c.id for c in before.components] + result.added:
        return False
    by_id = after.by_id()
    for cid, key, _old, new in result.updated:
        if getattr(by_id[cid], key) != new:
            return False
    return all(cid in by_id and by_id[cid].kind == found[cid].kind for cid in result.added)


def _only(inventory: Inventory, ids: list[str]) -> Inventory:
    keep = set(ids)
    return Inventory(components=[c for c in inventory.components if c.id in keep])


# ---------------------------------------------------------------------------
# scaffold.yaml: deliver the Component Lifecycle section (lifecycle step lists)
# ---------------------------------------------------------------------------


@dataclass
class ScaffoldEdit:
    text: str
    changed_lists: list[str] = field(default_factory=list)
    snippet: str = ""

    @property
    def needs_human(self) -> bool:
        return bool(self.snippet)


def _get(data: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _has_path(data: Any, path: tuple[str, ...]) -> bool:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return False
        data = data[key]
    return True


def _set(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    for key in path[:-1]:
        data = data[key]
    data[path[-1]] = value


def _append_list_item(lines: list[str], path: tuple[str, ...], item: str) -> bool:
    """Append *item* to the block-style list at *path*; False when the shape is unknown."""
    lo, hi, indent = 0, len(lines), 0
    for depth, key in enumerate(path):
        if depth:
            children = [i for i in range(lo, hi) if _content(lines[i])]
            if not children:
                return False
            indent = _indent(lines[children[0]])
        pattern = _key_line(key, indent)
        found = next((i for i in range(lo, hi) if pattern.match(lines[i])), None)
        if found is None:
            return False
        rest = _inline_value(pattern.match(lines[found]).group("rest"))  # type: ignore[union-attr]
        if rest.split("#", 1)[0].strip() == "[]" and depth == len(path) - 1:
            lines[found] = f"{' ' * indent}{key}:"
            lines.insert(found + 1, f"{' ' * (indent + 2)}- {_scalar(item)}")
            return True
        if rest:
            return False
        lo, hi = found + 1, _block_end(lines, found, indent)
    items = [i for i in range(lo, hi) if _content(lines[i])]
    if not items or not all(lines[i].lstrip().startswith("- ") for i in items):
        return False
    item_indent = _indent(lines[items[0]])
    lines.insert(items[-1] + 1, f"{' ' * item_indent}- {_scalar(item)}")
    return True


def snippet_for(path: tuple[str, ...], values: list[str]) -> str:
    nested: Any = values
    for key in reversed(path):
        nested = {key: nested}
    return yaml.safe_dump(nested, sort_keys=False, default_flow_style=False)


def add_manual_section(text: str, section: str = MANUAL_SECTION) -> ScaffoldEdit:
    """Add *section* to the lifecycle step lists that ``scaffold.yaml`` sets explicitly.

    A list the file does not set uses the built-in default, which already
    includes the section. The edit keeps comments and key order; when a list is
    written in a form this cannot edit (flow style, anchors), the result carries
    a snippet for the human and the text is unchanged.
    """
    try:
        loaded = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return ScaffoldEdit(text=text, snippet="scaffold.yaml is not valid YAML; nothing changed")
    if not isinstance(loaded, dict):
        return ScaffoldEdit(text=text, snippet="scaffold.yaml is not a mapping; nothing changed")
    lines = text.splitlines()
    expected = copy.deepcopy(loaded)
    changed: list[str] = []
    snippets: list[str] = []
    for path in SCAFFOLD_LISTS:
        if not _has_path(loaded, path):
            continue
        current = _get(loaded, path)
        if current is None:
            current = []
        if not isinstance(current, list):
            snippets.append(snippet_for(path, [section]))
            continue
        if any(str(v).strip().lower() == section.lower() for v in current):
            continue
        trial = list(lines)
        if not _append_list_item(trial, path, section):
            snippets.append(snippet_for(path, [*map(str, current), section]))
            continue
        lines = trial
        _set(expected, path, [*current, section])
        changed.append(".".join(path))
    candidate = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if changed:
        try:
            ok = yaml.safe_load(candidate) == expected
        except yaml.YAMLError:
            ok = False
        if not ok:
            paths = [p for p in SCAFFOLD_LISTS if ".".join(p) in changed]
            snippets += [snippet_for(p, [*map(str, _get(loaded, p) or []), section]) for p in paths]
            return ScaffoldEdit(text=text, snippet="\n".join(snippets))
    return ScaffoldEdit(
        text=candidate if changed else text, changed_lists=changed, snippet="\n".join(snippets)
    )
