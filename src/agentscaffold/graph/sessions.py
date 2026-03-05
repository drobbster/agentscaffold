"""Cross-session memory for the knowledge graph.

Tracks which files were modified, what plans were worked on, and provides
context continuity across coding sessions. Session data is stored as
Session nodes in the graph with edges to modified files.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)


def start_session(
    store: GraphStore,
    *,
    plan_numbers: list[int] | None = None,
    summary: str = "",
) -> str:
    """Create a new Session node and return its ID.

    Call at the start of a coding session to begin tracking modifications.
    """
    session_id = f"session::{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    plans_str = json.dumps(plan_numbers or [])

    store.create_node(
        "Session",
        {
            "id": session_id,
            "date": now,
            "planNumbers": plans_str,
            "filesModified": "[]",
            "summary": summary,
        },
    )

    logger.info("Started session %s", session_id)
    return session_id


def record_modification(
    store: GraphStore,
    session_id: str,
    file_path: str,
) -> None:
    """Record that a file was modified in the current session.

    Creates a SESSION_MODIFIED edge and updates the session's file list.
    """
    file_id = f"file::{file_path}"

    # Check file exists in graph
    exists = store.query_scalar(f"MATCH (f:File) WHERE f.id = '{file_id}' RETURN count(f)")
    if not exists or int(exists) == 0:
        logger.debug("File %s not in graph, skipping session tracking", file_path)
        return

    # Check if edge already exists
    edge_exists = store.query_scalar(
        f"MATCH (s:Session)-[:SESSION_MODIFIED]->(f:File) "
        f"WHERE s.id = '{session_id}' AND f.id = '{file_id}' "
        f"RETURN count(*)"
    )
    if edge_exists and int(edge_exists) > 0:
        return

    store.create_edge("SESSION_MODIFIED", "Session", session_id, "File", file_id)

    # Update the filesModified list on the session node
    rows = store.query(f"MATCH (s:Session) WHERE s.id = '{session_id}' " f"RETURN s.filesModified")
    if rows:
        try:
            current = json.loads(rows[0].get("s.filesModified", "[]"))
        except (json.JSONDecodeError, TypeError):
            current = []

        if file_path not in current:
            current.append(file_path)
            updated = json.dumps(current)
            escaped = updated.replace("\\", "\\\\").replace("'", "\\'")
            store.execute(
                f"MATCH (s:Session) WHERE s.id = '{session_id}' "
                f"SET s.filesModified = '{escaped}'"
            )


def end_session(
    store: GraphStore,
    session_id: str,
    *,
    summary: str = "",
) -> dict[str, Any]:
    """Finalize a session and return its summary.

    Optionally updates the session summary text.
    """
    if summary:
        escaped = summary.replace("\\", "\\\\").replace("'", "\\'")
        store.execute(
            f"MATCH (s:Session) WHERE s.id = '{session_id}' " f"SET s.summary = '{escaped}'"
        )

    return get_session(store, session_id)


def get_session(store: GraphStore, session_id: str) -> dict[str, Any]:
    """Retrieve a session's full data including modified files."""
    rows = store.query(
        f"MATCH (s:Session) WHERE s.id = '{session_id}' "
        f"RETURN s.id, s.date, s.planNumbers, s.filesModified, s.summary"
    )
    if not rows:
        return {}

    row = rows[0]
    try:
        plans = json.loads(row.get("s.planNumbers", "[]"))
    except (json.JSONDecodeError, TypeError):
        plans = []
    try:
        files = json.loads(row.get("s.filesModified", "[]"))
    except (json.JSONDecodeError, TypeError):
        files = []

    return {
        "id": row.get("s.id", ""),
        "date": row.get("s.date", ""),
        "plan_numbers": plans,
        "files_modified": files,
        "summary": row.get("s.summary", ""),
    }


def list_sessions(
    store: GraphStore,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return recent sessions ordered by date (most recent first)."""
    rows = store.query(
        "MATCH (s:Session) "
        "RETURN s.id, s.date, s.planNumbers, s.filesModified, s.summary "
        f"ORDER BY s.date DESC LIMIT {limit}"
    )

    sessions = []
    for row in rows:
        try:
            plans = json.loads(row.get("s.planNumbers", "[]"))
        except (json.JSONDecodeError, TypeError):
            plans = []
        try:
            files = json.loads(row.get("s.filesModified", "[]"))
        except (json.JSONDecodeError, TypeError):
            files = []

        sessions.append(
            {
                "id": row.get("s.id", ""),
                "date": row.get("s.date", ""),
                "plan_numbers": plans,
                "files_modified": files,
                "summary": row.get("s.summary", ""),
            }
        )

    return sessions


def get_session_context(
    store: GraphStore,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    """Build context from recent sessions for injection into templates/prompts.

    Returns a dict with recent session summaries and frequently modified files.
    """
    sessions = list_sessions(store, limit=limit)

    if not sessions:
        return {}

    # Aggregate frequently modified files across recent sessions
    file_counts: dict[str, int] = {}
    for s in sessions:
        for f in s.get("files_modified", []):
            file_counts[f] = file_counts.get(f, 0) + 1

    hot_session_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Recent plan numbers
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
