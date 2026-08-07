"""Plan vs code/graph diff for mid-implementation checks (Plan 246/247)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentscaffold.graph.governance import _extract_file_impact
from agentscaffold.mcp.plan_card import (
    build_plan_card,
    count_execution_checkboxes,
    next_unchecked_step,
)

_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
# Common English / markdown noise in plan notes.
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "file",
        "files",
        "test",
        "tests",
        "new",
        "modify",
        "update",
        "add",
        "create",
        "notes",
        "plan",
        "step",
        "steps",
        "true",
        "false",
        "none",
        "null",
        "path",
        "type",
        "change",
    }
)


def diff_plan_vs_code(
    store: Any,
    plan_number: int,
    *,
    root: Path,
) -> dict[str, Any]:
    """Compare a plan's File Impact Map / steps against graph + filesystem."""
    from agentscaffold.review.queries import get_plan_by_number, get_plan_impacted_files

    plan = get_plan_by_number(store, plan_number)
    if not plan:
        return {"error": f"Plan {plan_number} not found."}

    plan_path = plan.get("p.filePath") or ""
    if plan_path and not Path(plan_path).is_absolute():
        full_plan = root / plan_path
    else:
        full_plan = Path(plan_path)
    markdown_paths: list[str] = []
    impact_rows: list[dict[str, str]] = []
    unchecked = 0
    checked = 0
    next_step: str | None = None
    plan_text = ""
    if full_plan.is_file():
        plan_text = full_plan.read_text(encoding="utf-8")
        unchecked, checked = count_execution_checkboxes(plan_text)
        next_step = next_unchecked_step(plan_text)
        impact_rows = _extract_file_impact(plan_text)
        markdown_paths = [row["path"] for row in impact_rows]

    graph_paths = [
        f.get("f.path", "") for f in get_plan_impacted_files(store, plan_number) if f.get("f.path")
    ]
    planned = markdown_paths or graph_paths

    existing_on_disk: list[str] = []
    missing_on_disk: list[str] = []
    in_graph: list[str] = []
    not_in_graph: list[str] = []
    symbol_spot_checks: list[dict[str, Any]] = []

    graph_set = set(graph_paths)
    notes_by_path = {r["path"]: r.get("change_type", "") for r in impact_rows}
    for rel in planned:
        disk = root / rel
        if disk.is_file():
            existing_on_disk.append(rel)
            spot = _symbol_spot_check(disk, plan_text, notes_by_path.get(rel, ""), rel_path=rel)
            if spot:
                symbol_spot_checks.append(spot)
        else:
            missing_on_disk.append(rel)
        if rel in graph_set or _file_in_graph(store, rel):
            in_graph.append(rel)
        else:
            not_in_graph.append(rel)

    implemented_guess = len(existing_on_disk)
    missing_guess = len(missing_on_disk)
    card = build_plan_card(store, plan_number, root=root, plan_row=plan)

    return {
        "plan_number": plan_number,
        "plan_card": card,
        "planned_files": planned,
        "existing_on_disk": existing_on_disk,
        "missing_on_disk": missing_on_disk,
        "in_graph": in_graph,
        "not_in_graph": not_in_graph,
        "unchecked_steps": unchecked,
        "checked_steps": checked,
        "next_unchecked_step": next_step,
        "symbol_spot_checks": symbol_spot_checks,
        "summary": {
            "planned_count": len(planned),
            "existing_on_disk_count": implemented_guess,
            "missing_on_disk_count": missing_guess,
            "unchecked_steps": unchecked,
            "checked_steps": checked,
            "next_unchecked_step": next_step,
            "symbols_missing_in_existing_files": sum(
                1 for s in symbol_spot_checks if s.get("missing_symbols")
            ),
            "coarse_status": (
                "complete_looking"
                if missing_guess == 0 and unchecked == 0 and planned
                else "in_progress"
                if implemented_guess > 0 or checked > 0
                else "not_started"
            ),
        },
    }


def _symbol_spot_check(
    file_path: Path,
    plan_text: str,
    change_type: str,
    *,
    rel_path: str | None = None,
) -> dict[str, Any] | None:
    """Cheap export/name presence check for an existing planned file."""
    try:
        body = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    # Prefer CamelCase / snake_case tokens that also appear near the file path
    # mention in the plan; fall back to tokens from the filename stem.
    candidates: list[str] = []
    stem = file_path.stem
    if stem and stem not in _STOP and len(stem) > 2:
        candidates.append(stem)
    # Tokens from plan lines mentioning this path
    for line in plan_text.splitlines():
        if file_path.name in line or str(file_path).replace("\\", "/") in line.replace("\\", "/"):
            for tok in _IDENT.findall(line):
                if tok.lower() in _STOP or len(tok) < 4:
                    continue
                if tok[0].isupper() or "_" in tok:
                    candidates.append(tok)
    # Dedupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    uniq = uniq[:5]
    if not uniq:
        return None

    missing = [c for c in uniq if c not in body]
    found = [c for c in uniq if c in body]
    if not missing and not found:
        return None
    return {
        "path": rel_path or file_path.name,
        "change_type": change_type,
        "checked_symbols": uniq,
        "found_symbols": found,
        "missing_symbols": missing,
    }


def _file_in_graph(store: Any, path: str) -> bool:
    try:
        from agentscaffold.graph.query_compat import sql_escape

        esc = sql_escape(path)
        rows = store.query(f"SELECT id FROM File WHERE path = '{esc}' LIMIT 1")
        return bool(rows)
    except Exception:
        return False
