"""Thin plan_card metadata for MCP routing (Plan 246/247).

Never includes full plan body or full Execution Steps text -- agents that need
to edit open the markdown file. Card fields are cheap routing signals only.

Plan 247: checkbox counts are scoped to the Execution Steps section only so
Tests / Completion / Review checklists do not inflate progress.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_CHECKBOX_LINE = re.compile(r"^-\s+\[([ xX])\]\s+(.*)$", re.MULTILINE)
_HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
_SUMMARY_IMPACT_CAP = 12
_EXECUTION_HEADING_HINTS = ("execution step", "execution steps", "implementation step")


def _execution_steps_section(text: str) -> str:
    """Return the markdown body under the Execution Steps heading, if present."""
    if not text:
        return ""
    headings = list(_HEADING.finditer(text))
    start = None
    end = len(text)
    for i, m in enumerate(headings):
        title = m.group(1).strip().lower()
        # Strip leading numbering like "6. Execution Steps"
        title = re.sub(r"^\d+(\.\d+)*\.\s*", "", title)
        if any(h in title for h in _EXECUTION_HEADING_HINTS):
            start = m.end()
            if i + 1 < len(headings):
                end = headings[i + 1].start()
            break
    if start is None:
        return ""
    return text[start:end]


def count_execution_checkboxes(text: str) -> tuple[int, int]:
    """Return (unchecked, checked) counts from the Execution Steps section only.

    If no Execution Steps heading exists, returns (0, 0) rather than counting
    every checklist in the plan (Plan 247).
    """
    section = _execution_steps_section(text)
    if not section:
        return 0, 0
    unchecked = 0
    checked = 0
    for m in _CHECKBOX_LINE.finditer(section):
        if m.group(1).lower() == "x":
            checked += 1
        else:
            unchecked += 1
    return unchecked, checked


def next_unchecked_step(text: str) -> str | None:
    """Return the text of the first unchecked Execution Steps item, if any."""
    section = _execution_steps_section(text)
    for m in _CHECKBOX_LINE.finditer(section):
        if m.group(1).lower() != "x":
            step = m.group(2).strip()
            return step or None
    return None


def build_plan_card(
    store: Any,
    plan_number: int,
    *,
    root: Path | None = None,
    plan_row: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a thin plan_card for ``plan_number``.

    Uses graph plan row + File Impact edges + optional on-disk markdown for
    checkbox counts. Returns ``None`` when the plan is not in the graph.
    """
    from agentscaffold.review.filters import normalize_plan_status
    from agentscaffold.review.queries import get_plan_by_number, get_plan_impacted_files

    plan = plan_row or get_plan_by_number(store, plan_number)
    if not plan:
        return None

    impacted = get_plan_impacted_files(store, plan_number)
    impact_paths = [f.get("f.path", "") for f in impacted if f.get("f.path")]

    unchecked = 0
    checked = 0
    next_step: str | None = None
    plan_path = plan.get("p.filePath") or plan.get("filePath") or ""
    if root is not None and plan_path:
        full = Path(plan_path)
        if not full.is_absolute():
            full = root / plan_path
        try:
            if full.is_file():
                body = full.read_text(encoding="utf-8")
                unchecked, checked = count_execution_checkboxes(body)
                next_step = next_unchecked_step(body)
        except OSError:
            pass

    open_findings = _open_finding_summary(store, plan_number)

    status = plan.get("p.status") or plan.get("status")
    return {
        "plan_number": int(plan.get("p.number") or plan.get("number") or plan_number),
        "title": plan.get("p.title") or plan.get("title"),
        "status": status,
        "status_normalized": normalize_plan_status(status),
        "last_updated": plan.get("p.lastUpdated") or plan.get("lastUpdated") or "",
        "file_path": plan_path,
        "impacted_file_count": len(impact_paths),
        "impacted_files": impact_paths[:_SUMMARY_IMPACT_CAP],
        "impacted_files_truncated": max(0, len(impact_paths) - _SUMMARY_IMPACT_CAP),
        "unchecked_steps": unchecked,
        "checked_steps": checked,
        "next_unchecked_step": next_step,
        "open_finding_count": open_findings["count"],
        "open_finding_ids": open_findings["ids"],
    }


def _open_finding_summary(store: Any, plan_number: int) -> dict[str, Any]:
    try:
        from agentscaffold.graph.findings import get_open_findings

        rows = get_open_findings(store, plan_number=plan_number) or []
    except Exception:
        rows = []
    ids: list[str] = []
    for r in rows:
        fid = r.get("rf.id") or r.get("id") or ""
        if fid:
            ids.append(str(fid))
    return {"count": len(ids), "ids": ids[:10]}
