"""BacklogItem write-back logic.

Provides ``record_backlog_item()`` and ``resolve_backlog_item()`` that persist
BacklogItem nodes in the DuckPGQ knowledge graph.

BacklogItem IDs follow the existing project convention: ``B-{plan}-{seq}``.
The markdown files (backlog.md, backlog_archive.md, plan appendices) remain the
human-readable record -- graph writes are strictly additive.

Performance target: <200ms per write.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

_VALID_STATUSES = frozenset({"open", "blocked", "unblockable", "archived"})
_VALID_PRIORITIES = frozenset({"P1", "P2", "P3", "P4", "P5"})


def _sync_governance(store: GraphBackend) -> None:
    """Re-serialize governance to the git-backed artifact if write-through is on."""
    from agentscaffold.graph.governance_store import sync_if_enabled  # noqa: PLC0415

    sync_if_enabled(store)


def _backlog_id(plan_number: int, title: str, project: str | None = None) -> str:
    """Derive a deterministic, project-scoped ID from plan number + title.

    Plan numbers are NOT unique across projects in a multi-project workspace, so
    the project is folded into the hash key to prevent cross-project backlog-ID
    collisions. A falsy *project* reproduces the original (unscoped) ID for
    single-project back-compat.
    """
    prefix = f"{project}::" if project else ""
    key = f"{prefix}backlog::{plan_number}::{title[:64]}"
    return "bi::" + hashlib.sha1(key.encode()).hexdigest()[:12]  # noqa: S324


def record_backlog_item(
    store: GraphBackend,
    *,
    plan_number: int,
    title: str,
    priority: str = "P3",
    effort: str = "",
    source: str = "",
    status: str = "open",
    project: str | None = None,
) -> dict[str, Any]:
    """Record a backlog item in the knowledge graph.

    Creates a BacklogItem node and links it to the plan via a BACKLOG_ITEM_OF
    edge. Silently ignores duplicates (same plan_number + title).

    Args:
        store: Open GraphBackend instance.
        plan_number: The plan this item relates to (e.g. 133).
        title: Short description matching the title in backlog.md.
        priority: P1-P5 priority matching the backlog.md convention.
        effort: Effort estimate string (e.g. "Small (2h)").
        source: Review source reference (e.g. "DA Future Regret", "EX-8").
        status: Initial status -- "open", "blocked", or "unblockable".
        project: Owning project in a multi-project workspace; stamps the
            ``project`` column and scopes the deterministic ID and Plan lookup.
            None (single-project) keeps the original unscoped behavior.

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()
    item_id = _backlog_id(plan_number, title, project)
    now = datetime.now(timezone.utc).isoformat()
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""

    props: dict[str, Any] = {
        "id": item_id,
        "planNumber": plan_number,
        "title": title,
        "priority": priority,
        "effort": effort,
        "status": status,
        "source": source,
        "createdAt": now,
        "archivedAt": "",
        "project": project or "",
    }

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.create_node("BacklogItem", props)

        # Link to plan (scoped to the owning project: plan numbers are not unique
        # across projects in a multi-project workspace).
        plan_rows = store.query(f"SELECT id FROM Plan WHERE number = {plan_number}{proj_filter}")
        if plan_rows:
            store.create_edge("BACKLOG_ITEM_OF", "BacklogItem", item_id, "Plan", plan_rows[0]["id"])

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "id": item_id,
        "plan_number": plan_number,
        "title": title,
        "priority": priority,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "created_at": now,
    }


def record_backlog_items_batch(
    store: GraphBackend,
    *,
    plan_number: int,
    items: list[dict[str, Any]],
    project: str | None = None,
) -> dict[str, Any]:
    """Record multiple BacklogItem nodes in a single transaction.

    Each item in ``items`` must have a ``title`` key. Optional keys per item:
    ``priority``, ``effort``, ``source``, ``status``.

    Args:
        store: Open GraphBackend instance.
        plan_number: Plan number all items relate to.
        items: List of backlog item dicts.
        project: Owning project in a multi-project workspace; stamps the
            ``project`` column and scopes the deterministic IDs and Plan lookup.

    Returns:
        Dict with ``ids``, ``count``, and timing info.
    """
    t0 = time.monotonic()
    if not items:
        return {"ids": [], "count": 0, "elapsed_ms": 0.0}

    now = datetime.now(timezone.utc).isoformat()
    ids: list[str] = []
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""

    plan_rows = store.query(f"SELECT id FROM Plan WHERE number = {plan_number}{proj_filter}")
    plan_id = plan_rows[0]["id"] if plan_rows else None

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.execute("BEGIN TRANSACTION")
        try:
            for item in items:
                title = item.get("title", "")
                if not title:
                    continue
                item_id = _backlog_id(plan_number, title, project)
                props: dict[str, Any] = {
                    "id": item_id,
                    "planNumber": plan_number,
                    "title": title,
                    "priority": item.get("priority", "P3"),
                    "effort": item.get("effort", ""),
                    "status": item.get("status", "open"),
                    "source": item.get("source", ""),
                    "createdAt": now,
                    "archivedAt": "",
                    "project": project or "",
                }
                store.create_node("BacklogItem", props)
                if plan_id:
                    store.create_edge("BACKLOG_ITEM_OF", "BacklogItem", item_id, "Plan", plan_id)
                ids.append(item_id)

            store.execute("COMMIT")
        except Exception:
            store.execute("ROLLBACK")
            raise

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "ids": ids,
        "count": len(ids),
        "plan_number": plan_number,
        "elapsed_ms": elapsed_ms,
        "created_at": now,
    }


