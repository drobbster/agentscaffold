"""Reusable graph query building blocks for the Dialectic Engine.

Each function returns structured data from the knowledge graph.
All functions accept a GraphStore and return plain dicts/lists,
keeping them independent of output formatting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore


# ---------------------------------------------------------------------------
# Dependency queries
# ---------------------------------------------------------------------------


def get_file_importers(store: GraphStore, file_path: str) -> list[dict[str, Any]]:
    """Return files that import the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return store.query(
        "MATCH (a:File)-[r:IMPORTS]->(b:File) "
        f"WHERE b.path = '{escaped}' "
        "RETURN a.path, a.language, r.importedNames"
    )


def get_file_importees(store: GraphStore, file_path: str) -> list[dict[str, Any]]:
    """Return files that the given file imports."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return store.query(
        "MATCH (a:File)-[r:IMPORTS]->(b:File) "
        f"WHERE a.path = '{escaped}' "
        "RETURN b.path, b.language, r.importedNames"
    )


def get_function_callers(store: GraphStore, file_path: str) -> list[dict[str, Any]]:
    """Return all functions in other files that call functions in the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return store.query(
        "MATCH (caller:Function)-[r:CALLS]->(callee:Function) "
        f"WHERE callee.filePath = '{escaped}' AND caller.filePath <> '{escaped}' "
        "RETURN DISTINCT caller.name, caller.filePath, callee.name, r.confidence"
    )


def get_transitive_consumers(
    store: GraphStore, file_path: str, depth: int = 2
) -> list[dict[str, Any]]:
    """Return files that transitively depend on the given file (up to depth hops)."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return store.query(
        f"MATCH (a:File)-[:IMPORTS*1..{depth}]->(b:File) "
        f"WHERE b.path = '{escaped}' AND a.path <> '{escaped}' "
        "RETURN DISTINCT a.path, a.language"
    )


def count_callers_for_function(store: GraphStore, func_id: str) -> int:
    """Count how many functions call the given function."""
    escaped = func_id.replace("\\", "\\\\").replace("'", "\\'")
    val = store.query_scalar(
        "MATCH (caller:Function)-[:CALLS]->(fn:Function) "
        f"WHERE fn.id = '{escaped}' "
        "RETURN count(DISTINCT caller)"
    )
    return int(val) if val else 0


# ---------------------------------------------------------------------------
# Governance queries
# ---------------------------------------------------------------------------


def get_plans_impacting_file(store: GraphStore, file_path: str) -> list[dict[str, Any]]:
    """Return plans that list the given file in their File Impact Map."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    file_id = f"file::{file_path}"
    escaped_id = file_id.replace("\\", "\\\\").replace("'", "\\'")
    results = store.query(
        "MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File) "
        f"WHERE f.id = '{escaped_id}' "
        "RETURN p.number, p.title, p.status, p.createdDate, r.changeType "
        "ORDER BY p.number DESC"
    )
    if not results:
        results = store.query(
            "MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File) "
            f"WHERE f.path = '{escaped}' "
            "RETURN p.number, p.title, p.status, p.createdDate, r.changeType "
            "ORDER BY p.number DESC"
        )
    return results


