"""Selective pruning of governance knowledge from the graph.

Powers ``scaffold graph prune``. Selection is read-only and status-aware: only
resolved findings, archived backlog items, and sessions older than a cutoff are
ever eligible. Deletion is performed by ``apply_prune`` and is only invoked when
the caller explicitly opts in (the CLI defaults to a dry run).

Note on findings: the ``ReviewFinding`` table has no timestamp column, so the
age cutoff cannot be applied to findings -- selection is by ``resolved`` status
alone. Sessions and backlog items do carry timestamps and are filtered by age.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


def parse_age(spec: str) -> int:
    """Parse an age spec like ``"30d"`` into an integer day count.

    Raises ``ValueError`` for anything that is not a non-negative number of days.
    """
    text = spec.strip().lower()
    if not text.endswith("d"):
        raise ValueError(f"Invalid age '{spec}': expected a day count like '30d'.")
    try:
        days = int(text[:-1])
    except ValueError as exc:
        raise ValueError(f"Invalid age '{spec}': expected a day count like '30d'.") from exc
    if days < 0:
        raise ValueError(f"Invalid age '{spec}': must be non-negative.")
    return days


def _cutoff_iso(days: int) -> str:
    """Return the ISO-8601 cutoff timestamp for *days* ago (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _esc(value: str) -> str:
    return value.replace("'", "''")


def select_prunable(
    store: GraphBackend,
    *,
    resolved_findings_before: str | None = None,
    sessions_before: str | None = None,
    archived_backlog_before: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Select governance rows eligible for pruning. Read-only.

    Returns a dict with keys ``resolved_findings``, ``sessions``,
    ``archived_backlog`` mapping to lists of row dicts. Only categories whose
    corresponding ``*_before`` argument is provided are populated.
    """
    selection: dict[str, list[dict[str, Any]]] = {
        "resolved_findings": [],
        "sessions": [],
        "archived_backlog": [],
    }

    if resolved_findings_before is not None:
        # ReviewFinding has no timestamp; eligibility is by 'resolved' status only.
        # parse_age still validates the spec so the CLI surface stays consistent.
        parse_age(resolved_findings_before)
        selection["resolved_findings"] = store.query(
            "SELECT id, planNumber, severity, category FROM ReviewFinding WHERE status = 'resolved'"
        )

    if sessions_before is not None:
        cutoff = _cutoff_iso(parse_age(sessions_before))
        selection["sessions"] = store.query(
            f"SELECT id, date FROM Session WHERE date < '{_esc(cutoff)}'"
        )

    if archived_backlog_before is not None:
        cutoff = _cutoff_iso(parse_age(archived_backlog_before))
        selection["archived_backlog"] = store.query(
            "SELECT id, title, archivedAt FROM BacklogItem"
            f" WHERE status = 'archived' AND archivedAt < '{_esc(cutoff)}'"
        )

    return selection


def apply_prune(store: GraphBackend, selection: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Delete the selected rows and their edges. Mutating.

    Returns per-category deletion counts.
    """
    from agentscaffold.graph.backlog import delete_backlog_item
    from agentscaffold.graph.findings import delete_finding
    from agentscaffold.graph.sessions import delete_session

    counts = {"resolved_findings": 0, "sessions": 0, "archived_backlog": 0}

    for row in selection.get("resolved_findings", []):
        delete_finding(store, row["id"])
        counts["resolved_findings"] += 1
    for row in selection.get("sessions", []):
        delete_session(store, row["id"])
        counts["sessions"] += 1
    for row in selection.get("archived_backlog", []):
        delete_backlog_item(store, row["id"])
        counts["archived_backlog"] += 1

    return counts
