"""A plan's component fields (contract v2, Plan integration).

Plans name the components they touch in ``- Components:`` and carry a
"Component Lifecycle Changes" table with columns Component, Before, After and
Action. ``After`` is a lifecycle state or ``removed``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(?:[\d.]+\s+)?Component Lifecycle Changes\s*$", re.IGNORECASE)
_ANY_HEADING = re.compile(r"^(#{1,6})\s+")
_COMPONENTS_LINE = re.compile(r"^-\s*Components:\s*(.*)$", re.MULTILINE | re.IGNORECASE)
_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}")
_NONE = frozenset({"", "none", "n/a", "tbd", "-"})


@dataclass(frozen=True)
class LifecycleRow:
    component: str
    before: str
    after: str
    action: str


def _cell(text: str) -> str:
    return text.strip().strip("`").strip()


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [_cell(c) for c in body.split("|")]


def lifecycle_rows(text: str) -> list[LifecycleRow] | None:
    """Rows of the Component Lifecycle Changes table; None when the plan has no table."""
    lines = text.splitlines()
    start = None
    level = 0
    for index, line in enumerate(lines):
        match = _HEADING.match(line.strip())
        if match:
            start, level = index + 1, len(match.group(1))
            break
    if start is None:
        return None
    header: list[str] | None = None
    rows: list[LifecycleRow] = []
    for line in lines[start:]:
        stripped = line.strip()
        heading = _ANY_HEADING.match(stripped)
        if heading and len(heading.group(1)) <= level:
            break
        if not stripped.startswith("|"):
            if header is not None and rows:
                break
            continue
        if _SEPARATOR.match(stripped):
            continue
        cells = _cells(stripped)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        values = dict(zip(header, cells, strict=False))
        component = values.get("component", "")
        if component.lower() in _NONE:
            continue
        rows.append(
            LifecycleRow(
                component=component,
                before=values.get("before", "").lower(),
                after=values.get("after", "").lower(),
                action=values.get("action", ""),
            )
        )
    return rows if header is not None else None


def plan_components(text: str) -> list[str]:
    """Component ids on the plan's ``- Components:`` line, in order."""
    match = _COMPONENTS_LINE.search(text)
    if not match:
        return []
    out: list[str] = []
    for part in match.group(1).split(","):
        value = _cell(part)
        if value.lower() not in _NONE and value not in out:
            out.append(value)
    return out


def has_components_line(text: str) -> bool:
    return _COMPONENTS_LINE.search(text) is not None