def get_learnings_for_file(store: GraphStore, file_path: str) -> list[dict[str, Any]]:
    """Return learnings that reference the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    file_id = f"file::{file_path}"
    escaped_id = file_id.replace("\\", "\\\\").replace("'", "\\'")
    results = store.query(
        "MATCH (lr:Learning)-[:LEARNING_RELATES_TO_FILE]->(f:File) "
        f"WHERE f.id = '{escaped_id}' "
        "RETURN lr.learningId, lr.planNumber, lr.description, lr.status"
    )
    if not results:
        results = store.query(
            "MATCH (lr:Learning)-[:LEARNING_RELATES_TO_FILE]->(f:File) "
            f"WHERE f.path = '{escaped}' "
            "RETURN lr.learningId, lr.planNumber, lr.description, lr.status"
        )
    return results


def get_findings_for_file(store: GraphStore, file_path: str) -> list[dict[str, Any]]:
    """Return review findings about the given file."""
    file_id = f"file::{file_path}"
    escaped_id = file_id.replace("\\", "\\\\").replace("'", "\\'")
    return store.query(
        "MATCH (rf:ReviewFinding)-[:FINDING_ABOUT_FILE]->(f:File) "
        f"WHERE f.id = '{escaped_id}' "
        "RETURN rf.reviewType, rf.planNumber, rf.category, rf.finding, "
        "rf.severity, rf.status"
    )


def get_contracts_for_file(store: GraphStore, file_path: str) -> list[dict[str, Any]]:
    """Return contracts whose declared functions/classes are in the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    func_contracts = store.query(
        "MATCH (c:Contract)-[:CONTRACT_DECLARES_FUNC]->(fn:Function) "
        f"WHERE fn.filePath = '{escaped}' "
        "RETURN DISTINCT c.name, c.version, c.filePath"
    )
    class_contracts = store.query(
        "MATCH (c:Contract)-[:CONTRACT_DECLARES_CLASS]->(cls:Class) "
        f"WHERE cls.filePath = '{escaped}' "
        "RETURN DISTINCT c.name, c.version, c.filePath"
    )
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for c in func_contracts + class_contracts:
        key = c.get("c.name", "")
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def get_file_layer(store: GraphStore, file_path: str) -> dict[str, Any] | None:
    """Return the architecture layer for the given file, if assigned."""
    file_id = f"file::{file_path}"
    escaped_id = file_id.replace("\\", "\\\\").replace("'", "\\'")
    rows = store.query(
        "MATCH (f:File)-[:BELONGS_TO_LAYER]->(l:ArchitectureLayer) "
        f"WHERE f.id = '{escaped_id}' "
        "RETURN l.number, l.name, l.description"
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Aggregate / analytics queries
# ---------------------------------------------------------------------------


def get_hot_files(store: GraphStore, limit: int = 10) -> list[dict[str, Any]]:
    """Return files with the most plan impacts (most-modified files)."""
    return store.query(
        "MATCH (p:Plan)-[:PLAN_IMPACTS]->(f:File) "
        "RETURN f.path, count(p) AS plan_count "
        "ORDER BY plan_count DESC "
        f"LIMIT {limit}"
    )


def get_volatile_modules(
    store: GraphStore, window_days: int = 30, min_plans: int = 3
) -> list[dict[str, Any]]:
    """Return files modified by many plans in a recent window (instability signal)."""
    return store.query(
        "MATCH (p:Plan)-[:PLAN_IMPACTS]->(f:File) "
        "RETURN f.path, count(p) AS plan_count "
        "ORDER BY plan_count DESC"
    )


def get_all_plans(store: GraphStore) -> list[dict[str, Any]]:
    """Return all plans ordered by number."""
    return store.query(
        "MATCH (p:Plan) RETURN p.number, p.title, p.status, p.planType, "
        "p.createdDate, p.lastUpdated "
        "ORDER BY p.number DESC"
    )


def get_plan_by_number(store: GraphStore, number: int) -> dict[str, Any] | None:
    """Return a single plan by its number."""
    rows = store.query(
        f"MATCH (p:Plan) WHERE p.number = {number} "
        "RETURN p.id, p.number, p.title, p.status, p.planType, "
        "p.filePath, p.createdDate, p.lastUpdated"
    )
    return rows[0] if rows else None


def get_plan_impacted_files(store: GraphStore, plan_number: int) -> list[dict[str, Any]]:
    """Return files listed in a plan's File Impact Map."""
    return store.query(
        f"MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File) WHERE p.number = {plan_number} "
        "RETURN f.path, f.language, r.changeType"
    )


def get_recurring_finding_patterns(
    store: GraphStore, min_occurrences: int = 2
) -> list[dict[str, Any]]:
    """Return review finding categories that appear repeatedly."""
    return store.query(
        "MATCH (rf:ReviewFinding) "
        "RETURN rf.category, count(rf) AS occurrences "
        f"HAVING occurrences >= {min_occurrences} "
        "ORDER BY occurrences DESC"
    )
