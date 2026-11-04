"""Live workflow_state.md parse for session routing (Plan 266).

Heading extraction is unchanged from the 0.11.0 orient helper. Focus and
blocker escalation no longer scan the whole diary for ``In Progress``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_HEADING_BLOCKERS = re.compile(r"^##\s+Blockers?\s*\n(.*?)(?=\n##\s|\Z)", re.MULTILINE | re.DOTALL)
_HEADING_NEXT = re.compile(r"^##\s+Next\s+Steps?\s*\n(.*?)(?=\n##\s|\Z)", re.MULTILINE | re.DOTALL)
_HEADING_CURRENT = re.compile(
    r"^##\s+Current\s+Implementation\s*\n(.*?)(?=\n##\s|\Z)", re.MULTILINE | re.DOTALL
)
_NEXT_ON_PLAN = re.compile(r"Next(?:\s+on\s+|:\s*)Plan\s+(\d+)", re.IGNORECASE)
_PLAN_NUM = re.compile(r"Plan\s+(\d+)\b", re.IGNORECASE)
_IN_PROGRESS = re.compile(r"Plan\s+(\d+).*?In\s*Progress", re.IGNORECASE)
_NEGATED_PROGRESS = re.compile(r"no longer|not\s+in\s*progress", re.IGNORECASE)
_DROPPED_BLOCKER = re.compile(r"\b(UNBLOCKED|RESOLVED)\b", re.IGNORECASE)
_BULLET = re.compile(r"^[-*]\s+")
_LAST_UPDATED = re.compile(r"Last\s+Updated\**\s*:\s*\**\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)

#: A diary not updated for longer than this is reported as stale (Plan 276).
STALE_AFTER_DAYS = 14
#: Plan statuses that contradict a diary listing the plan as in progress.
_FINISHED_STATUSES = frozenset({"Complete", "Superseded"})

_EMPTY_SECTION = frozenset({"", "none", "n/a", "-"})
_NEXT_STEPS_LINE_CAP = 80
_FOCUS_BULLET_CAP = 15
_EXCERPT_BULLETS = 2
_EXCERPT_CHARS = 400


def parse_workflow_file(root: Path, config: Any) -> dict[str, Any]:
    """Read ``workflow_state.md`` from *root* and return the structured parse."""
    if config and hasattr(config, "graph"):
        ws_path = root / config.graph.workflow_state_file
    else:
        ws_path = root / "docs" / "ai" / "state" / "workflow_state.md"

    if not ws_path.is_file():
        return {"error": "workflow_state.md not found", "path": str(ws_path)}

    result = parse_workflow_text(ws_path.read_text(errors="replace"))
    result["path"] = str(ws_path)
    return result


def parse_workflow_text(text: str, *, today: date | None = None) -> dict[str, Any]:
    """Parse workflow markdown into heading fields plus live routing signals."""
    result: dict[str, Any] = {
        "blockers": _section(_HEADING_BLOCKERS, text),
        "next_steps": _section(_HEADING_NEXT, text),
        "current_implementation": _section(_HEADING_CURRENT, text),
    }
    result.update(_staleness(text, today or datetime.now(timezone.utc).date()))
    focus_plans = extract_focus_plans(result)
    result["in_progress_plans"] = [str(n) for n in focus_plans]
    focus = focus_plans[0] if focus_plans else None
    result["live_blockers"] = blockers_that_name_focus(result["blockers"], focus)
    result["workflow_live"] = {
        "focus_plan": focus,
        "current_excerpt": current_excerpt(result["current_implementation"]),
        "live_blocker_count": len(result["live_blockers"]),
    }
    return result


def extract_focus_plans(workflow: dict[str, Any]) -> list[int]:
    """Return live plan numbers, first entry is the session-router focus."""
    current = workflow.get("current_implementation") or ""
    next_steps = workflow.get("next_steps") or ""

    found = _focus_from_section(current)
    if found:
        return found

    next_head = "\n".join((next_steps or "").splitlines()[:_NEXT_STEPS_LINE_CAP])
    found = _focus_from_section(next_head)
    if found:
        return found

    scoped = ""
    if not _is_empty_section(current):
        scoped += current + "\n"
    if not _is_empty_section(next_head):
        scoped += next_head
    return _in_progress_scoped(scoped)


def house_blockers_count(blockers_text: str, focus: int | None) -> int:
    """Live blocker bullets that do not name *focus* (standing inventory)."""
    live = _live_blocker_bullets(blockers_text)
    if focus is None:
        return len(live)
    named = _names_plan(focus)
    return sum(1 for bullet in live if not named.search(bullet))


def blockers_that_name_focus(blockers_text: str, focus: int | None) -> list[str]:
    """Non-struck live blocker bullets that mention *focus*.

    Standing inventory is left on ``workflow_state.blockers``. Priority-1
    escalation requires a focus plan and a bullet that names it.
    """
    if focus is None or _is_empty_section(blockers_text):
        return []
    named = _names_plan(focus)
    return [bullet for bullet in _live_blocker_bullets(blockers_text) if named.search(bullet)]


def find_contradictions(
    in_progress_plans: Iterable[Any], status_of: Callable[[int], str | None]
) -> list[dict[str, Any]]:
    """Plans the diary lists as in progress whose own Status says they are finished."""
    found: list[dict[str, Any]] = []
    for raw in in_progress_plans:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        status = status_of(number)
        if status in _FINISHED_STATUSES:
            found.append(
                {"plan_number": number, "workflow_state": "In Progress", "plan_status": status}
            )
    return found


def _staleness(text: str, today: date) -> dict[str, Any]:
    match = _LAST_UPDATED.search(text or "")
    if not match:
        return {"last_updated": None, "stale": None}
    try:
        updated = date.fromisoformat(match.group(1))
    except ValueError:
        return {"last_updated": None, "stale": None}
    return {
        "last_updated": updated.isoformat(),
        "stale": (today - updated).days > STALE_AFTER_DAYS,
    }


def _names_plan(focus: int) -> re.Pattern[str]:
    """Match "Plan 28" and its zero-padded forms ("Plan 028"), not "Plan 280"."""
    return re.compile(rf"\bPlan\s+0*{int(focus)}\b", re.IGNORECASE)


def current_excerpt(section: str) -> str:
    """First two live Current Implementation bullets, capped."""
    if _is_empty_section(section):
        return ""
    text = "\n".join(_non_struck_bullets(section)[:_EXCERPT_BULLETS])
    return text[:_EXCERPT_CHARS]


def _section(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    return match.group(1).strip() if match else "None"


def _is_empty_section(value: str) -> bool:
    return (value or "").strip().lower() in _EMPTY_SECTION


def _non_struck_bullets(section: str) -> list[str]:
    """Return bullets including indented continuation lines.

    Rebellion's live signal is often ``Next on Plan N`` on the line after
    the ``- `` marker. First-line-only collection would miss it.
    """
    bullets: list[str] = []
    current: list[str] = []
    for raw in (section or "").splitlines():
        stripped = raw.strip()
        if _BULLET.match(stripped):
            if current:
                bullets.append("\n".join(current))
            current = [stripped]
            continue
        if current and stripped:
            current.append(stripped)
    if current:
        bullets.append("\n".join(current))
    live: list[str] = []
    for bullet in bullets:
        first = bullet.splitlines()[0]
        body = _BULLET.sub("", first, count=1)
        if body.startswith("~~"):
            continue
        live.append(bullet)
    return live


def _live_blocker_bullets(blockers_text: str) -> list[str]:
    live: list[str] = []
    for bullet in _non_struck_bullets(blockers_text):
        if _DROPPED_BLOCKER.search(bullet):
            continue
        live.append(bullet)
    return live


def _focus_from_section(section: str) -> list[int]:
    if _is_empty_section(section):
        return []
    bullets = _non_struck_bullets(section)[:_FOCUS_BULLET_CAP]
    text = "\n".join(bullets)
    next_hits = _unique_ints(_NEXT_ON_PLAN.findall(text))
    if next_hits:
        return next_hits
    counts: Counter[int] = Counter()
    order: list[int] = []
    for match in _PLAN_NUM.finditer(text):
        number = int(match.group(1))
        if number not in counts:
            order.append(number)
        counts[number] += 1
    if not counts:
        return []
    winner = max(order, key=lambda n: (counts[n], -order.index(n)))
    rest = [n for n in order if n != winner]
    return [winner, *rest]


def _in_progress_scoped(text: str) -> list[int]:
    found: list[int] = []
    for line in (text or "").splitlines():
        if _NEGATED_PROGRESS.search(line):
            continue
        if line.strip().startswith("~~"):
            continue
        match = _IN_PROGRESS.search(line)
        if match:
            found.append(int(match.group(1)))
    return _unique_ints(found)


def _unique_ints(values: list[Any]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in values:
        number = int(raw)
        if number in seen:
            continue
        seen.add(number)
        out.append(number)
    return out
