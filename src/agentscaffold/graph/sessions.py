"""Cross-session memory for the knowledge graph.

Tracks which files were modified, what plans were worked on, and provides
context continuity across coding sessions. Session data is stored as
Session nodes in the graph with edges to modified files.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.query_compat import ql, ql_execute, ql_scalar, sql_escape

logger = logging.getLogger(__name__)

_SESSION_SELECT = (
    'id AS "s.id", date AS "s.date", planNumbers AS "s.planNumbers", '
    'filesModified AS "s.filesModified", summary AS "s.summary", '
    'decisions AS "s.decisions", endedAt AS "s.endedAt", project AS "s.project"'
)

#: Appended to the summary of a session closed for inactivity.
AUTO_CLOSE_SUFFIX = " [closed: idle]"
#: Appended to the summary of a session closed by ``force_new``.
FORCE_NEW_SUFFIX = " [closed: force_new]"

_OPEN = "(endedAt IS NULL OR endedAt = '')"

_DECISION_STATUSES = frozenset({"observed", "inferred"})
_DECISION_KINDS = frozenset({"strategic", "architectural", "operational"})
_MAX_DECISIONS = 50


def _sync_governance(store: GraphBackend) -> None:
    """Re-serialize governance to the git-backed artifact if write-through is on."""
    from agentscaffold.graph.governance_store import sync_if_enabled  # noqa: PLC0415

    sync_if_enabled(store)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_clause(project: str | None) -> str:
    """Scoped read filter. Legacy rows written without a project stay visible."""
    if not project:
        return ""
    return f" AND COALESCE(project, '') IN ('{sql_escape(project)}', '')"


def _exact_project_clause(project: str | None) -> str:
    """Open-session lookup filter: only rows stamped with exactly *project*."""
    return f" AND COALESCE(project, '') = '{sql_escape(project or '')}'"


def _has_last_activity(store: GraphBackend) -> bool:
    """Whether the Session table has ``lastActivity`` yet.

    A read-only open of a graph that predates the column cannot add it, so
    age falls back to ``date`` until the next writable open heals it.
    """
    try:
        rows = ql(
            store,
            sql=(
                'SELECT COUNT(*) AS "n" FROM information_schema.columns '
                "WHERE table_name = 'Session' AND column_name = 'lastActivity'"
            ),
        )
    except Exception:  # noqa: BLE001 - treat an unreadable catalog as the old shape
        return False
    return bool(rows) and int(rows[0].get("n") or 0) > 0


def _activity_expr(store: GraphBackend) -> str:
    if _has_last_activity(store):
        return "COALESCE(NULLIF(lastActivity, ''), date)"
    return "date"


def _idle_cutoff(idle_hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=idle_hours)).isoformat()


def _active_clause(store: GraphBackend, idle_hours: float) -> str:
    """Exclude sessions idle for longer than *idle_hours* (``0`` disables)."""
    if not idle_hours or idle_hours <= 0:
        return ""
    return f" AND {_activity_expr(store)} >= '{sql_escape(_idle_cutoff(idle_hours))}'"


def _parse_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []


def _normalize_decisions(decisions: list[Any] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in decisions or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "inferred")
        if status not in _DECISION_STATUSES:
            status = "inferred"
        kind = str(item.get("kind") or "operational")
        if kind not in _DECISION_KINDS:
            kind = "operational"
        out.append(
            {
                "decision": str(item.get("decision") or ""),
                "evidence": str(item.get("evidence") or ""),
                "status": status,
                "kind": kind,
            }
        )
    return out


def _row_to_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("s.id", ""),
        "date": row.get("s.date", ""),
        "plan_numbers": _parse_json_list(row.get("s.planNumbers", "[]")),
        "files_modified": _parse_json_list(row.get("s.filesModified", "[]")),
        "summary": row.get("s.summary", "") or "",
        "decisions": _parse_json_list(row.get("s.decisions", "[]")),
        "ended_at": row.get("s.endedAt", "") or "",
        "project": row.get("s.project", "") or "",
        "last_activity": row.get("s.lastActivity", "") or row.get("s.date", "") or "",
    }


def _session_select(store: GraphBackend) -> str:
    if _has_last_activity(store):
        return f'{_SESSION_SELECT}, lastActivity AS "s.lastActivity"'
    return _SESSION_SELECT


def find_open_session(
    store: GraphBackend,
    *,
    project: str | None = None,
    exact_project: bool = False,
    idle_hours: float = 0,
) -> dict[str, Any] | None:
    """Return the most recent session with an empty ``endedAt``, or None.

    With ``exact_project`` only sessions stamped with exactly *project* match
    (an empty *project* matches legacy unstamped rows); otherwise an empty
    *project* matches any session. A positive *idle_hours* skips sessions with
    no activity for that long. Read-only: an idle session is skipped, not closed.
    """
    scope = _exact_project_clause(project) if exact_project else _project_clause(project)
    rows = ql(
        store,
        sql=(
            f"SELECT {_session_select(store)} FROM Session "
            f"WHERE {_OPEN}{scope}{_active_clause(store, idle_hours)} "
            f"ORDER BY date DESC LIMIT 1"
        ),
    )
    if not rows:
        return None
    return _row_to_session(rows[0])


def _close_open_sessions(store: GraphBackend, where: str, suffix: str) -> int:
    """Close every open session matching *where*, appending *suffix* to its summary."""
    ids = [
        str(row["id"])
        for row in ql(store, sql=f'SELECT id AS "id" FROM Session WHERE {_OPEN}{where}')
        if row.get("id")
    ]
    if not ids:
        return 0
    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    id_list = ", ".join(f"'{sql_escape(i)}'" for i in ids)
    with governance_write_lock(store):
        ql_execute(
            store,
            sql=(
                f"UPDATE Session SET endedAt = '{sql_escape(_now())}', "
                f"summary = COALESCE(summary, '') || '{sql_escape(suffix)}' "
                f"WHERE id IN ({id_list})"
            ),
        )
        _sync_governance(store)
    logger.info("Closed %d session(s)%s", len(ids), suffix)
    return len(ids)


def close_idle_sessions(store: GraphBackend, *, project: str | None, idle_hours: float) -> int:
    """Close sessions for *project*, and legacy unstamped ones, idle beyond *idle_hours*."""
    if not idle_hours or idle_hours <= 0:
        return 0
    where = (
        f" AND COALESCE(project, '') IN ('{sql_escape(project or '')}', '')"
        f" AND {_activity_expr(store)} < '{sql_escape(_idle_cutoff(idle_hours))}'"
    )
    return _close_open_sessions(store, where, AUTO_CLOSE_SUFFIX)


def touch_session(store: GraphBackend, *, project: str | None, idle_hours: float = 0) -> str | None:
    """Refresh ``lastActivity`` on the project's active open session; return its id."""
    session = find_open_session(store, project=project, exact_project=True, idle_hours=idle_hours)
    if not session or not session.get("id") or not _has_last_activity(store):
        return None
    session_id = str(session["id"])
    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        ql_execute(
            store,
            sql=(
                f"UPDATE Session SET lastActivity = '{sql_escape(_now())}' "
                f"WHERE id = '{sql_escape(session_id)}'"
            ),
        )
        _sync_governance(store)
    return session_id


