"""Execution-step parsing for plan markdown (Plan 265).

The checkbox helpers stay file-text functions so ``plan_card`` / ``diff_plan``
keep a live read. Ingest uses the same parser to create ``PlanStep`` nodes.
"""

from __future__ import annotations

import re
from typing import Any

_CHECKBOX_LINE = re.compile(r"^-\s+\[([ xX])\]\s+(.*)$")
_HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
_STEP_NUM = re.compile(r"^Step\s+(\d+)\b", re.IGNORECASE)
_EXECUTION_HEADING_HINTS = ("execution step", "execution steps", "implementation step")

_NEEDS_DEST_RANGE = re.compile(
    r"needs\s+(\d+)\s+steps?\s+(\d+)\s*-\s*(\d+)",
    re.IGNORECASE,
)
_SRC_RANGE_NEEDS = re.compile(
    r"steps?\s+(\d+)\s*-\s*(\d+)\s+need\s+(\d+)",
    re.IGNORECASE,
)


def execution_steps_section(text: str) -> str:
    """Return the markdown body under the Execution Steps heading, if present."""
    if not text:
        return ""
    headings = list(_HEADING.finditer(text))
    start = None
    end = len(text)
    for i, m in enumerate(headings):
        title = m.group(1).strip().lower()
        title = re.sub(r"^\d+(\.\d+)*\.\s*", "", title)
        if any(h in title for h in _EXECUTION_HEADING_HINTS):
            start = m.end()
            if i + 1 < len(headings):
                end = headings[i + 1].start()
            break
    if start is None:
        return ""
    return text[start:end]


def _checkbox_matches(section: str) -> list[re.Match[str]]:
    """Checkbox lines in ``section``, skipping fenced code blocks."""
    matches: list[re.Match[str]] = []
    in_fence = False
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _CHECKBOX_LINE.match(line)
        if m:
            matches.append(m)
    return matches


def count_execution_checkboxes(text: str) -> tuple[int, int]:
    """Return (unchecked, checked) counts from the Execution Steps section only.

    If no Execution Steps heading exists, returns (0, 0) rather than counting
    every checklist in the plan (Plan 247).
    """
    section = execution_steps_section(text)
    if not section:
        return 0, 0
    unchecked = 0
    checked = 0
    for m in _checkbox_matches(section):
        if m.group(1).lower() == "x":
            checked += 1
        else:
            unchecked += 1
    return unchecked, checked


def next_unchecked_step(text: str) -> str | None:
    """Return the text of the first unchecked Execution Steps item, if any."""
    section = execution_steps_section(text)
    for m in _checkbox_matches(section):
        if m.group(1).lower() != "x":
            step = m.group(2).strip()
            return step or None
    return None


def parse_execution_steps(text: str) -> list[dict[str, Any]]:
    """Parse Execution Steps checkboxes into graph-ready step dicts."""
    section = execution_steps_section(text)
    if not section:
        return []
    steps: list[dict[str, Any]] = []
    for ordinal, m in enumerate(_checkbox_matches(section), start=1):
        body = m.group(2).strip()
        num_m = _STEP_NUM.match(body)
        step_number = int(num_m.group(1)) if num_m else ordinal
        steps.append(
            {
                "ordinal": ordinal,
                "step_number": step_number,
                "text": body,
                "checked": m.group(1).lower() == "x",
            }
        )
    return steps


def parse_step_dependencies(raw: str) -> list[dict[str, Any]]:
    """Parse a ``Step dependencies:`` metadata value into edge clauses.

    ``needs 262 steps 1-9`` -- this plan waits on dest steps 1-9.
    ``steps 10-13 need 270`` -- this plan's steps 10-13 wait on dest.
    Clauses are semicolon-separated. Unknown text is ignored.
    """
    if not raw or raw.lower() in ("none", "n/a", "---"):
        return []
    clauses: list[dict[str, Any]] = []
    for part in raw.split(";"):
        chunk = part.strip()
        if not chunk:
            continue
        dest_m = _NEEDS_DEST_RANGE.search(chunk)
        if dest_m:
            clauses.append(
                {
                    "dest_number": int(dest_m.group(1)),
                    "from_step": None,
                    "from_step_end": None,
                    "to_step": int(dest_m.group(2)),
                    "to_step_end": int(dest_m.group(3)),
                }
            )
            continue
        src_m = _SRC_RANGE_NEEDS.search(chunk)
        if src_m:
            clauses.append(
                {
                    "dest_number": int(src_m.group(3)),
                    "from_step": int(src_m.group(1)),
                    "from_step_end": int(src_m.group(2)),
                    "to_step": None,
                    "to_step_end": None,
                }
            )
    return clauses
