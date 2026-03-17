"""DuckPGQ schema DDL for the AgentScaffold knowledge graph.

COUPLING WARNING
================
The ``CREATE_PROPERTY_GRAPH_SQL`` constant at the bottom of this module MUST
list every node table and every edge table by name.  DuckPGQ does not discover
tables automatically.  Any time a new node or edge type is added to the schema,
you must:

  1. Add the SQL ``CREATE TABLE`` statement to ``NODE_TABLES`` or
     ``EDGE_TABLES`` below.
  2. Add the corresponding ``VERTEX TABLE`` or ``EDGE TABLE`` clause to
     ``CREATE_PROPERTY_GRAPH_SQL``.
  3. Bump ``SCHEMA_VERSION``.

Failure to update ``CREATE_PROPERTY_GRAPH_SQL`` will silently omit the new
type from all ``GRAPH_TABLE`` queries.

If you are writing a plan that changes the graph schema, add this checklist
item to the plan's implementation steps:
  - [ ] Update ``duckpgq_schema.py``: NODE_TABLES / EDGE_TABLES DDL +
        CREATE_PROPERTY_GRAPH_SQL vertex/edge clauses + SCHEMA_VERSION bump.

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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

SCHEMA_VERSION = 4

# ---------------------------------------------------------------------------
# Node table DDL (19 tables)
# ---------------------------------------------------------------------------

NODE_TABLES: list[str] = [
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
        lastUpdated VARCHAR
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
# Edge table DDL (34 tables)
# All edge tables use ``src`` and ``dst`` FK columns (spike convention).
# ---------------------------------------------------------------------------

EDGE_TABLES: list[str] = [
    # --- Code edges ---
    "CREATE TABLE IF NOT EXISTS CONTAINS (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS CONTAINS_FOLDER (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS DEFINES_FUNCTION (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS DEFINES_CLASS (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS DEFINES_INTERFACE (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS HAS_METHOD (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS IMPORTS (
        src           VARCHAR NOT NULL,
        dst           VARCHAR NOT NULL,
        importedNames VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS CALLS (
        src        VARCHAR NOT NULL,
        dst        VARCHAR NOT NULL,
        confidence DOUBLE,
        reason     VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS METHOD_CALLS (
        src        VARCHAR NOT NULL,
        dst        VARCHAR NOT NULL,
        confidence DOUBLE,
        reason     VARCHAR
    )
    """,
    "CREATE TABLE IF NOT EXISTS EXTENDS (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS IMPLEMENTS (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS MEMBER_OF_COMMUNITY (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS STEP_IN_PROCESS (
        src  VARCHAR NOT NULL,
        dst  VARCHAR NOT NULL,
        step BIGINT
    )
    """,
    # --- Governance edges ---
    "CREATE TABLE IF NOT EXISTS BELONGS_TO_LAYER (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS PLAN_IMPACTS (
        src        VARCHAR NOT NULL,
        dst        VARCHAR NOT NULL,
        changeType VARCHAR
    )
    """,
    "CREATE TABLE IF NOT EXISTS PLAN_INTRODUCES_FUNC (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS PLAN_INTRODUCES_CLASS (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS CONTRACT_DECLARES_FUNC (
        src               VARCHAR NOT NULL,
        dst               VARCHAR NOT NULL,
        declaredSignature VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS CONTRACT_DECLARES_CLASS (
        src               VARCHAR NOT NULL,
        dst               VARCHAR NOT NULL,
        declaredSignature VARCHAR
    )
    """,
    "CREATE TABLE IF NOT EXISTS LEARNING_RELATES_TO_FILE"
    " (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS LEARNING_RELATES_TO_FUNC"
    " (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS FINDING_ABOUT_FILE (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS FINDING_ABOUT_FUNC (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS FINDING_LED_TO (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS FINDING_ADDRESSED_BY (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS SESSION_MODIFIED (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS DEPENDS_ON_PLAN (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS STUDY_REFERENCES_PLAN (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS STUDY_REFERENCES_FILE (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ADR_GOVERNS (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ADR_SUPERSEDES (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ADR_CITES_STUDY (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS ADR_CITES_SPIKE (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
    "CREATE TABLE IF NOT EXISTS SPIKE_FOR_PLAN (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)",
]

# ---------------------------------------------------------------------------
# CREATE PROPERTY GRAPH DDL
#
# COUPLING: This statement lists every node and edge table by name.
# Update this statement whenever NODE_TABLES or EDGE_TABLES changes.
# See the module docstring for the full update checklist.
# ---------------------------------------------------------------------------

DROP_PROPERTY_GRAPH_SQL = "DROP PROPERTY GRAPH IF EXISTS agentscaffold_graph"

CREATE_PROPERTY_GRAPH_SQL = """\
CREATE PROPERTY GRAPH agentscaffold_graph
VERTEX TABLES (
    File,
    Folder,
    Function,
    Class,
    Method,
    Interface,
    Community,
    Process,
    ArchitectureLayer,
    Plan,
    Contract,
    Learning,
    ReviewFinding,
    Session,
    Study,
    ADR,
    Spike,
    GraphMeta,
    ParsingWarning
)
EDGE TABLES (
    CONTAINS
        SOURCE KEY (src) REFERENCES Folder (id)
        DESTINATION KEY (dst) REFERENCES File (id),
    CONTAINS_FOLDER
        SOURCE KEY (src) REFERENCES Folder (id)
        DESTINATION KEY (dst) REFERENCES Folder (id),
    DEFINES_FUNCTION
        SOURCE KEY (src) REFERENCES File (id)
        DESTINATION KEY (dst) REFERENCES Function (id),
    DEFINES_CLASS
        SOURCE KEY (src) REFERENCES File (id)
        DESTINATION KEY (dst) REFERENCES Class (id),
    DEFINES_INTERFACE
        SOURCE KEY (src) REFERENCES File (id)
        DESTINATION KEY (dst) REFERENCES Interface (id),
    HAS_METHOD
        SOURCE KEY (src) REFERENCES Class (id)
        DESTINATION KEY (dst) REFERENCES Method (id),
    IMPORTS
        SOURCE KEY (src) REFERENCES File (id)
        DESTINATION KEY (dst) REFERENCES File (id),
    CALLS
        SOURCE KEY (src) REFERENCES Function (id)
        DESTINATION KEY (dst) REFERENCES Function (id),
    METHOD_CALLS
        SOURCE KEY (src) REFERENCES Method (id)
        DESTINATION KEY (dst) REFERENCES Function (id),
    EXTENDS
        SOURCE KEY (src) REFERENCES Class (id)
        DESTINATION KEY (dst) REFERENCES Class (id),
    IMPLEMENTS
        SOURCE KEY (src) REFERENCES Class (id)
        DESTINATION KEY (dst) REFERENCES Interface (id),
    MEMBER_OF_COMMUNITY
        SOURCE KEY (src) REFERENCES File (id)
        DESTINATION KEY (dst) REFERENCES Community (id),
    STEP_IN_PROCESS
        SOURCE KEY (src) REFERENCES Function (id)
        DESTINATION KEY (dst) REFERENCES Process (id),
    BELONGS_TO_LAYER
        SOURCE KEY (src) REFERENCES File (id)
        DESTINATION KEY (dst) REFERENCES ArchitectureLayer (id),
    PLAN_IMPACTS
        SOURCE KEY (src) REFERENCES Plan (id)
        DESTINATION KEY (dst) REFERENCES File (id),
    PLAN_INTRODUCES_FUNC
        SOURCE KEY (src) REFERENCES Plan (id)
        DESTINATION KEY (dst) REFERENCES Function (id),
    PLAN_INTRODUCES_CLASS
        SOURCE KEY (src) REFERENCES Plan (id)
        DESTINATION KEY (dst) REFERENCES Class (id),
    CONTRACT_DECLARES_FUNC
        SOURCE KEY (src) REFERENCES Contract (id)
        DESTINATION KEY (dst) REFERENCES Function (id),
    CONTRACT_DECLARES_CLASS
        SOURCE KEY (src) REFERENCES Contract (id)
        DESTINATION KEY (dst) REFERENCES Class (id),
    LEARNING_RELATES_TO_FILE
        SOURCE KEY (src) REFERENCES Learning (id)
        DESTINATION KEY (dst) REFERENCES File (id),
    LEARNING_RELATES_TO_FUNC
        SOURCE KEY (src) REFERENCES Learning (id)
        DESTINATION KEY (dst) REFERENCES Function (id),
    FINDING_ABOUT_FILE
        SOURCE KEY (src) REFERENCES ReviewFinding (id)
        DESTINATION KEY (dst) REFERENCES File (id),
    FINDING_ABOUT_FUNC
        SOURCE KEY (src) REFERENCES ReviewFinding (id)
        DESTINATION KEY (dst) REFERENCES Function (id),
    FINDING_LED_TO
        SOURCE KEY (src) REFERENCES ReviewFinding (id)
        DESTINATION KEY (dst) REFERENCES Learning (id),
    FINDING_ADDRESSED_BY
        SOURCE KEY (src) REFERENCES ReviewFinding (id)
        DESTINATION KEY (dst) REFERENCES Plan (id),
    SESSION_MODIFIED
        SOURCE KEY (src) REFERENCES Session (id)
        DESTINATION KEY (dst) REFERENCES File (id),
    DEPENDS_ON_PLAN
        SOURCE KEY (src) REFERENCES Plan (id)
        DESTINATION KEY (dst) REFERENCES Plan (id),
    STUDY_REFERENCES_PLAN
        SOURCE KEY (src) REFERENCES Study (id)
        DESTINATION KEY (dst) REFERENCES Plan (id),
    STUDY_REFERENCES_FILE
        SOURCE KEY (src) REFERENCES Study (id)
        DESTINATION KEY (dst) REFERENCES File (id),
    ADR_GOVERNS
        SOURCE KEY (src) REFERENCES ADR (id)
        DESTINATION KEY (dst) REFERENCES Plan (id),
    ADR_SUPERSEDES
        SOURCE KEY (src) REFERENCES ADR (id)
        DESTINATION KEY (dst) REFERENCES ADR (id),
    ADR_CITES_STUDY
        SOURCE KEY (src) REFERENCES ADR (id)
        DESTINATION KEY (dst) REFERENCES Study (id),
    ADR_CITES_SPIKE
        SOURCE KEY (src) REFERENCES ADR (id)
        DESTINATION KEY (dst) REFERENCES Spike (id),
    SPIKE_FOR_PLAN
        SOURCE KEY (src) REFERENCES Spike (id)
        DESTINATION KEY (dst) REFERENCES Plan (id)
)
"""


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
    if force_recreate_graph:
        conn.execute(DROP_PROPERTY_GRAPH_SQL)
        conn.execute(CREATE_PROPERTY_GRAPH_SQL)
    else:
        try:
            conn.execute(CREATE_PROPERTY_GRAPH_SQL)
        except Exception as exc:
            if "already exists" not in str(exc):
                raise