def _merge_decisions(
    existing: list[Any],
    incoming: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged = [d for d in existing if isinstance(d, dict)]
    for item in incoming:
        if item not in merged:
            merged.append(item)
    if len(merged) <= _MAX_DECISIONS:
        return merged
    kept = merged[: _MAX_DECISIONS - 1]
    kept.append(
        {
            "decision": (
                f"truncated: {len(merged) - (_MAX_DECISIONS - 1)} further decisions dropped"
            ),
            "evidence": f"cap={_MAX_DECISIONS}",
            "status": "observed",
            "kind": "operational",
        }
    )
    return kept


def _write_decisions(store: GraphBackend, session_id: str, decisions: list[dict[str, str]]) -> None:
    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        ql_execute(
            store,
            sql=(
                f"UPDATE Session SET decisions = '{sql_escape(json.dumps(decisions))}' "
                f"WHERE id = '{sql_escape(session_id)}'"
            ),
        )
        _sync_governance(store)


def _merge_plan_numbers(
    store: GraphBackend,
    session_id: str,
    incoming: list[int] | None,
) -> None:
    if not incoming:
        return
    current = get_session(store, session_id).get("plan_numbers") or []
    merged = [n for n in current if isinstance(n, int)]
    for raw in incoming:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number not in merged:
            merged.append(number)
    if merged == current:
        return
    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        ql_execute(
            store,
            sql=(
                f"UPDATE Session SET planNumbers = '{sql_escape(json.dumps(merged))}' "
                f"WHERE id = '{sql_escape(session_id)}'"
            ),
        )
        _sync_governance(store)


def record_decision(
    store: GraphBackend,
    *,
    decision: str,
    evidence: str = "",
    status: str = "observed",
    kind: str = "operational",
    project: str | None = None,
    plan_numbers: list[int] | None = None,
    ensure_session: bool = True,
    source: str = "",
    idle_hours: float = 0,
) -> dict[str, Any]:
    """Append one typed decision to the open session.

    When ``ensure_session`` is true and none is open, start one. Only the
    explicit record-decision path should call this -- findings, backlog, and
    begin/complete plan stay on their own vertices.
    """
    normalized = _normalize_decisions(
        [
            {
                "decision": decision,
                "evidence": evidence,
                "status": status,
                "kind": kind,
            }
        ]
    )
    if not normalized or not normalized[0]["decision"]:
        return {"status": "rejected", "error": "decision is required"}

    close_idle_sessions(store, project=project, idle_hours=idle_hours)
    open_session = find_open_session(store, project=project, exact_project=True)
    if open_session and open_session.get("id"):
        session_id = str(open_session["id"])
    elif ensure_session:
        summary = f"opened by {source}" if source else "opened by record_decision"
        session_id = start_session(
            store,
            plan_numbers=plan_numbers,
            summary=summary,
            project=project,
            idle_hours=idle_hours,
        )
    else:
        return {"status": "no_session"}

    _merge_plan_numbers(store, session_id, plan_numbers)
    current = _parse_json_list(get_session(store, session_id).get("decisions", []))
    merged = _merge_decisions(current, normalized)
    _write_decisions(store, session_id, merged)
    touch_session(store, project=project)
    return {
        "status": "recorded",
        "id": session_id,
        "decision": normalized[0],
        "decision_count": len(merged),
    }


def start_session(
    store: GraphBackend,
    *,
    plan_numbers: list[int] | None = None,
    summary: str = "",
    project: str | None = None,
    force_new: bool = False,
    idle_hours: float = 0,
) -> str:
    """Create a new Session node and return its ID.

    If a session is already open for exactly the same project and has been
    active within *idle_hours*, return that id (refreshing its activity) instead
    of minting a second one. Idle sessions for the project, and idle legacy
    sessions with no project, are closed first. ``force_new`` closes the
    project's open session even when it is active.
    """
    close_idle_sessions(store, project=project, idle_hours=idle_hours)
    if force_new:
        _close_open_sessions(store, _exact_project_clause(project), FORCE_NEW_SUFFIX)
    existing = find_open_session(store, project=project, exact_project=True)
    if existing and existing.get("id"):
        logger.info("Reusing open session %s", existing["id"])
        touch_session(store, project=project)
        return str(existing["id"])

    session_id = f"session::{uuid.uuid4().hex[:12]}"
    now = _now()
    props: dict[str, Any] = {
        "id": session_id,
        "date": now,
        "planNumbers": json.dumps(plan_numbers or []),
        "filesModified": "[]",
        "summary": summary,
        "decisions": "[]",
        "endedAt": "",
    }
    if _has_last_activity(store):
        props["lastActivity"] = now
    if project:
        props["project"] = project

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.create_node("Session", props)
        _sync_governance(store)
    logger.info("Started session %s", session_id)
    return session_id


def record_modification(
    store: GraphBackend,
    session_id: str,
    file_path: str,
) -> None:
    """Record that a file was modified in the current session.

    Creates a SESSION_MODIFIED edge and updates the session's file list.
    Paths with no File vertex still join ``filesModified``; they do not get
    an edge (the vertex is missing until the next index).
    """
    _append_files_modified(store, session_id, [file_path])

    file_id = f"file::{file_path}"
    exists = ql_scalar(
        store,
        sql=f"SELECT COUNT(*) FROM File WHERE id = '{sql_escape(file_id)}'",
    )
    if not exists or int(exists) == 0:
        logger.debug("File %s not in graph, skipping SESSION_MODIFIED edge", file_path)
        return

    edge_exists = ql_scalar(
        store,
        sql=(
            f"SELECT COUNT(*) FROM SESSION_MODIFIED "
            f"WHERE src = '{sql_escape(session_id)}' AND dst = '{sql_escape(file_id)}'"
        ),
    )
    if edge_exists and int(edge_exists) > 0:
        return

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        store.create_edge("SESSION_MODIFIED", "Session", session_id, "File", file_id)
        _sync_governance(store)


def _append_files_modified(
    store: GraphBackend,
    session_id: str,
    file_paths: list[str],
) -> None:
    if not file_paths:
        return
    rows = ql(
        store,
        sql=(
            f'SELECT filesModified AS "s.filesModified" '
            f"FROM Session WHERE id = '{sql_escape(session_id)}'"
        ),
    )
    if not rows:
        return
    current = _parse_json_list(rows[0].get("s.filesModified", "[]"))
    changed = False
    for path in file_paths:
        if path and path not in current:
            current.append(path)
            changed = True
    if not changed:
        return
    updated = json.dumps(current)
    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        ql_execute(
            store,
            sql=(
                f"UPDATE Session SET filesModified = '{sql_escape(updated)}' "
                f"WHERE id = '{sql_escape(session_id)}'"
            ),
        )
        _sync_governance(store)


def end_session(
    store: GraphBackend,
    session_id: str = "",
    *,
    summary: str = "",
    decisions: list[Any] | None = None,
    plan_numbers: list[int] | None = None,
    files: list[str] | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Finalize a session and return its summary.

    An empty ``session_id`` closes the open session for ``project``.
    """
    if not session_id:
        open_session = find_open_session(store, project=project, exact_project=True)
        if not open_session or not open_session.get("id"):
            return {}
        session_id = str(open_session["id"])

    existing = get_session(store, session_id)
    assignments: list[str] = [f"endedAt = '{sql_escape(_now())}'"]
    if summary:
        assignments.append(f"summary = '{sql_escape(summary)}'")
    if decisions is not None:
        merged = _merge_decisions(
            existing.get("decisions") or [],
            _normalize_decisions(decisions),
        )
        assignments.append(f"decisions = '{sql_escape(json.dumps(merged))}'")
    if plan_numbers is not None:
        assignments.append(f"planNumbers = '{sql_escape(json.dumps(plan_numbers))}'")

    from agentscaffold.graph.governance_store import governance_write_lock  # noqa: PLC0415

    with governance_write_lock(store):
        ql_execute(
            store,
            sql=(
                f"UPDATE Session SET {', '.join(assignments)} WHERE id = '{sql_escape(session_id)}'"
            ),
        )
        _sync_governance(store)

    for path in files or []:
        record_modification(store, session_id, path)

    return get_session(store, session_id)


def get_session(store: GraphBackend, session_id: str) -> dict[str, Any]:
    """Retrieve a session's full data including modified files."""
    rows = ql(
        store,
        sql=(f"SELECT {_session_select(store)} FROM Session WHERE id = '{sql_escape(session_id)}'"),
    )
    if not rows:
        return {}
    return _row_to_session(rows[0])


def list_sessions(
    store: GraphBackend,
    *,
    limit: int = 10,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent sessions ordered by date (most recent first)."""
    safe_limit = max(1, int(limit))
    rows = ql(
        store,
        sql=(
            f"SELECT {_session_select(store)} FROM Session "
            f"WHERE 1=1{_project_clause(project)} "
            f"ORDER BY date DESC LIMIT {safe_limit}"
        ),
    )
    return [_row_to_session(row) for row in rows]


def session_decisions_for_plan(
    store: GraphBackend,
    plan_number: int,
    *,
    project: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Decisions from sessions that name ``plan_number``.

    This is the session-ledger slice of ``scaffold_decision_context``. Empty
    means unconfirmed on this store, not "no decisions exist in docs".
    """
    sessions = list_sessions(store, limit=200, project=project)
    wanted = int(plan_number)
    out: list[dict[str, Any]] = []
    for session in sessions:
        named: set[int] = set()
        for raw in session.get("plan_numbers") or []:
            try:
                named.add(int(raw))
            except (TypeError, ValueError):
                continue
        if wanted not in named:
            continue
        for item in session.get("decisions") or []:
            if not isinstance(item, dict) or not item.get("decision"):
                continue
            kind = str(item.get("kind") or "operational")
            if kind not in _DECISION_KINDS:
                kind = "operational"
            out.append(
                {
                    "session_id": session.get("id", ""),
                    "date": session.get("date", ""),
                    "kind": kind,
                    "decision": item.get("decision", ""),
                    "evidence": item.get("evidence", ""),
                    "status": item.get("status", "inferred"),
                }
            )
            if len(out) >= limit:
                return out
    return out


def get_session_context(
    store: GraphBackend,
    *,
    limit: int = 3,
    project: str | None = None,
) -> dict[str, Any]:
    """Build context from recent sessions for injection into templates/prompts.

    Returns a dict with recent session summaries and frequently modified files.
    """
    sessions = list_sessions(store, limit=limit, project=project)

    if not sessions:
        return {}

    file_counts: dict[str, int] = {}
    for s in sessions:
        for f in s.get("files_modified", []):
            file_counts[f] = file_counts.get(f, 0) + 1

    hot_session_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    plan_numbers: set[int] = set()
    for s in sessions:
        for p in s.get("plan_numbers", []):
            plan_numbers.add(p)

    return {
        "recent_sessions": sessions,
        "hot_session_files": hot_session_files,
        "recent_plan_numbers": sorted(plan_numbers),
        "session_count": len(sessions),
    }


def format_session_context_markdown(ctx: dict[str, Any]) -> str:
    """Format session context as markdown for template injection."""
    if not ctx:
        return ""

    lines = ["## Recent Session Context", ""]

    sessions = ctx.get("recent_sessions", [])
    if sessions:
        lines.append(f"**{len(sessions)} recent session(s)**:")
        lines.append("")
        for s in sessions:
            date = s.get("date", "unknown")[:10]
            summary = s.get("summary", "No summary")
            files = s.get("files_modified", [])
            plans = s.get("plan_numbers", [])
            plans_str = ", ".join(str(p) for p in plans) if plans else "none"
            lines.append(f"- **{date}** (plans: {plans_str}): {summary}")
            if files:
                lines.append(f"  Files: {', '.join(files[:5])}")
                if len(files) > 5:
                    lines.append(f"  (+{len(files) - 5} more)")
        lines.append("")

    hot = ctx.get("hot_session_files", [])
    if hot:
        lines.append("**Frequently modified files (across sessions)**:")
        lines.append("")
        for path, count in hot[:5]:
            lines.append(f"- `{path}` ({count}x)")
        lines.append("")

    return "\n".join(lines)


def delete_session(store: GraphBackend, session_id: str) -> None:
    """Delete a Session and its SESSION_MODIFIED edges.

    Used by selective pruning. Removes the session's edges first (src = id),
    then the node itself.
    """
    sid = sql_escape(session_id)
    try:
        store.execute(f"DELETE FROM SESSION_MODIFIED WHERE src = '{sid}'")
    except Exception:  # noqa: BLE001 - edge table may be absent
        pass
    store.execute(f"DELETE FROM Session WHERE id = '{sid}'")
