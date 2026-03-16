"""Reusable graph query building blocks for the Dialectic Engine.

Each function returns structured data from the knowledge graph.
All functions accept a GraphBackend and return plain dicts/lists,
keeping them independent of output formatting.

Step A.7: All queries dispatch through ql() / ql_scalar() (query_compat.py),
providing both KuzuDB Cypher and DuckPGQ SQL translations.  Column names in
returned dicts use the KuzuDB dot-qualified convention (e.g. ``"a.path"``)
so that consumers are backend-agnostic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentscaffold.graph.query_compat import is_duckpgq, ql, ql_scalar

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


# ---------------------------------------------------------------------------
# Dependency queries
# ---------------------------------------------------------------------------


def get_file_importers(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return files that import the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return ql(
        store,
        cypher=(
            "MATCH (a:File)-[r:IMPORTS]->(b:File) "
            f"WHERE b.path = '{escaped}' "
            "RETURN a.path, a.language, r.importedNames"
        ),
        sql=(
            'SELECT t.a_path AS "a.path",'
            ' t.a_language AS "a.language",'
            ' t.r_importedNames AS "r.importedNames"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:File)-[r:IMPORTS]->(b:File)"
            f" WHERE b.path = '{escaped}'"
            " COLUMNS (a.path AS a_path, a.language AS a_language,"
            " r.importedNames AS r_importedNames)) t"
        ),
    )


def get_file_importees(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return files that the given file imports."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return ql(
        store,
        cypher=(
            "MATCH (a:File)-[r:IMPORTS]->(b:File) "
            f"WHERE a.path = '{escaped}' "
            "RETURN b.path, b.language, r.importedNames"
        ),
        sql=(
            'SELECT t.b_path AS "b.path",'
            ' t.b_language AS "b.language",'
            ' t.r_importedNames AS "r.importedNames"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:File)-[r:IMPORTS]->(b:File)"
            f" WHERE a.path = '{escaped}'"
            " COLUMNS (b.path AS b_path, b.language AS b_language,"
            " r.importedNames AS r_importedNames)) t"
        ),
    )


def get_function_callers(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return all functions in other files that call functions in the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return ql(
        store,
        cypher=(
            "MATCH (caller:Function)-[r:CALLS]->(callee:Function) "
            f"WHERE callee.filePath = '{escaped}' AND caller.filePath <> '{escaped}' "
            "RETURN DISTINCT caller.name, caller.filePath, callee.name, r.confidence"
        ),
        sql=(
            "SELECT DISTINCT"
            ' t.caller_name AS "caller.name",'
            ' t.caller_filePath AS "caller.filePath",'
            ' t.callee_name AS "callee.name",'
            ' t.r_confidence AS "r.confidence"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (caller:Function)-[r:CALLS]->(callee:Function)"
            f" WHERE callee.filePath = '{escaped}' AND caller.filePath <> '{escaped}'"
            " COLUMNS (caller.name AS caller_name,"
            " caller.filePath AS caller_filePath,"
            " callee.name AS callee_name,"
            " r.confidence AS r_confidence)) t"
        ),
    )


def get_transitive_consumers(
    store: GraphBackend, file_path: str, depth: int = 2
) -> list[dict[str, Any]]:
    """Return files that transitively depend on the given file (up to depth hops)."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return ql(
        store,
        cypher=(
            f"MATCH (a:File)-[:IMPORTS*1..{depth}]->(b:File) "
            f"WHERE b.path = '{escaped}' AND a.path <> '{escaped}' "
            "RETURN DISTINCT a.path, a.language"
        ),
        sql=(
            'SELECT DISTINCT t.a_path AS "a.path",'
            ' t.a_language AS "a.language"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            f" MATCH (a:File)-[e:IMPORTS]->{{1,{depth}}}(b:File)"
            f" WHERE b.path = '{escaped}' AND a.path <> '{escaped}'"
            " COLUMNS (a.path AS a_path, a.language AS a_language)) t"
        ),
    )


def count_callers_for_function(store: GraphBackend, func_id: str) -> int:
    """Count how many functions call the given function."""
    escaped = func_id.replace("\\", "\\\\").replace("'", "\\'")
    val = ql_scalar(
        store,
        cypher=(
            "MATCH (caller:Function)-[:CALLS]->(fn:Function) "
            f"WHERE fn.id = '{escaped}' "
            "RETURN count(DISTINCT caller)"
        ),
        sql=f"SELECT COUNT(DISTINCT src) FROM CALLS WHERE dst = '{escaped}'",
    )
    return int(val) if val else 0


