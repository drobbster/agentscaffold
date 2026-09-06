"""Reusable graph query building blocks for the Dialectic Engine.

Each function returns structured data from the knowledge graph.
All functions accept a GraphBackend and return plain dicts/lists,
keeping them independent of output formatting.

All queries dispatch through ql() / ql_scalar() (query_compat.py),
executing SQL against the DuckPGQ backend.  Column names in returned
dicts use the dot-qualified convention (e.g. ``"a.path"``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentscaffold.graph.query_compat import ql, ql_scalar, sql_escape

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


# ---------------------------------------------------------------------------
# Project scoping (Plan 225)
#
# File paths and plan/study identifiers are NOT globally unique across the
# projects sharing one graph cache, so an unscoped governance read could surface
# another project's learnings/findings (misorientation). These helpers default
# to the *current* project in a multi-project workspace and are exact no-ops in
# a single-project repo, so existing callsites keep their behavior unchanged.
# Project names are validated to a safe charset, so inlining is injection-safe.
# ---------------------------------------------------------------------------


def _resolve_scope(project: str | None, all_projects: bool) -> Any:
    from agentscaffold.graph.scoping import resolve_scope

    return resolve_scope(project=project, all_projects=all_projects)


def _sql_scope(scope: Any, connector: str, column: str = "project") -> str:
    """Inline plain-SQL predicate (``WHERE``/``AND`` ``project = '<name>'``) or ''."""
    if getattr(scope, "is_noop", True):
        return ""
    return f" {connector} {column} = '{scope.project}'"


def _graph_scope(scope: Any, alias: str) -> str:
    """Inline ``GRAPH_TABLE`` predicate (`` AND <alias>.project = '<name>'``) or ''."""
    if getattr(scope, "is_noop", True):
        return ""
    return f" AND {alias}.project = '{scope.project}'"


def _provenance_select(scope: Any, alias: str, column: str = "project") -> str:
    """Trailing ``, project AS "<alias>.project"`` for federated reads, else ''.

    A federated read merges rows from several projects into one list, so without
    this the caller cannot tell which project any given row came from -- and a
    plan number or file path is not unique across projects. Emitted only when
    federating: a scoped read already knows its project, and a NULL provenance
    column on every row of a single-project graph reads as missing data.
    """
    if not getattr(scope, "is_federated", False):
        return ""
    return f', {column} AS "{alias}.project"'


# ---------------------------------------------------------------------------
# Dependency queries
# ---------------------------------------------------------------------------


def get_file_importers(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return files that import the given file."""
    escaped = sql_escape(file_path)
    return ql(
        store,
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
    escaped = sql_escape(file_path)
    return ql(
        store,
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
    escaped = sql_escape(file_path)
    return ql(
        store,
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
    """Return files that transitively depend on the given file (up to depth hops).

    Uses SQL joins instead of variable-length GRAPH_TABLE paths to avoid a
    DuckPGQ bug in IterativeLengthFunction with recursive path queries.
    """
    escaped = sql_escape(file_path)
    # Direct importers (depth=1)
    sql = (
        'SELECT DISTINCT f.path AS "a.path", f.language AS "a.language"'
        " FROM IMPORTS i JOIN File f ON i.src = f.id"
        " JOIN File target ON i.dst = target.id"
        f" WHERE target.path = '{escaped}' AND f.path <> '{escaped}'"
    )
    results = ql(store, sql=sql)
    if depth < 2:
        return results
    # Second-hop importers (depth=2): files that import direct importers
    direct_ids_sql = (
        "SELECT f.id FROM IMPORTS i JOIN File f ON i.src = f.id"
        " JOIN File target ON i.dst = target.id"
        f" WHERE target.path = '{escaped}' AND f.path <> '{escaped}'"
    )
    sql2 = (
        'SELECT DISTINCT f2.path AS "a.path", f2.language AS "a.language"'
        " FROM IMPORTS i2 JOIN File f2 ON i2.src = f2.id"
        f" WHERE i2.dst IN ({direct_ids_sql})"
        f" AND f2.path <> '{escaped}'"
    )
    results2 = ql(store, sql=sql2)
    # Deduplicate by path
    seen = {r["a.path"] for r in results}
    for r in results2:
        if r["a.path"] not in seen:
            results.append(r)
            seen.add(r["a.path"])
    return results


def count_callers_for_function(store: GraphBackend, func_id: str) -> int:
    """Count how many functions call the given function."""
    escaped = sql_escape(func_id)
    val = ql_scalar(
        store,
        sql=f"SELECT COUNT(DISTINCT src) FROM CALLS WHERE dst = '{escaped}'",
    )
    return int(val) if val else 0


# ---------------------------------------------------------------------------
# Governance queries
# ---------------------------------------------------------------------------


def get_plans_impacting_file(
    store: GraphBackend,
    file_path: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return plans that list the given file in their File Impact Map."""
    escaped = sql_escape(file_path)
    scope = _graph_scope(_resolve_scope(project, all_projects), "f")
    return store.query(
        'SELECT t.p_number AS "p.number",'
        ' t.p_title AS "p.title",'
        ' t.p_status AS "p.status",'
        ' t.p_createdDate AS "p.createdDate",'
        ' t.r_changeType AS "r.changeType"'
        " FROM GRAPH_TABLE(agentscaffold_graph"
        " MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File)"
        f" WHERE f.path = '{escaped}'{scope}"
        " COLUMNS (p.number AS p_number, p.title AS p_title,"
        " p.status AS p_status, p.createdDate AS p_createdDate,"
        " r.changeType AS r_changeType)) t"
        " ORDER BY t.p_number DESC"
    )


def get_learnings_for_file(
    store: GraphBackend,
    file_path: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return learnings that reference the given file."""
    escaped = sql_escape(file_path)
    scope = _graph_scope(_resolve_scope(project, all_projects), "f")
    return store.query(
        'SELECT t.lr_learningId AS "lr.learningId",'
        ' t.lr_planNumber AS "lr.planNumber",'
        ' t.lr_description AS "lr.description",'
        ' t.lr_status AS "lr.status"'
        " FROM GRAPH_TABLE(agentscaffold_graph"
        " MATCH (lr:Learning)-[e:LEARNING_RELATES_TO_FILE]->(f:File)"
        f" WHERE f.path = '{escaped}'{scope}"
        " COLUMNS (lr.learningId AS lr_learningId,"
        " lr.planNumber AS lr_planNumber,"
        " lr.description AS lr_description,"
        " lr.status AS lr_status)) t"
    )


def get_findings_for_file(
    store: GraphBackend,
    file_path: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return review findings about the given file.

    Matches on ``f.path`` (identical across single/multi-project) rather than the
    node id, which becomes project-qualified when multiple projects share the
    cache; the project predicate then disambiguates a path shared by siblings.
    """
    escaped = sql_escape(file_path)
    scope = _graph_scope(_resolve_scope(project, all_projects), "f")
    return ql(
        store,
        sql=(
            'SELECT t.rf_reviewType AS "rf.reviewType",'
            ' t.rf_planNumber AS "rf.planNumber",'
            ' t.rf_category AS "rf.category",'
            ' t.rf_finding AS "rf.finding",'
            ' t.rf_severity AS "rf.severity",'
            ' t.rf_status AS "rf.status",'
            ' t.rf_evidenceKind AS "rf.evidenceKind",'
            ' t.rf_evidence AS "rf.evidence"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File)"
            f" WHERE f.path = '{escaped}'{scope}"
            " COLUMNS (rf.reviewType AS rf_reviewType,"
            " rf.planNumber AS rf_planNumber,"
            " rf.category AS rf_category,"
            " rf.finding AS rf_finding,"
            " rf.severity AS rf_severity,"
            " rf.status AS rf_status,"
            " rf.evidenceKind AS rf_evidenceKind,"
            " rf.evidence AS rf_evidence)) t"
        ),
    )


def get_contracts_for_file(store: GraphBackend, file_path: str) -> list[dict[str, Any]]:
    """Return contracts covering the given file.

    Prefers the direct ``CONTRACT_ABOUT_FILE`` edge (Plan 237); falls back to the
    declares-join (contracts whose declared functions/classes live in the file) so
    graphs indexed before the edge existed still resolve.
    """
    escaped = sql_escape(file_path)

    direct = store.query(
        'SELECT DISTINCT c.name AS "c.name",'
        ' c.version AS "c.version",'
        ' c.filePath AS "c.filePath"'
        " FROM CONTRACT_ABOUT_FILE caf"
        " JOIN Contract c ON c.id = caf.src"
        " JOIN File f ON f.id = caf.dst"
        f" WHERE f.path = '{escaped}'"
    )
    if direct:
        seen_direct: set[str] = set()
        result_direct: list[dict[str, Any]] = []
        for c in direct:
            key = c.get("c.name", "")
            if key not in seen_direct:
                seen_direct.add(key)
                result_direct.append(c)
        return result_direct

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
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for c in func_contracts + class_contracts:
        key = c.get("c.name", "")
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def get_file_layer(
    store: GraphBackend,
    file_path: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> dict[str, Any] | None:
    """Return the architecture layer for the given file, if assigned."""
    escaped = sql_escape(file_path)
    scope = _graph_scope(_resolve_scope(project, all_projects), "f")
    rows = ql(
        store,
        sql=(
            'SELECT t.l_number AS "l.number",'
            ' t.l_name AS "l.name",'
            ' t.l_description AS "l.description"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (f:File)-[e:BELONGS_TO_LAYER]->(l:ArchitectureLayer)"
            f" WHERE f.path = '{escaped}'{scope}"
            " COLUMNS (l.number AS l_number, l.name AS l_name,"
            " l.description AS l_description)) t"
        ),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Aggregate / analytics queries
# ---------------------------------------------------------------------------


def get_hot_files(
    store: GraphBackend,
    limit: int = 10,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return files with the most plan impacts (most-modified files)."""
    scope = _resolve_scope(project, all_projects)
    where = "" if getattr(scope, "is_noop", True) else f" WHERE f.project = '{scope.project}'"
    return ql(
        store,
        sql=(
            'SELECT t.f_path AS "f.path", COUNT(*) AS plan_count'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[e:PLAN_IMPACTS]->(f:File)"
            f"{where}"
            " COLUMNS (f.path AS f_path)) t"
            " GROUP BY t.f_path"
            " ORDER BY plan_count DESC"
            f" LIMIT {limit}"
        ),
    )


def get_volatile_modules(
    store: GraphBackend,
    window_days: int = 30,
    min_plans: int = 3,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return files modified by many plans in a recent window (instability signal)."""
    scope = _resolve_scope(project, all_projects)
    where = "" if getattr(scope, "is_noop", True) else f" WHERE f.project = '{scope.project}'"
    return ql(
        store,
        sql=(
            'SELECT t.f_path AS "f.path", COUNT(*) AS plan_count'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[e:PLAN_IMPACTS]->(f:File)"
            f"{where}"
            " COLUMNS (f.path AS f_path)) t"
            " GROUP BY t.f_path"
            " ORDER BY plan_count DESC"
        ),
    )


def get_all_plans(
    store: GraphBackend,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return all plans ordered by number (scoped to the current project)."""
    scope = _sql_scope(_resolve_scope(project, all_projects), "WHERE")
    return ql(
        store,
        sql=(
            'SELECT number AS "p.number", title AS "p.title",'
            ' status AS "p.status", planType AS "p.planType",'
            ' filePath AS "p.filePath",'
            ' createdDate AS "p.createdDate", lastUpdated AS "p.lastUpdated"'
            f" FROM Plan{scope} ORDER BY number DESC"
        ),
    )


def get_plan_by_number(
    store: GraphBackend,
    number: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> dict[str, Any] | None:
    """Return a single plan by its number (scoped to the current project)."""
    scope = _sql_scope(_resolve_scope(project, all_projects), "AND")
    rows = ql(
        store,
        sql=(
            'SELECT id AS "p.id", number AS "p.number",'
            ' title AS "p.title", status AS "p.status",'
            ' planType AS "p.planType", filePath AS "p.filePath",'
            ' createdDate AS "p.createdDate",'
            ' lastUpdated AS "p.lastUpdated"'
            f" FROM Plan WHERE number = {number}{scope}"
        ),
    )
    return rows[0] if rows else None


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _closed_range(start: Any, end: Any) -> tuple[int, int] | None:
    lo = _as_optional_int(start)
    hi = _as_optional_int(end)
    if lo is None and hi is None:
        return None
    if lo is None:
        lo = hi
    if hi is None:
        hi = lo
    if lo is None or hi is None:
        return None
    if lo > hi:
        lo, hi = hi, lo
    return (lo, hi)


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return not (left[1] < right[0] or right[1] < left[0])


def _direction_summary(
    src_id: str,
    dst_id: str,
    plan_edges: list[tuple[str, str]],
    step_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe one A→B direction: unqualified, dest range, and/or src range."""
    has_plan = any(src == src_id and dst == dst_id for src, dst in plan_edges)
    dest_range: tuple[int, int] | None = None
    src_range: tuple[int, int] | None = None
    for edge in step_edges:
        if edge["src"] != src_id or edge["dst"] != dst_id:
            continue
        dest = _closed_range(edge.get("toStep"), edge.get("toStepEnd"))
        src = _closed_range(edge.get("fromStep"), edge.get("fromStepEnd"))
        if dest is not None:
            dest_range = dest
        if src is not None:
            src_range = src
    unqualified = has_plan or (dest_range is None and src_range is None and has_plan)
    if has_plan:
        dest_range = None
        src_range = None
        unqualified = True
    elif dest_range is None and src_range is None:
        unqualified = False
    present = has_plan or dest_range is not None or src_range is not None
    return {
        "present": present,
        "unqualified": unqualified and present,
        "dest_range": dest_range,
        "src_range": src_range,
    }


def plan_dependency_cycle(
    store: GraphBackend,
    plan_a: int,
    plan_b: int,
) -> dict[str, Any]:
    """Pairwise apparent vs genuine cycle for two plans (Plan 265).

    ``none`` if the pair is not mutually dependent. ``genuine`` if both
    directions wait on the other without disjoint step ranges. ``apparent``
    if a prefix/suffix handshake dissolves the plan-level loop.
    """
    empty = {"status": "none", "ranges": []}
    row_a = get_plan_by_number(store, plan_a)
    row_b = get_plan_by_number(store, plan_b)
    if not row_a or not row_b:
        return empty
    id_a = str(row_a.get("p.id") or "")
    id_b = str(row_b.get("p.id") or "")
    if not id_a or not id_b:
        return empty

    ea = sql_escape(id_a)
    eb = sql_escape(id_b)
    pair = f"WHERE (src = '{ea}' AND dst = '{eb}') OR (src = '{eb}' AND dst = '{ea}')"
    plan_rows = store.query(f"SELECT src, dst FROM DEPENDS_ON_PLAN {pair}")
    step_rows = store.query(
        f"SELECT src, dst, fromStep, fromStepEnd, toStep, toStepEnd FROM DEPENDS_ON_STEPS {pair}"
    )
    plan_edges = [(str(r["src"]), str(r["dst"])) for r in (plan_rows or [])]
    step_edges = [
        {
            "src": str(r["src"]),
            "dst": str(r["dst"]),
            "fromStep": r.get("fromStep"),
            "fromStepEnd": r.get("fromStepEnd"),
            "toStep": r.get("toStep"),
            "toStepEnd": r.get("toStepEnd"),
        }
        for r in (step_rows or [])
    ]

    a_to_b = _direction_summary(id_a, id_b, plan_edges, step_edges)
    b_to_a = _direction_summary(id_b, id_a, plan_edges, step_edges)
    if not a_to_b["present"] or not b_to_a["present"]:
        return empty

    ranges: list[dict[str, Any]] = []
    if a_to_b["dest_range"]:
        ranges.append({"from": plan_a, "to": plan_b, "to_steps": list(a_to_b["dest_range"])})
    if a_to_b["src_range"]:
        ranges.append({"from": plan_a, "to": plan_b, "from_steps": list(a_to_b["src_range"])})
    if b_to_a["dest_range"]:
        ranges.append({"from": plan_b, "to": plan_a, "to_steps": list(b_to_a["dest_range"])})
    if b_to_a["src_range"]:
        ranges.append({"from": plan_b, "to": plan_a, "from_steps": list(b_to_a["src_range"])})

    if a_to_b["unqualified"] or b_to_a["unqualified"]:
        return {"status": "genuine", "ranges": ranges}

    handshake_on_b = (
        a_to_b["dest_range"] is not None
        and b_to_a["src_range"] is not None
        and not _ranges_overlap(a_to_b["dest_range"], b_to_a["src_range"])
    )
    handshake_on_a = (
        b_to_a["dest_range"] is not None
        and a_to_b["src_range"] is not None
        and not _ranges_overlap(b_to_a["dest_range"], a_to_b["src_range"])
    )
    if handshake_on_b or handshake_on_a:
        return {"status": "apparent", "ranges": ranges}
    return {"status": "genuine", "ranges": ranges}


def get_plan_impacted_files(
    store: GraphBackend,
    plan_number: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return files listed in a plan's File Impact Map."""
    scope = _graph_scope(_resolve_scope(project, all_projects), "p")
    return ql(
        store,
        sql=(
            'SELECT t.f_path AS "f.path",'
            ' t.f_language AS "f.language",'
            ' t.r_changeType AS "r.changeType"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[r:PLAN_IMPACTS]->(f:File)"
            f" WHERE p.number = {plan_number}{scope}"
            " COLUMNS (f.path AS f_path, f.language AS f_language,"
            " r.changeType AS r_changeType)) t"
        ),
    )


def get_recurring_finding_patterns(
    store: GraphBackend,
    min_occurrences: int = 2,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return review finding categories that appear repeatedly.

    Returns rows with keys ``category`` and ``occurrences``.
    """
    scope = _sql_scope(_resolve_scope(project, all_projects), "WHERE")
    return ql(
        store,
        sql=(
            "SELECT category, COUNT(*) AS occurrences"
            f" FROM ReviewFinding{scope}"
            " GROUP BY category"
            f" HAVING COUNT(*) >= {min_occurrences}"
            " ORDER BY occurrences DESC"
        ),
    )


def get_plan_projects(store: GraphBackend, number: int) -> list[str]:
    """Return every project owning a plan with this number, across the workspace.

    Plan numbers are allocated per project, so the same number routinely names
    different plans in different projects. Callers that federate need to know
    whether a number is unique before answering with one project's plan.
    """
    rows = ql(
        store,
        sql=f'SELECT DISTINCT project AS "p.project" FROM Plan WHERE number = {number}',
    )
    return sorted({str(r.get("p.project")) for r in rows if r.get("p.project")})


def get_plan_dependencies(
    store: GraphBackend,
    plan_number: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return plans that the given plan depends on."""
    scope = _graph_scope(_resolve_scope(project, all_projects), "p")
    return ql(
        store,
        sql=(
            'SELECT t.dep_number AS "dep.number",'
            ' t.dep_title AS "dep.title",'
            ' t.dep_status AS "dep.status"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (p:Plan)-[e:DEPENDS_ON_PLAN]->(dep:Plan)"
            f" WHERE p.number = {plan_number}{scope}"
            " COLUMNS (dep.number AS dep_number,"
            " dep.title AS dep_title,"
            " dep.status AS dep_status)) t"
        ),
    )


# ---------------------------------------------------------------------------
# Study queries
# ---------------------------------------------------------------------------


def get_studies_for_plan(
    store: GraphBackend,
    plan_number: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return studies that reference the given plan."""
    scope = _graph_scope(_resolve_scope(project, all_projects), "p")
    return ql(
        store,
        sql=(
            'SELECT t.s_studyId AS "s.studyId",'
            ' t.s_title AS "s.title",'
            ' t.s_status AS "s.status",'
            ' t.s_outcome AS "s.outcome",'
            ' t.s_confidence AS "s.confidence",'
            ' t.s_tags AS "s.tags"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (s:Study)-[e:STUDY_REFERENCES_PLAN]->(p:Plan)"
            f" WHERE p.number = {plan_number}{scope}"
            " COLUMNS (s.studyId AS s_studyId, s.title AS s_title,"
            " s.status AS s_status, s.outcome AS s_outcome,"
            " s.confidence AS s_confidence, s.tags AS s_tags)) t"
        ),
    )


def get_studies_by_tags(
    store: GraphBackend,
    tags: list[str],
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return studies matching any of the given tags (substring match on tags field)."""
    sql_conditions = " OR ".join(f"CONTAINS(tags, '{t}')" for t in tags)
    resolved = _resolve_scope(project, all_projects)
    scope = _sql_scope(resolved, "AND")
    return ql(
        store,
        sql=(
            'SELECT studyId AS "s.studyId",'
            ' title AS "s.title",'
            ' status AS "s.status",'
            ' outcome AS "s.outcome",'
            ' confidence AS "s.confidence",'
            ' tags AS "s.tags"'
            f"{_provenance_select(resolved, 's')}"
            f" FROM Study WHERE ({sql_conditions}){scope}"
            " ORDER BY started DESC"
        ),
    )


def get_studies_by_outcome(
    store: GraphBackend,
    outcome: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return studies with a specific outcome."""
    escaped = sql_escape(outcome)
    resolved = _resolve_scope(project, all_projects)
    scope = _sql_scope(resolved, "AND")
    return ql(
        store,
        sql=(
            'SELECT studyId AS "s.studyId",'
            ' title AS "s.title",'
            ' status AS "s.status",'
            ' outcome AS "s.outcome",'
            ' confidence AS "s.confidence",'
            ' tags AS "s.tags"'
            f"{_provenance_select(resolved, 's')}"
            f" FROM Study WHERE outcome = '{escaped}'{scope}"
            " ORDER BY started DESC"
        ),
    )


def get_studies_for_file(
    store: GraphBackend,
    file_path: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return studies that reference the given file via artifact paths."""
    escaped = sql_escape(file_path)
    scope = _graph_scope(_resolve_scope(project, all_projects), "f")
    return ql(
        store,
        sql=(
            'SELECT t.s_studyId AS "s.studyId",'
            ' t.s_title AS "s.title",'
            ' t.s_status AS "s.status",'
            ' t.s_outcome AS "s.outcome",'
            ' t.s_tags AS "s.tags"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (s:Study)-[e:STUDY_REFERENCES_FILE]->(f:File)"
            f" WHERE f.path = '{escaped}'{scope}"
            " COLUMNS (s.studyId AS s_studyId, s.title AS s_title,"
            " s.status AS s_status, s.outcome AS s_outcome,"
            " s.tags AS s_tags)) t"
        ),
    )


def get_all_studies(
    store: GraphBackend,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return all studies ordered by start date descending."""
    scope = _sql_scope(_resolve_scope(project, all_projects), "WHERE")
    return ql(
        store,
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
            f" FROM Study{scope} ORDER BY started DESC"
        ),
    )


# ---------------------------------------------------------------------------
# ADR queries
# ---------------------------------------------------------------------------


def get_adrs_for_plan(
    store: GraphBackend,
    plan_number: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return ADRs that govern the given plan."""
    scope = _graph_scope(_resolve_scope(project, all_projects), "p")
    return ql(
        store,
        sql=(
            'SELECT t.a_number AS "a.number",'
            ' t.a_title AS "a.title",'
            ' t.a_status AS "a.status",'
            ' t.a_date AS "a.date"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:ADR)-[e:ADR_GOVERNS]->(p:Plan)"
            f" WHERE p.number = {plan_number}{scope}"
            " COLUMNS (a.number AS a_number, a.title AS a_title,"
            " a.status AS a_status, a.date AS a_date)) t"
        ),
    )


def get_adr_by_number(
    store: GraphBackend,
    number: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> dict[str, Any] | None:
    """Return a single ADR by number."""
    scope = _sql_scope(_resolve_scope(project, all_projects), "AND")
    rows = ql(
        store,
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
            f" FROM ADR WHERE number = {number}{scope}"
        ),
    )
    return rows[0] if rows else None


def get_all_adrs(
    store: GraphBackend,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return all ADRs ordered by number."""
    resolved = _resolve_scope(project, all_projects)
    scope = _sql_scope(resolved, "WHERE")
    return ql(
        store,
        sql=(
            'SELECT number AS "a.number",'
            ' title AS "a.title",'
            ' status AS "a.status",'
            ' date AS "a.date",'
            ' supersededBy AS "a.supersededBy"'
            f"{_provenance_select(resolved, 'a')}"
            f" FROM ADR{scope} ORDER BY number"
        ),
    )


def get_superseded_adrs(
    store: GraphBackend,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return ADRs that have been superseded."""
    scope = _sql_scope(_resolve_scope(project, all_projects), "AND")
    return ql(
        store,
        sql=(
            'SELECT number AS "a.number",'
            ' title AS "a.title",'
            ' status AS "a.status",'
            ' supersededBy AS "a.supersededBy"'
            f" FROM ADR WHERE CONTAINS(status, 'Superseded'){scope}"
        ),
    )


def get_adrs_for_file(
    store: GraphBackend,
    file_path: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return ADRs governing plans that impact this file (2-hop traversal)."""
    escaped = sql_escape(file_path)
    scope = _graph_scope(_resolve_scope(project, all_projects), "f")
    return ql(
        store,
        sql=(
            "SELECT DISTINCT"
            ' t.a_number AS "a.number",'
            ' t.a_title AS "a.title",'
            ' t.a_status AS "a.status",'
            ' t.p_number AS "plan_number"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:ADR)-[e1:ADR_GOVERNS]->(p:Plan)-[e2:PLAN_IMPACTS]->(f:File)"
            f" WHERE f.path = '{escaped}'{scope}"
            " COLUMNS (a.number AS a_number, a.title AS a_title,"
            " a.status AS a_status, p.number AS p_number)) t"
        ),
    )


# ---------------------------------------------------------------------------
# Spike queries
# ---------------------------------------------------------------------------


def get_spikes_for_plan(
    store: GraphBackend,
    plan_number: int,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return spikes that validated the given plan."""
    scope = _graph_scope(_resolve_scope(project, all_projects), "p")
    return ql(
        store,
        sql=(
            'SELECT t.sp_title AS "sp.title",'
            ' t.sp_status AS "sp.status",'
            ' t.sp_created AS "sp.created",'
            ' t.sp_timeBox AS "sp.timeBox",'
            ' t.sp_filePath AS "sp.filePath"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (sp:Spike)-[e:SPIKE_FOR_PLAN]->(p:Plan)"
            f" WHERE p.number = {plan_number}{scope}"
            " COLUMNS (sp.title AS sp_title, sp.status AS sp_status,"
            " sp.created AS sp_created, sp.timeBox AS sp_timeBox,"
            " sp.filePath AS sp_filePath)) t"
        ),
    )


def get_all_spikes(
    store: GraphBackend,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return all spikes ordered by created date descending."""
    scope = _sql_scope(_resolve_scope(project, all_projects), "WHERE")
    return ql(
        store,
        sql=(
            'SELECT title AS "sp.title",'
            ' parentPlan AS "sp.parentPlan",'
            ' status AS "sp.status",'
            ' created AS "sp.created",'
            ' timeBox AS "sp.timeBox"'
            f" FROM Spike{scope} ORDER BY created DESC"
        ),
    )


# ---------------------------------------------------------------------------
# Backlog queries
# ---------------------------------------------------------------------------


def get_open_backlog_items(
    store: GraphBackend,
    *,
    plan_number: int | None = None,
    limit: int = 20,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return open BacklogItems, optionally filtered by plan, sorted by priority.

    Scoped to the current project by default so a sibling project's backlog does
    not leak into orientation/recall; ``all_projects`` reads the federation.
    """
    from agentscaffold.graph.backlog import get_open_backlog_items as _get_open  # noqa: PLC0415

    scope = _resolve_scope(project, all_projects)
    return _get_open(
        store, plan_number=plan_number, limit=limit, project=getattr(scope, "project", None)
    )


def get_backlog_items_for_plan(
    store: GraphBackend,
    plan_number: int,
    *,
    include_archived: bool = False,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return all BacklogItems for a specific plan (scoped to the current project)."""
    from agentscaffold.graph.backlog import (  # noqa: PLC0415
        get_backlog_items_for_plan as _get_plan_items,
    )

    scope = _resolve_scope(project, all_projects)
    return _get_plan_items(
        store,
        plan_number,
        include_archived=include_archived,
        project=getattr(scope, "project", None),
    )


# ---------------------------------------------------------------------------
# Plan lifecycle queries
# ---------------------------------------------------------------------------


def stamp_plan_reviewed(store: GraphBackend, plan_number: int) -> str | None:
    """Set ``reviewedAt`` on the Plan node for the given plan number.

    Returns the ISO timestamp written, or None if the Plan node does not exist.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    now = datetime.now(timezone.utc).isoformat()
    rows = store.query(f"SELECT id FROM Plan WHERE number = {plan_number}")
    if not rows:
        return None
    plan_id = rows[0]["id"]
    store.execute(f"UPDATE Plan SET reviewedAt = '{now}' WHERE id = '{plan_id}'")
    return now


def get_plan_reviewed_at(store: GraphBackend, plan_number: int) -> str | None:
    """Return the ``reviewedAt`` timestamp for the given plan, or None."""
    rows = store.query(f"SELECT reviewedAt FROM Plan WHERE number = {plan_number}")
    if not rows:
        return None
    val = rows[0].get("reviewedAt")
    return val if val else None


# ---------------------------------------------------------------------------
# Spike queries (continued)
# ---------------------------------------------------------------------------


def get_spike_by_title(
    store: GraphBackend,
    title_fragment: str,
    *,
    project: str | None = None,
    all_projects: bool = False,
) -> list[dict[str, Any]]:
    """Return spikes matching a title keyword."""
    escaped = sql_escape(title_fragment)
    scope = _sql_scope(_resolve_scope(project, all_projects), "AND")
    return ql(
        store,
        sql=(
            'SELECT title AS "sp.title",'
            ' parentPlan AS "sp.parentPlan",'
            ' status AS "sp.status",'
            ' created AS "sp.created",'
            ' filePath AS "sp.filePath"'
            f" FROM Spike WHERE CONTAINS(title, '{escaped}'){scope}"
        ),
    )
