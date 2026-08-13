"""DuckPGQ schema DDL for the AgentScaffold knowledge graph.

SINGLE SOURCE OF TRUTH
======================
Edge identity lives in one place: the ``EDGE_DEFS`` list below.  The edge DDL
(``EDGE_TABLES``), the edge-name tuple (``EDGE_TABLE_NAMES``), and the
``EDGE TABLES`` clause of ``CREATE_PROPERTY_GRAPH_SQL`` are all generated from
it, so they cannot drift.  To add or change an edge, edit ``EDGE_DEFS`` only.

Node tables are still authored as ``CREATE TABLE`` strings in ``NODE_TABLES``;
their names (``NODE_TABLE_NAMES``) and the ``VERTEX TABLES`` clause of the
property graph are derived from that single list.

To add a node:
  1. Add the ``CREATE TABLE`` statement to ``NODE_TABLES``.
  2. Bump ``SCHEMA_VERSION``.

To add an edge:
  1. Add an ``EdgeDef`` entry to ``EDGE_DEFS``.
  2. Bump ``SCHEMA_VERSION``.

DuckPGQ does not discover tables automatically, but because the property graph
statement is generated from these two lists there is no separate clause to keep
in sync.  A guardrail test (``tests/test_duckpgq_schema.py``) fails if the
derived names, DDL, and property-graph statement ever disagree.

If you are writing a plan that changes the graph schema, add this checklist
item to the plan's implementation steps:
  - [ ] Update ``duckpgq_schema.py``: NODE_TABLES DDL and/or EDGE_DEFS +
        SCHEMA_VERSION bump.

Edge table convention
---------------------
Each SQL edge table has two fixed FK columns:
  - ``src VARCHAR NOT NULL``  – references the source node table's ``id``
  - ``dst VARCHAR NOT NULL``  – references the destination node table's ``id``

Plus any per-edge properties (e.g., ``importedNames``, ``confidence``).

Column type mapping
-------------------
  STRING   →  VARCHAR
  INT64    →  BIGINT
  BOOLEAN  →  BOOLEAN
  DOUBLE   →  DOUBLE

Query validation: all DuckPGQ query patterns were validated in
``dev_docs/spike-duckpgq-query-validation.md`` (Step A.0.5, all 5 patterns
PASS on DuckDB 1.4.4 + duckpgq community extension).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import duckdb

# Bumped to 10 by Plan 252 without a DDL change. The tables are identical; what
# changed is what gets *derived* into them -- relative Python imports now produce
# IMPORTS edges instead of being dropped. A graph built before that fix is
# structurally valid and quietly incomplete, which is the worst state for impact
# analysis to be in, because an under-reported blast radius is indistinguishable
# from a small one. Bumping the version routes those graphs through the existing
# governance-preserving rebuild so they heal on the next index rather than
# waiting for someone to read a warning and act on it.
SCHEMA_VERSION = 10

# ---------------------------------------------------------------------------
# Node table DDL (20 tables)
# ---------------------------------------------------------------------------

_AUTHORED_NODE_TABLES: list[str] = [
    # --- Workspace nodes (Plan 225) ---
    # The Project node is the namespace itself; it carries no `project` column.
    # `lastIndexed` is per-project so re-indexing one project does not misreport
    # another's freshness (GraphMeta stays workspace-global for schema/pipeline state).
    """
    CREATE TABLE IF NOT EXISTS Project (
        id          VARCHAR PRIMARY KEY,
        name        VARCHAR,
        rootPath    VARCHAR,
        lastIndexed VARCHAR
    )
    """,
    # --- Code nodes ---
    """
    CREATE TABLE IF NOT EXISTS File (
        id           VARCHAR PRIMARY KEY,
        path         VARCHAR,
        language     VARCHAR,
        size         BIGINT,
        lastModified VARCHAR,
        lineCount    BIGINT,
        contentHash  VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Folder (
        id    VARCHAR PRIMARY KEY,
        path  VARCHAR,
        name  VARCHAR,
        depth BIGINT
    )
    """,
    # NOTE: "Function" is a reserved word in some SQL dialects.  DuckDB accepts
    # it as a table name when unquoted (consistent with spike validation), but
    # it must be quoted in the CREATE PROPERTY GRAPH statement and in any raw
    # DuckDB SQL that references it outside of GRAPH_TABLE MATCH clauses.
    """
    CREATE TABLE IF NOT EXISTS Function (
        id         VARCHAR PRIMARY KEY,
        name       VARCHAR,
        filePath   VARCHAR,
        startLine  BIGINT,
        endLine    BIGINT,
        isExported BOOLEAN,
        paramCount BIGINT,
        signature  VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Class (
        id         VARCHAR PRIMARY KEY,
        name       VARCHAR,
        filePath   VARCHAR,
        startLine  BIGINT,
        endLine    BIGINT,
        isExported BOOLEAN
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Method (
        id         VARCHAR PRIMARY KEY,
        name       VARCHAR,
        className  VARCHAR,
        filePath   VARCHAR,
        startLine  BIGINT,
        endLine    BIGINT,
        isExported BOOLEAN,
        signature  VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Interface (
        id        VARCHAR PRIMARY KEY,
        name      VARCHAR,
        filePath  VARCHAR,
        startLine BIGINT,
        endLine   BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Community (
        id            VARCHAR PRIMARY KEY,
        name          VARCHAR,
        label         VARCHAR,
        fileCount     BIGINT,
        functionCount BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Process (
        id          VARCHAR PRIMARY KEY,
        name        VARCHAR,
        description VARCHAR,
        stepCount   BIGINT
    )
    """,
    # --- Governance nodes ---
    """
    CREATE TABLE IF NOT EXISTS ArchitectureLayer (
        id           VARCHAR PRIMARY KEY,
        number       BIGINT,
        name         VARCHAR,
        description  VARCHAR,
        pathPatterns VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Plan (
        id          VARCHAR PRIMARY KEY,
        number      BIGINT,
        title       VARCHAR,
        status      VARCHAR,
        planType    VARCHAR,
        filePath    VARCHAR,
        createdDate VARCHAR,
        lastUpdated VARCHAR,
        reviewedAt  VARCHAR DEFAULT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Contract (
        id              VARCHAR PRIMARY KEY,
        name            VARCHAR,
        version         VARCHAR,
        filePath        VARCHAR,
        lastUpdated     VARCHAR,
        declaredMethods VARCHAR,
        declaredClasses VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Learning (
        id          VARCHAR PRIMARY KEY,
        learningId  VARCHAR,
        planNumber  BIGINT,
        description VARCHAR,
        target      VARCHAR,
        status      VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ReviewFinding (
        id         VARCHAR PRIMARY KEY,
        reviewType VARCHAR,
        planNumber BIGINT,
        severity   VARCHAR,
        category   VARCHAR,
        finding    VARCHAR,
        resolution VARCHAR,
        status     VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Session (
        id            VARCHAR PRIMARY KEY,
        date          VARCHAR,
        planNumbers   VARCHAR,
        filesModified VARCHAR,
        summary       VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Study (
        id           VARCHAR PRIMARY KEY,
        studyId      VARCHAR,
        title        VARCHAR,
        studyType    VARCHAR,
        status       VARCHAR,
        outcome      VARCHAR,
        confidence   VARCHAR,
        tags         VARCHAR,
        relatedPlans VARCHAR,
        filePath     VARCHAR,
        started      VARCHAR,
        completed    VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ADR (
        id           VARCHAR PRIMARY KEY,
        number       BIGINT,
        title        VARCHAR,
        status       VARCHAR,
        date         VARCHAR,
        filePath     VARCHAR,
        relatedPlans VARCHAR,
        relatedADRs  VARCHAR,
        supersededBy VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Spike (
        id         VARCHAR PRIMARY KEY,
        title      VARCHAR,
        parentPlan VARCHAR,
        status     VARCHAR,
        created    VARCHAR,
        filePath   VARCHAR,
        timeBox    VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS BacklogItem (
        id         VARCHAR PRIMARY KEY,
        planNumber BIGINT,
        title      VARCHAR,
        priority   VARCHAR,
        effort     VARCHAR,
        status     VARCHAR,
        source     VARCHAR,
        createdAt  VARCHAR,
        archivedAt VARCHAR,
        resolution VARCHAR DEFAULT ''
    )
    """,
    # --- Metadata nodes ---
    """
    CREATE TABLE IF NOT EXISTS GraphMeta (
        id              VARCHAR PRIMARY KEY,
        schemaVersion   BIGINT,
        lastIndexed     VARCHAR,
        pipelineState   VARCHAR,
        phasesCompleted VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ParsingWarning (
        id       VARCHAR PRIMARY KEY,
        filePath VARCHAR,
        phase    VARCHAR,
        message  VARCHAR,
        severity VARCHAR
    )
    """,
]

# ---------------------------------------------------------------------------
# Derived node-table names
#
# Node names are extracted from the CREATE TABLE statements above so the
# property graph's VERTEX TABLES clause and the clear/delete helpers never
# drift from the authoritative DDL.
# ---------------------------------------------------------------------------


def _table_name(create_table_ddl: str) -> str:
    """Extract the table name from a ``CREATE TABLE IF NOT EXISTS <name> (...)`` string."""
    return create_table_ddl.strip().split("(")[0].split()[-1]


# Node tables that are NOT project-scoped: GraphMeta is workspace-global
# (schema version + pipeline state) and Project is the namespace itself.
_PROJECT_SCOPED_EXCLUDE = {"GraphMeta", "Project"}


def _with_project_column(create_table_ddl: str) -> str:
    """Append a ``project`` column to a node table DDL (Plan 225, single source).

    Multi-project workspaces namespace every code/governance node with its owning
    project; the column is the authoritative scoping key (ID prefixing is the
    collision guard, the column drives reads and project-scoped clears). Defined
    once here so all node tables stay consistent. Single-project repos leave it at
    the ``''`` default and scope predicates are no-ops, so behavior is unchanged.
    ``GraphMeta`` and ``Project`` are excluded (see ``_PROJECT_SCOPED_EXCLUDE``).
    """
    if _table_name(create_table_ddl) in _PROJECT_SCOPED_EXCLUDE:
        return create_table_ddl
    stripped = create_table_ddl.rstrip()
    if not stripped.endswith(")"):
        raise ValueError(f"Unexpected node DDL (no trailing ')'): {create_table_ddl!r}")
    body = stripped[:-1].rstrip()
    return f"{body},\n        project     VARCHAR DEFAULT ''\n    )\n    "


# The authoritative node-table DDL list, with the project column injected.
NODE_TABLES: list[str] = [_with_project_column(stmt) for stmt in _AUTHORED_NODE_TABLES]


NODE_TABLE_NAMES: tuple[str, ...] = tuple(_table_name(stmt) for stmt in NODE_TABLES)


# ---------------------------------------------------------------------------
# Edge definitions (single source of truth)
#
# Every edge's DDL, name, and property-graph clause is generated from this
# list. Each edge has the two fixed FK columns ``src``/``dst`` plus any extra
# property columns declared in ``properties`` as (column_name, sql_type).
# ---------------------------------------------------------------------------


class EdgeDef(NamedTuple):
    """A single property-graph edge: its name, FK node tables, and extra columns."""

    name: str
    src: str
    dst: str
    properties: tuple[tuple[str, str], ...] = ()


EDGE_DEFS: list[EdgeDef] = [
    # --- Code edges ---
    EdgeDef("CONTAINS", "Folder", "File"),
    EdgeDef("CONTAINS_FOLDER", "Folder", "Folder"),
    EdgeDef("DEFINES_FUNCTION", "File", "Function"),
    EdgeDef("DEFINES_CLASS", "File", "Class"),
    EdgeDef("DEFINES_INTERFACE", "File", "Interface"),
    EdgeDef("HAS_METHOD", "Class", "Method"),
    EdgeDef("IMPORTS", "File", "File", (("importedNames", "VARCHAR"),)),
    EdgeDef("CALLS", "Function", "Function", (("confidence", "DOUBLE"), ("reason", "VARCHAR"))),
    EdgeDef(
        "METHOD_CALLS",
        "Method",
        "Function",
        (("confidence", "DOUBLE"), ("reason", "VARCHAR")),
    ),
    EdgeDef("EXTENDS", "Class", "Class"),
    EdgeDef("IMPLEMENTS", "Class", "Interface"),
    EdgeDef("MEMBER_OF_COMMUNITY", "File", "Community"),
    EdgeDef("STEP_IN_PROCESS", "Function", "Process", (("step", "BIGINT"),)),
    # --- Governance edges ---
    EdgeDef("BELONGS_TO_LAYER", "File", "ArchitectureLayer"),
    EdgeDef("PLAN_IMPACTS", "Plan", "File", (("changeType", "VARCHAR"),)),
    EdgeDef("PLAN_INTRODUCES_FUNC", "Plan", "Function"),
    EdgeDef("PLAN_INTRODUCES_CLASS", "Plan", "Class"),
    EdgeDef("CONTRACT_DECLARES_FUNC", "Contract", "Function", (("declaredSignature", "VARCHAR"),)),
    EdgeDef("CONTRACT_DECLARES_CLASS", "Contract", "Class", (("declaredSignature", "VARCHAR"),)),
    EdgeDef("CONTRACT_ABOUT_FILE", "Contract", "File"),
    EdgeDef("LEARNING_RELATES_TO_FILE", "Learning", "File"),
    EdgeDef("LEARNING_RELATES_TO_FUNC", "Learning", "Function"),
    EdgeDef("FINDING_ABOUT_FILE", "ReviewFinding", "File"),
    EdgeDef("FINDING_ABOUT_FUNC", "ReviewFinding", "Function"),
    EdgeDef("FINDING_LED_TO", "ReviewFinding", "Learning"),
    EdgeDef("FINDING_ADDRESSED_BY", "ReviewFinding", "Plan"),
    EdgeDef("SESSION_MODIFIED", "Session", "File"),
    EdgeDef("DEPENDS_ON_PLAN", "Plan", "Plan"),
    EdgeDef("STUDY_REFERENCES_PLAN", "Study", "Plan"),
    EdgeDef("STUDY_REFERENCES_FILE", "Study", "File"),
    EdgeDef("ADR_GOVERNS", "ADR", "Plan"),
    EdgeDef("ADR_SUPERSEDES", "ADR", "ADR"),
    EdgeDef("ADR_CITES_STUDY", "ADR", "Study"),
    EdgeDef("ADR_CITES_SPIKE", "ADR", "Spike"),
    EdgeDef("SPIKE_FOR_PLAN", "Spike", "Plan"),
    EdgeDef("BACKLOG_ITEM_OF", "BacklogItem", "Plan"),
    # Config-driven wiring: a config File (YAML/JSON/TOML) references a code File
    # via a fully-qualified dotted path under an allowlisted key (e.g. ``class:
    # libs.strategies.momentum.MomentumStrategy``). ``symbol`` is the trailing
    # Class/Function name when one resolved, else empty; ``confidence`` is 0.9
    # when the symbol resolved in the target file, 0.7 for a file-only resolution.
    EdgeDef(
        "CONFIG_REFERENCES",
        "File",
        "File",
        (("confidence", "DOUBLE"), ("refKey", "VARCHAR"), ("symbol", "VARCHAR")),
    ),
]


def _edge_ddl(edge: EdgeDef) -> str:
    """Render the ``CREATE TABLE`` DDL for an edge from its definition."""
    columns = ["src VARCHAR NOT NULL", "dst VARCHAR NOT NULL"]
    columns += [f"{name} {sql_type}" for name, sql_type in edge.properties]
    if edge.properties:
        body = ",\n    ".join(columns)
        return f"CREATE TABLE IF NOT EXISTS {edge.name} (\n    {body}\n)"
    return f"CREATE TABLE IF NOT EXISTS {edge.name} ({columns[0]}, {columns[1]})"


# Edge DDL (executed by init_schema) and edge names (used by the backend for
# cascade/clear operations) -- both generated from EDGE_DEFS.
EDGE_TABLES: list[str] = [_edge_ddl(edge) for edge in EDGE_DEFS]
EDGE_TABLE_NAMES: tuple[str, ...] = tuple(edge.name for edge in EDGE_DEFS)

# ---------------------------------------------------------------------------
# CREATE PROPERTY GRAPH DDL (generated)
#
# The VERTEX TABLES clause is generated from NODE_TABLE_NAMES and the EDGE
# TABLES clause from EDGE_DEFS, so this statement can never drift from the
# table definitions above.
# ---------------------------------------------------------------------------

DROP_PROPERTY_GRAPH_SQL = "DROP PROPERTY GRAPH IF EXISTS agentscaffold_graph"


def _build_create_property_graph_sql() -> str:
    """Generate the CREATE PROPERTY GRAPH statement from the table definitions."""
    vertices = ",\n    ".join(NODE_TABLE_NAMES)
    edge_clauses = [
        f"    {edge.name}\n"
        f"        SOURCE KEY (src) REFERENCES {edge.src} (id)\n"
        f"        DESTINATION KEY (dst) REFERENCES {edge.dst} (id)"
        for edge in EDGE_DEFS
    ]
    edges = ",\n".join(edge_clauses)
    return (
        "CREATE PROPERTY GRAPH agentscaffold_graph\n"
        f"VERTEX TABLES (\n    {vertices}\n)\n"
        f"EDGE TABLES (\n{edges}\n)"
    )


CREATE_PROPERTY_GRAPH_SQL = _build_create_property_graph_sql()


# ---------------------------------------------------------------------------
# Auxiliary tables (not part of the property graph topology)
# ---------------------------------------------------------------------------

# EmbeddingStore holds float-array embeddings for semantic similarity search.
# It is a plain SQL table (not a VERTEX/EDGE TABLE) so it does not appear in
# CREATE_PROPERTY_GRAPH_SQL.  Stored as FLOAT[] so DuckDB's
# list_cosine_similarity() can operate on it without loading JSON.
AUXILIARY_TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS EmbeddingStore (
        node_id   VARCHAR NOT NULL,
        node_type VARCHAR NOT NULL,
        embedding FLOAT[],
        project   VARCHAR DEFAULT '',
        model     VARCHAR DEFAULT '',
        text_hash VARCHAR DEFAULT '',
        PRIMARY KEY (node_id, node_type)
    )
    """,
]


def all_node_ddl() -> list[str]:
    """Return DDL for all node tables in dependency order."""
    return list(NODE_TABLES)


def all_edge_ddl() -> list[str]:
    """Return DDL for all edge tables in dependency order."""
    return list(EDGE_TABLES)


def init_schema(conn: duckdb.DuckDBPyConnection, *, force_recreate_graph: bool = False) -> None:
    """Create all tables and register the property graph.

    Node and edge tables use ``CREATE TABLE IF NOT EXISTS``.  The property
    graph is created lazily (skip if it already exists) unless
    *force_recreate_graph* is True.

    DuckPGQ property graphs are process-global within a DuckDB instance.
    Dropping the graph affects all open connections to any database in the
    same process, so we avoid DROP unless explicitly forced (e.g. full
    re-index via ``clear_all()``).

    Args:
        conn: An open DuckDB connection with the duckpgq extension loaded.
        force_recreate_graph: If True, drop and recreate the property graph.
            Use only when performing a full re-index (not for normal opens).
    """
    for stmt in NODE_TABLES:
        conn.execute(stmt)
    for stmt in EDGE_TABLES:
        conn.execute(stmt)
    for stmt in AUXILIARY_TABLES:
        conn.execute(stmt)
    # Additive column for existing databases (Plan 255). CREATE TABLE IF NOT EXISTS
    # does not add columns to an already-created table; this ALTER is idempotent
    # and avoids a SCHEMA_VERSION bump / full rebuild for one VARCHAR.
    try:
        conn.execute(
            "ALTER TABLE BacklogItem ADD COLUMN IF NOT EXISTS resolution VARCHAR DEFAULT ''"
        )
    except Exception as exc:
        # Older DuckDB without IF NOT EXISTS: ignore "already exists".
        if "already exists" not in str(exc).lower():
            raise
    if force_recreate_graph:
        conn.execute(DROP_PROPERTY_GRAPH_SQL)
        conn.execute(CREATE_PROPERTY_GRAPH_SQL)
    else:
        try:
            conn.execute(CREATE_PROPERTY_GRAPH_SQL)
        except Exception as exc:
            if "already exists" not in str(exc):
                raise