# ---------------------------------------------------------------------------
# Governance queries
# ---------------------------------------------------------------------------


def get_plans_impacting_file(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return plans that list the given file in their File Impact Map."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    if is_duckpgq(store):
        return store.query(
            'SELECT t.p_number AS "p.number",'
            ' t.p_title AS "p.title",'
            ' t.p_status AS "p.status",'
            ' t.p_createdDate AS "p.createdDate",'
            ' t.r_changeType AS "r.changeType"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File)"
            f" WHERE f.path = '{escaped}'"
            " COLUMNS (p.number AS p_number, p.title AS p_title,"
            " p.status AS p_status, p.createdDate AS p_createdDate,"
            " r.changeType AS r_changeType)) t"
            " ORDER BY t.p_number DESC"
        )
    # KuzuDB: try by canonical file id first, then fall back to path match
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


def get_learnings_for_file(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return learnings that reference the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    if is_duckpgq(store):
        return store.query(
            'SELECT t.lr_learningId AS "lr.learningId",'
            ' t.lr_planNumber AS "lr.planNumber",'
            ' t.lr_description AS "lr.description",'
            ' t.lr_status AS "lr.status"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (lr:Learning)-[e:LEARNING_RELATES_TO_FILE]->(f:File)"
            f" WHERE f.path = '{escaped}'"
            " COLUMNS (lr.learningId AS lr_learningId,"
            " lr.planNumber AS lr_planNumber,"
            " lr.description AS lr_description,"
            " lr.status AS lr_status)) t"
        )
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


def get_findings_for_file(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return review findings about the given file."""
    file_id = f"file::{file_path}"
    escaped_id = file_id.replace("\\", "\\\\").replace("'", "\\'")
    return ql(
        store,
        cypher=(
            "MATCH (rf:ReviewFinding)-[:FINDING_ABOUT_FILE]->(f:File) "
            f"WHERE f.id = '{escaped_id}' "
            "RETURN rf.reviewType, rf.planNumber, rf.category, rf.finding, "
            "rf.severity, rf.status"
        ),
        sql=(
            'SELECT t.rf_reviewType AS "rf.reviewType",'
            ' t.rf_planNumber AS "rf.planNumber",'
            ' t.rf_category AS "rf.category",'
            ' t.rf_finding AS "rf.finding",'
            ' t.rf_severity AS "rf.severity",'
            ' t.rf_status AS "rf.status"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File)"
            f" WHERE f.id = '{escaped_id}'"
            " COLUMNS (rf.reviewType AS rf_reviewType,"
            " rf.planNumber AS rf_planNumber,"
            " rf.category AS rf_category,"
            " rf.finding AS rf_finding,"
            " rf.severity AS rf_severity,"
            " rf.status AS rf_status)) t"
        ),
    )


def get_contracts_for_file(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return contracts whose declared functions/classes are in the given file."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    if is_duckpgq(store):
        func_contracts = store.query(
            'SELECT DISTINCT c.name AS "c.name",'
            ' c.version AS "c.version",'
            ' c.filePath AS "c.filePath"'
            " FROM CONTRACT_DECLARES_FUNC cdf"
            " JOIN Contract c ON c.id = cdf.src"
            " JOIN Function fn ON fn.id = cdf.dst"
            f" WHERE fn.filePath = '{escaped}'"
        )
        class_contracts = store.query(
            'SELECT DISTINCT c.name AS "c.name",'
            ' c.version AS "c.version",'
            ' c.filePath AS "c.filePath"'
            " FROM CONTRACT_DECLARES_CLASS cdc"
            " JOIN Contract c ON c.id = cdc.src"
            " JOIN Class cls ON cls.id = cdc.dst"
            f" WHERE cls.filePath = '{escaped}'"
        )
    else:
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


def get_file_layer(store: GraphBackend, file_path: str) -> dict[str, Any] | None:
    """Return the architecture layer for the given file, if assigned."""
    file_id = f"file::{file_path}"
    escaped_id = file_id.replace("\\", "\\\\").replace("'", "\\'")
    rows = ql(
        store,
        cypher=(
            "MATCH (f:File)-[:BELONGS_TO_LAYER]->(l:ArchitectureLayer) "
            f"WHERE f.id = '{escaped_id}' "
            "RETURN l.number, l.name, l.description"
        ),
        sql=(
            'SELECT t.l_number AS "l.number",'
            ' t.l_name AS "l.name",'
            ' t.l_description AS "l.description"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (f:File)-[e:BELONGS_TO_LAYER]->(l:ArchitectureLayer)"
            f" WHERE f.id = '{escaped_id}'"
            " COLUMNS (l.number AS l_number, l.name AS l_name,"
            " l.description AS l_description)) t"
        ),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Aggregate / analytics queries
# ---------------------------------------------------------------------------


def get_hot_files(store: GraphBackend, limit: int = 10) -> list[dict[str, Any]]:
    """Return files with the most plan impacts (most-modified files)."""
    return ql(
        store,
        cypher=(
            "MATCH (p:Plan)-[:PLAN_IMPACTS]->(f:File) "
            "RETURN f.path, count(p) AS plan_count "
            "ORDER BY plan_count DESC "
            f"LIMIT {limit}"
        ),
        sql=(
            'SELECT t.f_path AS "f.path", COUNT(*) AS plan_count'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[e:PLAN_IMPACTS]->(f:File)"
            " COLUMNS (f.path AS f_path)) t"
            " GROUP BY t.f_path"
            " ORDER BY plan_count DESC"
            f" LIMIT {limit}"
        ),
    )


def get_volatile_modules(
    store: GraphBackend, window_days: int = 30, min_plans: int = 3
) -> list[dict[str, Any]]:
    """Return files modified by many plans in a recent window (instability signal)."""
    return ql(
        store,
        cypher=(
            "MATCH (p:Plan)-[:PLAN_IMPACTS]->(f:File) "
            "RETURN f.path, count(p) AS plan_count "
            "ORDER BY plan_count DESC"
        ),
        sql=(
            'SELECT t.f_path AS "f.path", COUNT(*) AS plan_count'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[e:PLAN_IMPACTS]->(f:File)"
            " COLUMNS (f.path AS f_path)) t"
            " GROUP BY t.f_path"
            " ORDER BY plan_count DESC"
        ),
    )


def get_all_plans(store: GraphBackend) -> list[dict[str, Any]]:
    """Return all plans ordered by number."""
    return ql(
        store,
        cypher=(
            "MATCH (p:Plan) RETURN p.number, p.title, p.status, p.planType, "
            "p.createdDate, p.lastUpdated "
            "ORDER BY p.number DESC"
        ),
        sql=(
            'SELECT number AS "p.number", title AS "p.title",'
            ' status AS "p.status", planType AS "p.planType",'
            ' createdDate AS "p.createdDate", lastUpdated AS "p.lastUpdated"'
            " FROM Plan ORDER BY number DESC"
        ),
    )


def get_plan_by_number(store: GraphBackend, number: int) -> dict[str, Any] | None:
    """Return a single plan by its number."""
    rows = ql(
        store,
        cypher=(
            f"MATCH (p:Plan) WHERE p.number = {number} "
            "RETURN p.id, p.number, p.title, p.status, p.planType, "
            "p.filePath, p.createdDate, p.lastUpdated"
        ),
        sql=(
            'SELECT id AS "p.id", number AS "p.number",'
            ' title AS "p.title", status AS "p.status",'
            ' planType AS "p.planType", filePath AS "p.filePath",'
            ' createdDate AS "p.createdDate",'
            ' lastUpdated AS "p.lastUpdated"'
            f" FROM Plan WHERE number = {number}"
        ),
    )
    return rows[0] if rows else None


def get_plan_impacted_files(store: GraphBackend, plan_number: int) -> list[dict[str, Any]]:
    """Return files listed in a plan's File Impact Map."""
    return ql(
        store,
        cypher=(
            f"MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File) WHERE p.number = {plan_number} "
            "RETURN f.path, f.language, r.changeType"
        ),
        sql=(
            'SELECT t.f_path AS "f.path",'
            ' t.f_language AS "f.language",'
            ' t.r_changeType AS "r.changeType"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File)"
            f" WHERE p.number = {plan_number}"
            " COLUMNS (f.path AS f_path, f.language AS f_language,"
            " r.changeType AS r_changeType)) t"
        ),
    )


def get_recurring_finding_patterns(
    store: GraphBackend, min_occurrences: int = 2
) -> list[dict[str, Any]]:
    """Return review finding categories that appear repeatedly.

    Returns rows with keys ``category`` and ``occurrences``.
    """
    return ql(
        store,
        # KuzuDB does not support HAVING; use WITH ... WHERE instead.
        cypher=(
            "MATCH (rf:ReviewFinding) "
            "WITH rf.category AS category, count(rf) AS occurrences "
            f"WHERE occurrences >= {min_occurrences} "
            "RETURN category, occurrences "
            "ORDER BY occurrences DESC"
        ),
        sql=(
            "SELECT category, COUNT(*) AS occurrences"
            " FROM ReviewFinding"
            " GROUP BY category"
            f" HAVING COUNT(*) >= {min_occurrences}"
            " ORDER BY occurrences DESC"
        ),
    )


def get_plan_dependencies(store: GraphBackend, plan_number: int) -> list[dict[str, Any]]:
    """Return plans that the given plan depends on."""
    return ql(
        store,
        cypher=(
            f"MATCH (p:Plan)-[:DEPENDS_ON_PLAN]->(dep:Plan) WHERE p.number = {plan_number} "
            "RETURN dep.number, dep.title, dep.status"
        ),
        sql=(
            'SELECT t.dep_number AS "dep.number",'
            ' t.dep_title AS "dep.title",'
            ' t.dep_status AS "dep.status"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[e:DEPENDS_ON_PLAN]->(dep:Plan)"
            f" WHERE p.number = {plan_number}"
            " COLUMNS (dep.number AS dep_number,"
            " dep.title AS dep_title,"
            " dep.status AS dep_status)) t"
        ),
    )


# ---------------------------------------------------------------------------
# Study queries
# ---------------------------------------------------------------------------


def get_studies_for_plan(store: GraphBackend, plan_number: int) -> list[dict[str, Any]]:
    """Return studies that reference the given plan."""
    return ql(
        store,
        cypher=(
            f"MATCH (s:Study)-[:STUDY_REFERENCES_PLAN]->(p:Plan) WHERE p.number = {plan_number} "
            "RETURN s.studyId, s.title, s.status, s.outcome, s.confidence, s.tags"
        ),
        sql=(
            'SELECT t.s_studyId AS "s.studyId",'
            ' t.s_title AS "s.title",'
            ' t.s_status AS "s.status",'
            ' t.s_outcome AS "s.outcome",'
            ' t.s_confidence AS "s.confidence",'
            ' t.s_tags AS "s.tags"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (s:Study)-[e:STUDY_REFERENCES_PLAN]->(p:Plan)"
            f" WHERE p.number = {plan_number}"
            " COLUMNS (s.studyId AS s_studyId, s.title AS s_title,"
            " s.status AS s_status, s.outcome AS s_outcome,"
            " s.confidence AS s_confidence, s.tags AS s_tags)) t"
        ),
    )


def get_studies_by_tags(store: GraphBackend, tags: list[str]) -> list[dict[str, Any]]:
    """Return studies matching any of the given tags (substring match on tags field)."""
    cypher_conditions = " OR ".join(f"s.tags CONTAINS '{t}'" for t in tags)
    sql_conditions = " OR ".join(f"CONTAINS(tags, '{t}')" for t in tags)
    return ql(
        store,
        cypher=(
            f"MATCH (s:Study) WHERE {cypher_conditions} "
            "RETURN s.studyId, s.title, s.status, s.outcome, s.confidence, s.tags "
            "ORDER BY s.started DESC"
        ),
        sql=(
            'SELECT studyId AS "s.studyId",'
            ' title AS "s.title",'
            ' status AS "s.status",'
            ' outcome AS "s.outcome",'
            ' confidence AS "s.confidence",'
            ' tags AS "s.tags"'
            f" FROM Study WHERE {sql_conditions}"
            " ORDER BY started DESC"
        ),
    )


def get_studies_by_outcome(store: GraphBackend, outcome: str) -> list[dict[str, Any]]:
    """Return studies with a specific outcome."""
    escaped = outcome.replace("'", "\\'")
    return ql(
        store,
        cypher=(
            f"MATCH (s:Study) WHERE s.outcome = '{escaped}' "
            "RETURN s.studyId, s.title, s.status, s.outcome, s.confidence, s.tags "
            "ORDER BY s.started DESC"
        ),
        sql=(
            'SELECT studyId AS "s.studyId",'
            ' title AS "s.title",'
            ' status AS "s.status",'
            ' outcome AS "s.outcome",'
            ' confidence AS "s.confidence",'
            ' tags AS "s.tags"'
            f" FROM Study WHERE outcome = '{escaped}'"
            " ORDER BY started DESC"
        ),
    )


def get_studies_for_file(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return studies that reference the given file via artifact paths."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return ql(
        store,
        cypher=(
            "MATCH (s:Study)-[:STUDY_REFERENCES_FILE]->(f:File) "
            f"WHERE f.path = '{escaped}' "
            "RETURN s.studyId, s.title, s.status, s.outcome, s.tags"
        ),
        sql=(
            'SELECT t.s_studyId AS "s.studyId",'
            ' t.s_title AS "s.title",'
            ' t.s_status AS "s.status",'
            ' t.s_outcome AS "s.outcome",'
            ' t.s_tags AS "s.tags"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (s:Study)-[e:STUDY_REFERENCES_FILE]->(f:File)"
            f" WHERE f.path = '{escaped}'"
            " COLUMNS (s.studyId AS s_studyId, s.title AS s_title,"
            " s.status AS s_status, s.outcome AS s_outcome,"
            " s.tags AS s_tags)) t"
        ),
    )


def get_all_studies(store: GraphBackend) -> list[dict[str, Any]]:
    """Return all studies ordered by start date descending."""
    return ql(
        store,
        cypher=(
            "MATCH (s:Study) "
            "RETURN s.studyId, s.title, s.studyType, s.status, s.outcome, "
            "s.confidence, s.tags, s.started, s.completed "
            "ORDER BY s.started DESC"
        ),
        sql=(
            'SELECT studyId AS "s.studyId",'
            ' title AS "s.title",'
            ' studyType AS "s.studyType",'
            ' status AS "s.status",'
            ' outcome AS "s.outcome",'
            ' confidence AS "s.confidence",'
            ' tags AS "s.tags",'
            ' started AS "s.started",'
            ' completed AS "s.completed"'
            " FROM Study ORDER BY started DESC"
        ),
    )


# ---------------------------------------------------------------------------
# ADR queries
# ---------------------------------------------------------------------------


def get_adrs_for_plan(store: GraphBackend, plan_number: int) -> list[dict[str, Any]]:
    """Return ADRs that govern the given plan."""
    return ql(
        store,
        cypher=(
            f"MATCH (a:ADR)-[:ADR_GOVERNS]->(p:Plan) WHERE p.number = {plan_number} "
            "RETURN a.number, a.title, a.status, a.date"
        ),
        sql=(
            'SELECT t.a_number AS "a.number",'
            ' t.a_title AS "a.title",'
            ' t.a_status AS "a.status",'
            ' t.a_date AS "a.date"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:ADR)-[e:ADR_GOVERNS]->(p:Plan)"
            f" WHERE p.number = {plan_number}"
            " COLUMNS (a.number AS a_number, a.title AS a_title,"
            " a.status AS a_status, a.date AS a_date)) t"
        ),
    )


def get_adr_by_number(store: GraphBackend, number: int) -> dict[str, Any] | None:
    """Return a single ADR by number."""
    rows = ql(
        store,
        cypher=(
            f"MATCH (a:ADR) WHERE a.number = {number} "
            "RETURN a.id, a.number, a.title, a.status, a.date, a.filePath, "
            "a.relatedPlans, a.relatedADRs, a.supersededBy"
        ),
        sql=(
            'SELECT id AS "a.id",'
            ' number AS "a.number",'
            ' title AS "a.title",'
            ' status AS "a.status",'
            ' date AS "a.date",'
            ' filePath AS "a.filePath",'
            ' relatedPlans AS "a.relatedPlans",'
            ' relatedADRs AS "a.relatedADRs",'
            ' supersededBy AS "a.supersededBy"'
            f" FROM ADR WHERE number = {number}"
        ),
    )
    return rows[0] if rows else None


def get_all_adrs(store: GraphBackend) -> list[dict[str, Any]]:
    """Return all ADRs ordered by number."""
    return ql(
        store,
        cypher=(
            "MATCH (a:ADR) "
            "RETURN a.number, a.title, a.status, a.date, a.supersededBy "
            "ORDER BY a.number"
        ),
        sql=(
            'SELECT number AS "a.number",'
            ' title AS "a.title",'
            ' status AS "a.status",'
            ' date AS "a.date",'
            ' supersededBy AS "a.supersededBy"'
            " FROM ADR ORDER BY number"
        ),
    )


def get_superseded_adrs(store: GraphBackend) -> list[dict[str, Any]]:
    """Return ADRs that have been superseded."""
    return ql(
        store,
        cypher=(
            "MATCH (a:ADR) WHERE a.status CONTAINS 'Superseded' "
            "RETURN a.number, a.title, a.status, a.supersededBy"
        ),
        sql=(
            'SELECT number AS "a.number",'
            ' title AS "a.title",'
            ' status AS "a.status",'
            ' supersededBy AS "a.supersededBy"'
            " FROM ADR WHERE CONTAINS(status, 'Superseded')"
        ),
    )


def get_adrs_for_file(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return ADRs governing plans that impact this file (2-hop traversal)."""
    escaped = file_path.replace("\\", "\\\\").replace("'", "\\'")
    return ql(
        store,
        cypher=(
            "MATCH (a:ADR)-[:ADR_GOVERNS]->(p:Plan)-[:PLAN_IMPACTS]->(f:File) "
            f"WHERE f.path = '{escaped}' "
            "RETURN DISTINCT a.number, a.title, a.status, p.number AS plan_number"
        ),
        sql=(
            "SELECT DISTINCT"
            ' t.a_number AS "a.number",'
            ' t.a_title AS "a.title",'
            ' t.a_status AS "a.status",'
            ' t.p_number AS "plan_number"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:ADR)-[e1:ADR_GOVERNS]->(p:Plan)-[e2:PLAN_IMPACTS]->(f:File)"
            f" WHERE f.path = '{escaped}'"
            " COLUMNS (a.number AS a_number, a.title AS a_title,"
            " a.status AS a_status, p.number AS p_number)) t"
        ),
    )


# ---------------------------------------------------------------------------
# Spike queries
# ---------------------------------------------------------------------------


def get_spikes_for_plan(store: GraphBackend, plan_number: int) -> list[dict[str, Any]]:
    """Return spikes that validated the given plan."""
    return ql(
        store,
        cypher=(
            f"MATCH (sp:Spike)-[:SPIKE_FOR_PLAN]->(p:Plan) WHERE p.number = {plan_number} "
            "RETURN sp.title, sp.status, sp.created, sp.timeBox, sp.filePath"
        ),
        sql=(
            'SELECT t.sp_title AS "sp.title",'
            ' t.sp_status AS "sp.status",'
            ' t.sp_created AS "sp.created",'
            ' t.sp_timeBox AS "sp.timeBox",'
            ' t.sp_filePath AS "sp.filePath"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (sp:Spike)-[e:SPIKE_FOR_PLAN]->(p:Plan)"
            f" WHERE p.number = {plan_number}"
            " COLUMNS (sp.title AS sp_title, sp.status AS sp_status,"
            " sp.created AS sp_created, sp.timeBox AS sp_timeBox,"
            " sp.filePath AS sp_filePath)) t"
        ),
    )


def get_all_spikes(store: GraphBackend) -> list[dict[str, Any]]:
    """Return all spikes ordered by created date descending."""
    return ql(
        store,
        cypher=(
            "MATCH (sp:Spike) "
            "RETURN sp.title, sp.parentPlan, sp.status, sp.created, sp.timeBox "
            "ORDER BY sp.created DESC"
        ),
        sql=(
            'SELECT title AS "sp.title",'
            ' parentPlan AS "sp.parentPlan",'
            ' status AS "sp.status",'
            ' created AS "sp.created",'
            ' timeBox AS "sp.timeBox"'
            " FROM Spike ORDER BY created DESC"
        ),
    )


def get_spike_by_title(store: GraphBackend, title_fragment: str) -> list[dict[str, Any]]:
    """Return spikes matching a title keyword."""
    escaped = title_fragment.replace("'", "\\'")
    return ql(
        store,
        cypher=(
            f"MATCH (sp:Spike) WHERE sp.title CONTAINS '{escaped}' "
            "RETURN sp.title, sp.parentPlan, sp.status, sp.created, sp.filePath"
        ),
        sql=(
            'SELECT title AS "sp.title",'
            ' parentPlan AS "sp.parentPlan",'
            ' status AS "sp.status",'
            ' created AS "sp.created",'
            ' filePath AS "sp.filePath"'
            f" FROM Spike WHERE CONTAINS(title, '{escaped}')"
        ),
    )
