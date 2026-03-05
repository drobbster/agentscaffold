"""KuzuDB schema definitions for the AgentScaffold knowledge graph.

All node and edge tables are defined here as Cypher DDL strings.
The schema is versioned; bumps require a full re-index.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Code node tables
# ---------------------------------------------------------------------------

NODE_TABLES: list[str] = [
    """
    CREATE NODE TABLE IF NOT EXISTS File (
        id STRING,
        path STRING,
        language STRING,
        size INT64,
        lastModified STRING,
        lineCount INT64,
        contentHash STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Folder (
        id STRING,
        path STRING,
        name STRING,
        depth INT64,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Function (
        id STRING,
        name STRING,
        filePath STRING,
        startLine INT64,
        endLine INT64,
        isExported BOOLEAN,
        paramCount INT64,
        signature STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Class (
        id STRING,
        name STRING,
        filePath STRING,
        startLine INT64,
        endLine INT64,
        isExported BOOLEAN,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Method (
        id STRING,
        name STRING,
        className STRING,
        filePath STRING,
        startLine INT64,
        endLine INT64,
        isExported BOOLEAN,
        signature STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Interface (
        id STRING,
        name STRING,
        filePath STRING,
        startLine INT64,
        endLine INT64,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Community (
        id STRING,
        name STRING,
        label STRING,
        fileCount INT64,
        functionCount INT64,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Process (
        id STRING,
        name STRING,
        description STRING,
        stepCount INT64,
        PRIMARY KEY (id)
    )
    """,
]

# ---------------------------------------------------------------------------
# Governance node tables
# ---------------------------------------------------------------------------

GOVERNANCE_NODE_TABLES: list[str] = [
    """
    CREATE NODE TABLE IF NOT EXISTS ArchitectureLayer (
        id STRING,
        number INT64,
        name STRING,
        description STRING,
        pathPatterns STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Plan (
        id STRING,
        number INT64,
        title STRING,
        status STRING,
        planType STRING,
        filePath STRING,
        createdDate STRING,
        lastUpdated STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Contract (
        id STRING,
        name STRING,
        version STRING,
        filePath STRING,
        lastUpdated STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Learning (
        id STRING,
        learningId STRING,
        planNumber INT64,
        description STRING,
        target STRING,
        status STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS ReviewFinding (
        id STRING,
        reviewType STRING,
        planNumber INT64,
        severity STRING,
        category STRING,
        finding STRING,
        resolution STRING,
        status STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Session (
        id STRING,
        date STRING,
        planNumbers STRING,
        filesModified STRING,
        summary STRING,
        PRIMARY KEY (id)
    )
    """,
]

# ---------------------------------------------------------------------------
# Metadata tables
# ---------------------------------------------------------------------------

METADATA_TABLES: list[str] = [
    """
    CREATE NODE TABLE IF NOT EXISTS GraphMeta (
        id STRING,
        schemaVersion INT64,
        lastIndexed STRING,
        pipelineState STRING,
        phasesCompleted STRING,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS ParsingWarning (
        id STRING,
        filePath STRING,
        phase STRING,
        message STRING,
        severity STRING,
        PRIMARY KEY (id)
    )
    """,
]

# ---------------------------------------------------------------------------
# Code edge tables
# ---------------------------------------------------------------------------

EDGE_TABLES: list[str] = [
    "CREATE REL TABLE IF NOT EXISTS CONTAINS (FROM Folder TO File, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS CONTAINS_FOLDER (FROM Folder TO Folder, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS DEFINES_FUNCTION (FROM File TO Function, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS DEFINES_CLASS (FROM File TO Class, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS DEFINES_INTERFACE (FROM File TO Interface, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS HAS_METHOD (FROM Class TO Method, MANY_MANY)",
    """
    CREATE REL TABLE IF NOT EXISTS IMPORTS (
        FROM File TO File,
        importedNames STRING,
        MANY_MANY
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS CALLS (
        FROM Function TO Function,
        confidence DOUBLE,
        reason STRING,
        MANY_MANY
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS METHOD_CALLS (
        FROM Method TO Function,
        confidence DOUBLE,
        reason STRING,
        MANY_MANY
    )
    """,
    "CREATE REL TABLE IF NOT EXISTS EXTENDS (FROM Class TO Class, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS (FROM Class TO Interface, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS MEMBER_OF_COMMUNITY (FROM File TO Community, MANY_MANY)",
    """
    CREATE REL TABLE IF NOT EXISTS STEP_IN_PROCESS (
        FROM Function TO Process,
        step INT64,
        MANY_MANY
    )
    """,
]

# ---------------------------------------------------------------------------
# Governance edge tables
# ---------------------------------------------------------------------------

GOVERNANCE_EDGE_TABLES: list[str] = [
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO_LAYER (FROM File TO ArchitectureLayer, MANY_MANY)",
    """
    CREATE REL TABLE IF NOT EXISTS PLAN_IMPACTS (
        FROM Plan TO File,
        changeType STRING,
        MANY_MANY
    )
    """,
    "CREATE REL TABLE IF NOT EXISTS PLAN_INTRODUCES_FUNC (FROM Plan TO Function, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS PLAN_INTRODUCES_CLASS (FROM Plan TO Class, MANY_MANY)",
    """
    CREATE REL TABLE IF NOT EXISTS CONTRACT_DECLARES_FUNC (
        FROM Contract TO Function,
        declaredSignature STRING,
        MANY_MANY
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS CONTRACT_DECLARES_CLASS (
        FROM Contract TO Class,
        declaredSignature STRING,
        MANY_MANY
    )
    """,
    "CREATE REL TABLE IF NOT EXISTS LEARNING_RELATES_TO_FILE (FROM Learning TO File, MANY_MANY)",
    (
        "CREATE REL TABLE IF NOT EXISTS LEARNING_RELATES_TO_FUNC "
        "(FROM Learning TO Function, MANY_MANY)"
    ),
    "CREATE REL TABLE IF NOT EXISTS FINDING_ABOUT_FILE (FROM ReviewFinding TO File, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS FINDING_ABOUT_FUNC (FROM ReviewFinding TO Function, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS FINDING_LED_TO (FROM ReviewFinding TO Learning, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS FINDING_ADDRESSED_BY (FROM ReviewFinding TO Plan, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS SESSION_MODIFIED (FROM Session TO File, MANY_MANY)",
    "CREATE REL TABLE IF NOT EXISTS DEPENDS_ON_PLAN (FROM Plan TO Plan, MANY_MANY)",
]


def all_ddl_statements() -> list[str]:
    """Return all DDL statements in dependency order."""
    return (
        NODE_TABLES
        + GOVERNANCE_NODE_TABLES
        + METADATA_TABLES
        + EDGE_TABLES
        + GOVERNANCE_EDGE_TABLES
    )
