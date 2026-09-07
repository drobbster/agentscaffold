"""Session brief for scaffold_orient (Plan 273).

Current work, blockers for that work, related items, and idle-next come
from an open Session and plan-file Status -- not the Current
Implementation diary table.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentscaffold.mcp.plan_card import build_plan_card
from agentscaffold.mcp.workflow_state import (
    blockers_that_name_focus,
    house_blockers_count,
)
from agentscaffold.review.filters import normalize_plan_status

_GATED = frozenset({"Draft", "Review", "Ready", "In Progress"})
_STATUS_LINE = re.compile(r"^-\s*Status:\s*(.+)$", re.MULTILINE)
_APPROVAL_LINE = re.compile(r"^-\s*Approval Required:\s*(.+)$", re.MULTILINE | re.IGNORECASE)

_IDLE_NEXT = {
    "action": "Nothing in flight; no gated plan found.",
    "tool": None,
    "arguments": {},
    "rationale": "no gated plan",
}


def build_session_brief(
    store: Any,
    *,
    root: Path,
    workflow: dict[str, Any],
    project: str | None = None,
    plan_number: int | None = None,
) -> dict[str, Any]:
    """Return the locked ``session_brief`` object."""
    from agentscaffold.graph.sessions import find_open_session

    session = find_open_session(store, project=project)
    candidate, source = _resolve_candidate(store, root, session, explicit=plan_number)
    card = None
    status = ""
    approval_required = False
    text = ""
    if candidate is not None:
        pn = int(candidate.get("p.number"))
        card = build_plan_card(store, pn, root=root, plan_row=candidate)
        text = _read_plan_text(root, candidate)
        status = _status_from_text(text, candidate.get("p.status") or "")
        if card is not None:
            inferred = _routing_status(card)
            if status == "Unknown":
                status = inferred
            card = {**card, "status_normalized": status}
        approval_required = _approval_required(text)

    in_flight = _is_in_flight(status, card)
    focus_pn = int(card["plan_number"]) if card is not None else None

    if in_flight and card is not None:
        current_work = _current_work(
            kind="in_flight",
            card=card,
            status=status,
            source=source,
            approval_required=approval_required,
        )
        nxt = _next_for(card, status, approval_required)
        related_pn = focus_pn
    elif card is not None:
        current_work = _idle_work()
        nxt = _next_for(card, status, approval_required)
        related_pn = focus_pn
    else:
        current_work = _idle_work()
        nxt = dict(_IDLE_NEXT)
        related_pn = None

    named = blockers_that_name_focus(workflow.get("blockers") or "", related_pn)
    blockers_for_work: list[dict[str, Any]] = []
    if approval_required and status in {"Draft", "Review"}:
        blockers_for_work.append(
            {
                "kind": "approval",
                "text": f"Plan {related_pn} requires approval (Status is {status}).",
            }
        )
    for bullet in named:
        blockers_for_work.append({"kind": "named_blocker", "text": bullet})

    open_finding_ids: list[str] = []
    open_backlog_ids: list[str] = []
    session_decisions: list[dict[str, Any]] = []
    if related_pn is not None:
        from agentscaffold.graph.backlog import get_backlog_items_for_plan
        from agentscaffold.graph.findings import get_open_findings
        from agentscaffold.graph.sessions import session_decisions_for_plan

        for row in get_open_findings(store, plan_number=related_pn, limit=5, project=project):
            fid = row.get("rf.id") or row.get("id")
            if fid:
                open_finding_ids.append(str(fid))
                blockers_for_work.append({"kind": "open_finding", "id": str(fid)})
        for row in get_backlog_items_for_plan(store, related_pn, project=project)[:3]:
            bid = row.get("bi.id") or row.get("id")
            if bid:
                open_backlog_ids.append(str(bid))
        session_decisions = session_decisions_for_plan(store, related_pn, project=project, limit=5)

    return {
        "current_work": current_work,
        "blockers_for_work": blockers_for_work,
        "related": {
            "open_finding_ids": open_finding_ids[:5],
            "open_backlog_ids": open_backlog_ids[:3],
            "session_decisions": session_decisions[:5],
        },
        "house_blockers_count": house_blockers_count(workflow.get("blockers") or "", related_pn),
        "next": nxt,
        "focus_plan": (
            current_work["plan_number"] if current_work["kind"] == "in_flight" else related_pn
        ),
    }


def compact_session_context(session: dict[str, Any] | None) -> dict[str, Any]:
    """Open session id, plan_numbers, last 3 decisions -- not the full ledger."""
    if not session:
        return {}
    decisions = session.get("decisions") or []
    if not isinstance(decisions, list):
        decisions = []
    return {
        "id": session.get("id"),
        "plan_numbers": session.get("plan_numbers") or [],
        "decisions": decisions[-3:],
        "session_count": 1,
    }


def _resolve_candidate(
    store: Any,
    root: Path,
    session: dict[str, Any] | None,
    *,
    explicit: int | None,
) -> tuple[dict[str, Any] | None, str]:
    from agentscaffold.review.queries import get_all_plans, get_plan_by_number

    if explicit is not None:
        row = get_plan_by_number(store, int(explicit))
        if row is not None:
            return row, "explicit"

    numbers = _session_plan_numbers(session)
    if numbers:
        for pn in sorted(numbers, reverse=True):
            row = get_plan_by_number(store, pn)
            if row is None:
                continue
            if _gated_status(store, root, row) in _GATED:
                return row, "open_session"

    for row in get_all_plans(store):
        if _gated_status(store, root, row) in _GATED:
            return row, "plan_status"
    return None, "none"


def _session_plan_numbers(session: dict[str, Any] | None) -> list[int]:
    if not session:
        return []
    out: list[int] = []
    for raw in session.get("plan_numbers") or []:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return out


def _gated_status(store: Any, root: Path, plan_row: dict[str, Any]) -> str:
    """Plan-file Status, else graph, else Execution Steps inference."""
    text = _read_plan_text(root, plan_row)
    status = _status_from_text(text, plan_row.get("p.status") or "")
    if status in _GATED or status == "Complete":
        return status
    pn = plan_row.get("p.number")
    if pn is None:
        return status
    card = build_plan_card(store, int(pn), root=root, plan_row=plan_row)
    if card is None:
        return status
    return _routing_status({**card, "status_normalized": "Unknown"})


def _read_plan_text(root: Path, plan_row: dict[str, Any]) -> str:
    path = plan_row.get("p.filePath") or plan_row.get("filePath") or ""
    if not path:
        return ""
    full = Path(path)
    if not full.is_absolute():
        full = root / path
    try:
        if full.is_file():
            return full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return ""


def _status_from_text(text: str, fallback: str) -> str:
    match = _STATUS_LINE.search(text or "")
    raw = match.group(1).strip() if match else (fallback or "")
    return normalize_plan_status(raw)


def _approval_required(text: str) -> bool:
    match = _APPROVAL_LINE.search(text or "")
    if not match:
        return False
    return match.group(1).strip().lower().startswith("yes")


def _routing_status(card: dict[str, Any]) -> str:
    status = card.get("status_normalized") or "Unknown"
    if status != "Unknown":
        return status
    unchecked = int(card.get("unchecked_steps") or 0)
    checked = int(card.get("checked_steps") or 0)
    if unchecked > 0 and checked > 0:
        return "In Progress"
    if unchecked > 0 and checked == 0:
        return "Draft"
    if unchecked == 0 and checked > 0:
        return "Complete"
    return "Unknown"


def _is_in_flight(status: str, card: dict[str, Any] | None) -> bool:
    if card is None:
        return False
    if status in {"In Progress", "Ready"}:
        return True
    checked = int(card.get("checked_steps") or 0)
    unchecked = int(card.get("unchecked_steps") or 0)
    return checked > 0 and unchecked > 0


def _idle_work() -> dict[str, Any]:
    return {
        "kind": "idle",
        "plan_number": None,
        "title": "",
        "status": "",
        "source": "none",
        "unchecked_steps": 0,
        "next_unchecked_step": None,
        "approval_required": False,
    }


def _current_work(
    *,
    kind: str,
    card: dict[str, Any],
    status: str,
    source: str,
    approval_required: bool,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "plan_number": card.get("plan_number"),
        "title": card.get("title") or "",
        "status": status,
        "source": source,
        "unchecked_steps": int(card.get("unchecked_steps") or 0),
        "next_unchecked_step": card.get("next_unchecked_step"),
        "approval_required": approval_required,
    }


def _next_for(
    card: dict[str, Any],
    status: str,
    approval_required: bool,
) -> dict[str, Any]:
    pn = card["plan_number"]
    if approval_required and status in {"Draft", "Review"}:
        return {
            "action": f"Present Plan {pn} for approval (do not implement).",
            "tool": "scaffold_begin_plan",
            "arguments": {"plan_number": pn, "dry_run": True},
            "rationale": "Approval Required and Status is still Draft/Review",
        }
    if status in {"Draft", "Review"}:
        return {
            "action": f"Run pre-implementation review for Plan {pn}.",
            "tool": "scaffold_begin_plan",
            "arguments": {"plan_number": pn, "dry_run": True},
            "rationale": "plan not yet through begin-plan / reviewedAt gate",
        }
    unchecked = int(card.get("unchecked_steps") or 0)
    if unchecked > 0:
        return {
            "action": f"Continue Plan {pn}: {unchecked} unchecked steps remain.",
            "tool": "scaffold_diff_plan_vs_code",
            "arguments": {"plan_number": pn},
            "rationale": "unchecked execution steps remain",
        }
    if status in {"Ready", "In Progress"} or (int(card.get("checked_steps") or 0) > 0):
        return {
            "action": f"Close out Plan {pn} with post-implementation review.",
            "tool": "scaffold_complete_plan",
            "arguments": {"plan_number": pn, "dry_run": True},
            "rationale": "no unchecked steps; ready for retro rehearsal",
        }
    return dict(_IDLE_NEXT)
