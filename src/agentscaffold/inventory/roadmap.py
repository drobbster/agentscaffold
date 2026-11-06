"""The project's current roadmap stage, read from its roadmap document.

The document holds a markdown table with a ``Stage`` column and a ``Gate met``
column. A stage id is the first token of its Stage cell (``3 Promotion`` is
``3``). The current stage is the one after the highest stage whose Gate met
cell begins with "Yes"; with no stage met, it is the first stage.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Searched in order when ``inventory.roadmap.path`` is not set.
CANDIDATES: tuple[str, ...] = (
    "docs/ai/strategy_roadmap.md",
    "docs/ai/delivery_roadmap.md",
    "docs/ai/roadmap.md",
    "docs/roadmap.md",
    "ROADMAP.md",
)

_ROW = re.compile(r"^\s*\|(?P<body>.*)\|\s*$")
_DIVIDER = re.compile(r"^\s*:?-{2,}:?\s*$")


def _cells(line: str) -> list[str] | None:
    match = _ROW.match(line)
    if match is None:
        return None
    return [cell.strip() for cell in match.group("body").split("|")]


def _plain(cell: str) -> str:
    return re.sub(r"[*_`]", "", cell).strip()


def stage_table(text: str) -> list[tuple[str, bool]] | None:
    """``(stage id, gate met)`` rows of the first Stage / Gate met table, or None."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        header = _cells(line)
        if not header:
            continue
        names = [_plain(cell).lower() for cell in header]
        if "stage" not in names or not any(n.startswith("gate met") for n in names):
            continue
        stage_col = names.index("stage")
        gate_col = next(i for i, n in enumerate(names) if n.startswith("gate met"))
        rows: list[tuple[str, bool]] = []
        for row_line in lines[index + 1 :]:
            cells = _cells(row_line)
            if cells is None:
                break
            if all(_DIVIDER.match(c) or not c for c in cells):
                continue
            if max(stage_col, gate_col) >= len(cells):
                continue
            tokens = _plain(cells[stage_col]).split()
            if not tokens:
                continue
            stage = tokens[0].rstrip(".:")
            if stage.lower() == "stage" and len(tokens) > 1:
                stage = tokens[1].rstrip(".:")
            rows.append((stage, _plain(cells[gate_col]).lower().startswith("yes")))
        if rows:
            return rows
    return None


def current_stage(text: str) -> str | None:
    """The stage after the highest stage whose gate is met; None without a table."""
    rows = stage_table(text)
    if not rows:
        return None
    met = [index for index, (_stage, ok) in enumerate(rows) if ok]
    if not met:
        return rows[0][0]
    after = met[-1] + 1
    return rows[after][0] if after < len(rows) else rows[-1][0]


def find_roadmap(root: Path, configured: str | None = None) -> str | None:
    """The configured roadmap path, else the first candidate that has a stage table."""
    if configured:
        return configured
    for candidate in CANDIDATES:
        path = Path(root) / candidate
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if stage_table(text):
            return candidate
    return None


def read_current_stage(root: Path, path: str | None) -> str | None:
    """The current stage from the roadmap at *path*; None when unreadable or tableless."""
    if not path:
        return None
    try:
        text = (Path(root) / path).read_text(encoding="utf-8")
    except OSError:
        return None
    return current_stage(text)


__all__ = ["CANDIDATES", "current_stage", "find_roadmap", "read_current_stage", "stage_table"]
