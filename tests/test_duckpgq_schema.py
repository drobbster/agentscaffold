"""Tests for duckpgq_schema.py — Step A.5."""

from __future__ import annotations

import pytest

from agentscaffold.graph.duckpgq_schema import (
    CREATE_PROPERTY_GRAPH_SQL,
    EDGE_TABLES,
    NODE_TABLES,
    SCHEMA_VERSION,
    all_edge_ddl,
    all_node_ddl,
    init_schema,
)

# Skip entire module if duckdb is not installed.
duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")


@pytest.fixture
def conn():
    """In-memory DuckDB connection with duckpgq loaded."""
    c = duckdb.connect(":memory:")
    try:
        c.execute("INSTALL duckpgq FROM community")
    except Exception:
        pass
    try:
        c.execute("LOAD duckpgq")
    except Exception as exc:
        pytest.skip(f"duckpgq extension not available: {exc}")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_schema_version():
    assert SCHEMA_VERSION == 3


def test_node_table_count():
    assert len(NODE_TABLES) == 19


def test_edge_table_count():
    assert len(EDGE_TABLES) == 34


def test_all_node_ddl_returns_copy():
    assert all_node_ddl() == NODE_TABLES
    assert all_node_ddl() is not NODE_TABLES


def test_all_edge_ddl_returns_copy():
    assert all_edge_ddl() == EDGE_TABLES
    assert all_edge_ddl() is not EDGE_TABLES


def test_create_property_graph_sql_lists_all_node_tables():
    """Every node table name must appear in the CREATE PROPERTY GRAPH statement."""
    expected_nodes = [
        "File",
        "Folder",
        "Function",
        "Class",
        "Method",
        "Interface",
        "Community",
        "Process",
        "ArchitectureLayer",
        "Plan",
        "Contract",
        "Learning",
        "ReviewFinding",
        "Session",
        "Study",
        "ADR",
        "Spike",
        "GraphMeta",
        "ParsingWarning",
    ]
    for name in expected_nodes:
        assert name in CREATE_PROPERTY_GRAPH_SQL, f"Missing vertex: {name}"


def test_create_property_graph_sql_lists_all_edge_tables():
    """Every edge type must appear in the CREATE PROPERTY GRAPH statement."""
    expected_edges = [
        "CONTAINS",
        "CONTAINS_FOLDER",
        "DEFINES_FUNCTION",
        "DEFINES_CLASS",
        "DEFINES_INTERFACE",
        "HAS_METHOD",
        "IMPORTS",
        "CALLS",
        "METHOD_CALLS",
        "EXTENDS",
        "IMPLEMENTS",
        "MEMBER_OF_COMMUNITY",
        "STEP_IN_PROCESS",
        "BELONGS_TO_LAYER",
        "PLAN_IMPACTS",
        "PLAN_INTRODUCES_FUNC",
        "PLAN_INTRODUCES_CLASS",
        "CONTRACT_DECLARES_FUNC",
        "CONTRACT_DECLARES_CLASS",
        "LEARNING_RELATES_TO_FILE",
        "LEARNING_RELATES_TO_FUNC",
        "FINDING_ABOUT_FILE",
        "FINDING_ABOUT_FUNC",
        "FINDING_LED_TO",
        "FINDING_ADDRESSED_BY",
        "SESSION_MODIFIED",
        "DEPENDS_ON_PLAN",
        "STUDY_REFERENCES_PLAN",
        "STUDY_REFERENCES_FILE",
        "ADR_GOVERNS",
        "ADR_SUPERSEDES",
        "ADR_CITES_STUDY",
        "ADR_CITES_SPIKE",
        "SPIKE_FOR_PLAN",
    ]
    for name in expected_edges:
        assert name in CREATE_PROPERTY_GRAPH_SQL, f"Missing edge: {name}"


# ---------------------------------------------------------------------------
# Schema creation (requires duckpgq)
# ---------------------------------------------------------------------------