def resolve_backlog_item(
    store: GraphBackend,
    item_id: str,
    *,
    resolution: str = "",
    project: str | None = None,
) -> dict[str, Any]:
    """Mark a BacklogItem as archived (completed).

    Sets status to 'archived' and records the archived timestamp. The item
    remains in the graph for retrospective queries.

    Args:
        store: Open GraphBackend instance.
        item_id: The ID of the backlog item to archive.
        resolution: Optional note describing how the item was completed.
        project: When set, only archives the item if it belongs to this
            project (defense-in-depth against cross-project resolves).

    Returns:
        Dict with ``id``, ``status``, and timing info.
    """
    t0 = time.monotonic()
    now = datetime.now(timezone.utc).isoformat()
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.execute(
            f"UPDATE BacklogItem SET status = 'archived', archivedAt = '{now}'"
            f" WHERE id = '{_esc(item_id)}'{proj_filter}"
        )

        _sync_governance(store)

    elapsed_ms = (time.monotonic() - t0) * 1000
    return {
        "id": item_id,
        "status": "archived",
        "resolution": resolution,
        "archived_at": now,
        "elapsed_ms": elapsed_ms,
    }


def get_open_backlog_items(
    store: GraphBackend,
    *,
    plan_number: int | None = None,
    limit: int = 20,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Return open (non-archived) BacklogItems, optionally filtered by plan.

    Results are sorted by priority (P1 first).

    Args:
        store: Open GraphBackend instance.
        plan_number: If provided, filter to items for this plan only.
        limit: Maximum number of items to return.
        project: When set, only return items stamped with this project
            (multi-project scoping). None returns items regardless of project.

    Returns:
        List of backlog item dicts.
    """
    from agentscaffold.graph.query_compat import ql  # noqa: PLC0415

    plan_filter = f" AND planNumber = {plan_number}" if plan_number is not None else ""
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""
    rows = ql(
        store,
        sql=(
            f'SELECT id AS "bi.id", planNumber AS "bi.planNumber",'
            f' title AS "bi.title", priority AS "bi.priority",'
            f' effort AS "bi.effort", status AS "bi.status", source AS "bi.source"'
            f" FROM BacklogItem"
            f" WHERE status NOT IN ('archived', 'unblockable'){plan_filter}{proj_filter}"
            f" ORDER BY priority"
            f" LIMIT {limit}"
        ),
    )
    return rows


def get_backlog_items_for_plan(
    store: GraphBackend,
    plan_number: int,
    *,
    include_archived: bool = False,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Return all BacklogItems for a specific plan.

    Args:
        store: Open GraphBackend instance.
        plan_number: Plan number to filter by.
        include_archived: If True, include archived items.
        project: When set, only return items stamped with this project
            (multi-project scoping). None returns items regardless of project.

    Returns:
        List of backlog item dicts ordered by priority.
    """
    from agentscaffold.graph.query_compat import ql  # noqa: PLC0415

    status_filter = "" if include_archived else " AND status != 'archived'"
    proj_filter = f" AND project = '{_esc(project)}'" if project else ""
    rows = ql(
        store,
        sql=(
            f'SELECT id AS "bi.id", planNumber AS "bi.planNumber",'
            f' title AS "bi.title", priority AS "bi.priority",'
            f' effort AS "bi.effort", status AS "bi.status", source AS "bi.source"'
            f" FROM BacklogItem"
            f" WHERE planNumber = {plan_number}{status_filter}{proj_filter}"
            f" ORDER BY priority"
        ),
    )
    return rows


def delete_backlog_item(store: GraphBackend, item_id: str) -> None:
    """Delete a BacklogItem and its BACKLOG_ITEM_OF edges.

    Used by selective pruning. Removes the item's edges first (src = id), then
    the node itself.
    """
    iid = _esc(item_id)
    try:
        store.execute(f"DELETE FROM BACKLOG_ITEM_OF WHERE src = '{iid}'")
    except Exception:  # noqa: BLE001 - edge table may be absent
        pass
    store.execute(f"DELETE FROM BacklogItem WHERE id = '{iid}'")


def _esc(s: str) -> str:
    """Minimal SQL string escaping (single-quote doubling)."""
    return s.replace("'", "''")