def test_init_schema_creates_all_tables(conn):
    init_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    node_names = [
        "File",
        "Folder",
        "Function",
        "Class",
        "Method",
        "Interface",
        "Community",
        "Process",
        "ArchitectureLayer",
        "Plan",
        "Contract",
        "Learning",
        "ReviewFinding",
        "Session",
        "Study",
        "ADR",
        "Spike",
        "GraphMeta",
        "ParsingWarning",
    ]
    edge_names = [
        "CONTAINS",
        "CONTAINS_FOLDER",
        "DEFINES_FUNCTION",
        "DEFINES_CLASS",
        "DEFINES_INTERFACE",
        "HAS_METHOD",
        "IMPORTS",
        "CALLS",
        "METHOD_CALLS",
        "EXTENDS",
        "IMPLEMENTS",
        "MEMBER_OF_COMMUNITY",
        "STEP_IN_PROCESS",
        "BELONGS_TO_LAYER",
        "PLAN_IMPACTS",
        "PLAN_INTRODUCES_FUNC",
        "PLAN_INTRODUCES_CLASS",
        "CONTRACT_DECLARES_FUNC",
        "CONTRACT_DECLARES_CLASS",
        "LEARNING_RELATES_TO_FILE",
        "LEARNING_RELATES_TO_FUNC",
        "FINDING_ABOUT_FILE",
        "FINDING_ABOUT_FUNC",
        "FINDING_LED_TO",
        "FINDING_ADDRESSED_BY",
        "SESSION_MODIFIED",
        "DEPENDS_ON_PLAN",
        "STUDY_REFERENCES_PLAN",
        "STUDY_REFERENCES_FILE",
        "ADR_GOVERNS",
        "ADR_SUPERSEDES",
        "ADR_CITES_STUDY",
        "ADR_CITES_SPIKE",
        "SPIKE_FOR_PLAN",
    ]
    for name in node_names + edge_names:
        assert name in tables, f"Table not created: {name}"


def test_init_schema_is_idempotent(conn):
    """Calling init_schema twice must not raise."""
    init_schema(conn)
    init_schema(conn)


def test_graph_table_plan_impacts_query(conn):
    """Basic GRAPH_TABLE traversal over PLAN_IMPACTS edge returns correct rows."""
    init_schema(conn)
    conn.execute(
        "INSERT INTO File VALUES ('f:1', 'src/main.py', 'python', 100, '2026-01-01', 50, 'abc')"
    )
    conn.execute(
        "INSERT INTO Plan VALUES ('p:1', 1, 'Test Plan', 'COMPLETE', 'feature',"
        " 'docs/plans/1.md', '2026-01-01', '2026-01-01')"
    )
    conn.execute("INSERT INTO PLAN_IMPACTS VALUES ('p:1', 'f:1', 'MODIFY')")

    rows = conn.execute(
        """
        SELECT t.p_number, t.f_path, t.change_type
        FROM GRAPH_TABLE(agentscaffold_graph
            MATCH (p:Plan)-[e:PLAN_IMPACTS]->(f:File)
            COLUMNS (p.number AS p_number, f.path AS f_path, e.changeType AS change_type)
        ) t
        """
    ).fetchall()
    assert rows == [(1, "src/main.py", "MODIFY")]


def test_graph_table_transitive_imports(conn):
    """Variable-length IMPORTS path pattern works."""
    init_schema(conn)
    conn.execute(
        "INSERT INTO File VALUES ('f:a', 'a.py', 'python', 10, '', 5, ''), "
        "                        ('f:b', 'b.py', 'python', 10, '', 5, ''), "
        "                        ('f:c', 'c.py', 'python', 10, '', 5, '')"
    )
    conn.execute("INSERT INTO IMPORTS (src, dst) VALUES ('f:a', 'f:b'), ('f:b', 'f:c')")

    rows = conn.execute(
        """
        SELECT DISTINCT t.id
        FROM GRAPH_TABLE(agentscaffold_graph
            MATCH (a:File)-[e:IMPORTS]->{1,2}(b:File)
            WHERE b.id = 'f:c'
            COLUMNS (a.id)
        ) t
        """
    ).fetchall()
    ids = {r[0] for r in rows}
    assert "f:a" in ids
    assert "f:b" in ids
    assert "f:c" not in ids


def test_graph_table_adr_governs_two_hop(conn):
    """Two-hop ADR -> Plan -> File traversal works."""
    init_schema(conn)
    conn.execute("INSERT INTO File VALUES ('f:1', 'src/a.py', 'python', 10, '', 5, '')")
    conn.execute(
        "INSERT INTO Plan VALUES"
        " ('p:1', 1, 'Plan One', 'COMPLETE', 'feature', '', '2026-01-01', '')"
    )
    conn.execute(
        "INSERT INTO ADR VALUES ('adr:1', 1, 'ADR One', 'Accepted', '2026-01-01', '', '', '', '')"
    )
    conn.execute("INSERT INTO PLAN_IMPACTS (src, dst, changeType) VALUES ('p:1', 'f:1', 'MODIFY')")
    conn.execute("INSERT INTO ADR_GOVERNS (src, dst) VALUES ('adr:1', 'p:1')")

    rows = conn.execute(
        """
        SELECT DISTINCT t.a_number, t.a_title, t.p_number
        FROM GRAPH_TABLE(agentscaffold_graph
            MATCH (a:ADR)-[g:ADR_GOVERNS]->(p:Plan)-[i:PLAN_IMPACTS]->(f:File)
            WHERE f.path = 'src/a.py'
            COLUMNS (a.number AS a_number, a.title AS a_title, p.number AS p_number)
        ) t
        """
    ).fetchall()
    assert rows == [(1, "ADR One", 1)]
