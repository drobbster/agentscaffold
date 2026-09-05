"""Tests for duckpgq_schema.py — Step A.5."""

from __future__ import annotations

import pytest

from agentscaffold.graph.duckpgq_schema import (
    CREATE_PROPERTY_GRAPH_SQL,
    EDGE_DEFS,
    EDGE_TABLE_NAMES,
    EDGE_TABLES,
    NODE_TABLE_NAMES,
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
    assert SCHEMA_VERSION == 11  # bumped in Plan 265 (PlanStep / DEPENDS_ON_STEPS)


def test_backlogitem_ddl_includes_resolution():
    backlog_ddl = next(s for s in NODE_TABLES if "BacklogItem" in s)
    assert "resolution" in backlog_ddl


def test_backlogitem_resolution_column_added_to_existing_table(conn):
    """Plan 255: ALTER adds resolution without a SCHEMA_VERSION rebuild."""
    conn.execute("DROP TABLE IF EXISTS BacklogItem")
    conn.execute(
        """
        CREATE TABLE BacklogItem (
            id VARCHAR PRIMARY KEY,
            planNumber BIGINT,
            title VARCHAR,
            priority VARCHAR,
            effort VARCHAR,
            status VARCHAR,
            source VARCHAR,
            createdAt VARCHAR,
            archivedAt VARCHAR
        )
        """
    )
    init_schema(conn)
    cols = [
        str(r[0]).lower()
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'BacklogItem'"
        ).fetchall()
    ]
    assert "resolution" in cols


def test_extends_additive_columns_on_existing_table(conn):
    """Plan 262: resolved/baseName ALTER without a SCHEMA_VERSION rebuild."""
    from agentscaffold.graph.duckpgq_schema import ensure_additive_columns

    conn.execute("DROP TABLE IF EXISTS EXTENDS")
    conn.execute("CREATE TABLE EXTENDS (src VARCHAR NOT NULL, dst VARCHAR NOT NULL)")
    ensure_additive_columns(conn)
    cols = {
        str(r[0]).lower()
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'EXTENDS'"
        ).fetchall()
    }
    assert "resolved" in cols
    assert "basename" in cols


def test_schema_version_unchanged_by_extends_columns():
    assert SCHEMA_VERSION == 11


def test_session_additive_columns_on_existing_table(conn):
    """Plan 263: decisions/endedAt ALTER without a SCHEMA_VERSION rebuild."""
    from agentscaffold.graph.duckpgq_schema import ensure_additive_columns

    conn.execute("DROP TABLE IF EXISTS Session")
    conn.execute(
        """
        CREATE TABLE Session (
            id VARCHAR PRIMARY KEY,
            date VARCHAR,
            planNumbers VARCHAR,
            filesModified VARCHAR,
            summary VARCHAR
        )
        """
    )
    ensure_additive_columns(conn)
    cols = {
        str(r[0]).lower()
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'Session'"
        ).fetchall()
    }
    assert "decisions" in cols
    assert "endedat" in cols


def test_schema_version_unchanged_by_session_columns():
    assert SCHEMA_VERSION == 11


def test_finding_evidence_additive_columns_on_existing_table(conn):
    """Plan 264: evidenceKind/evidence ALTER without a SCHEMA_VERSION rebuild."""
    from agentscaffold.graph.duckpgq_schema import ensure_additive_columns

    conn.execute("DROP TABLE IF EXISTS ReviewFinding")
    conn.execute("DROP TABLE IF EXISTS Learning")
    conn.execute(
        """
        CREATE TABLE ReviewFinding (
            id VARCHAR PRIMARY KEY,
            finding VARCHAR,
            status VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE Learning (
            id VARCHAR PRIMARY KEY,
            description VARCHAR
        )
        """
    )
    ensure_additive_columns(conn)
    finding_cols = {
        str(r[0]).lower()
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ReviewFinding'"
        ).fetchall()
    }
    learning_cols = {
        str(r[0]).lower()
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'Learning'"
        ).fetchall()
    }
    assert "evidencekind" in finding_cols
    assert "evidence" in finding_cols
    assert "evidencekind" in learning_cols
    assert "evidence" in learning_cols


def test_schema_version_unchanged_by_evidence_columns():
    assert SCHEMA_VERSION == 11


def test_planstep_and_depends_on_steps_are_in_schema():
    assert "PlanStep" in NODE_TABLE_NAMES
    assert "PLAN_HAS_STEP" in EDGE_TABLE_NAMES
    assert "DEPENDS_ON_STEPS" in EDGE_TABLE_NAMES
    depends = next(e for e in EDGE_DEFS if e.name == "DEPENDS_ON_STEPS")
    assert depends.src == "Plan" and depends.dst == "Plan"
    cols = {name for name, _sql in depends.properties}
    assert cols == {"fromStep", "fromStepEnd", "toStep", "toStepEnd"}
    process = next(e for e in EDGE_DEFS if e.name == "STEP_IN_PROCESS")
    assert process.src == "Function"


def test_ensure_additive_columns_is_noop_when_table_missing(conn):
    from agentscaffold.graph.duckpgq_schema import ensure_additive_columns

    conn.execute("DROP TABLE IF EXISTS BacklogItem")
    ensure_additive_columns(conn)


def test_fresh_backend_can_init_schema_after_constructor_additive_check(tmp_path):
    """Constructor calls ensure_additive_columns before tables exist.

    An ALTER on a missing table aborts the DuckDB transaction even when the
    error is caught; init_schema must still be able to CREATE TABLE.
    """
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    store = DuckPGQBackend(tmp_path / "fresh.db")
    store.init_schema()
    rows = store.query("SELECT count(*) AS n FROM Session")
    assert rows[0]["n"] == 0
    store.close()


def test_missing_additive_columns_detects_pre_255_shape(conn):
    from agentscaffold.graph.duckpgq_schema import missing_additive_columns

    conn.execute("DROP TABLE IF EXISTS BacklogItem")
    conn.execute(
        """
        CREATE TABLE BacklogItem (
            id VARCHAR PRIMARY KEY,
            title VARCHAR,
            status VARCHAR
        )
        """
    )
    assert ("BacklogItem", "resolution") in missing_additive_columns(conn)


def test_the_plan_252_bump_changed_no_tables():
    """Version 10 is a *derivation* change, not a DDL one.

    Plan 252 bumped the version to force existing graphs through a rebuild, so
    they gain the IMPORTS edges that relative imports should always have
    produced. No table was added or altered. The two counts below being
    unchanged across the bump is what distinguishes that case from a real schema
    migration, and keeps the bump from being read later as evidence of one.

    Plan 255 later added BacklogItem.resolution at this same version, via an
    additive ALTER rather than a bump. So version 10 is not a promise that the
    columns never moved -- only that the set of tables did not.
    """
    assert len(NODE_TABLES) == 22
    assert len(EDGE_TABLES) == 39


def test_node_table_count():
    assert len(NODE_TABLES) == 22  # +PlanStep (Plan 265)


def test_edge_table_count():
    assert len(EDGE_TABLES) == 39  # +PLAN_HAS_STEP, DEPENDS_ON_STEPS (Plan 265)


def test_all_node_ddl_returns_copy():
    assert all_node_ddl() == NODE_TABLES
    assert all_node_ddl() is not NODE_TABLES


def test_all_edge_ddl_returns_copy():
    assert all_edge_ddl() == EDGE_TABLES
    assert all_edge_ddl() is not EDGE_TABLES


def test_create_property_graph_sql_lists_all_node_tables():
    """Every node table name must appear in the CREATE PROPERTY GRAPH statement."""
    assert len(NODE_TABLE_NAMES) == 22
    for name in NODE_TABLE_NAMES:
        assert name in CREATE_PROPERTY_GRAPH_SQL, f"Missing vertex: {name}"


def test_create_property_graph_sql_lists_all_edge_tables():
    """Every edge type must appear in the CREATE PROPERTY GRAPH statement."""
    assert len(EDGE_TABLE_NAMES) == 39
    for name in EDGE_TABLE_NAMES:
        assert name in CREATE_PROPERTY_GRAPH_SQL, f"Missing edge: {name}"


# ---------------------------------------------------------------------------
# Drift guardrails: edge names, edge DDL, and the property-graph statement are
# all generated from EDGE_DEFS, so they can never disagree. These tests fail
# loudly if that invariant is ever broken.
# ---------------------------------------------------------------------------


def test_edge_names_derive_consistently():
    """EDGE_DEFS, EDGE_TABLE_NAMES, and EDGE_TABLES all describe the same edges."""
    def_names = [edge.name for edge in EDGE_DEFS]
    assert list(EDGE_TABLE_NAMES) == def_names
    assert len(EDGE_TABLES) == len(EDGE_DEFS)
    for name, ddl in zip(def_names, EDGE_TABLES):
        assert f"CREATE TABLE IF NOT EXISTS {name} (" in ddl


def test_edge_names_unique():
    assert len(EDGE_TABLE_NAMES) == len(set(EDGE_TABLE_NAMES))


def test_node_names_unique():
    assert len(NODE_TABLE_NAMES) == len(set(NODE_TABLE_NAMES))


def test_edge_ddl_includes_extra_property_columns():
    """Edges with extra columns render them in the generated DDL."""
    ddl_by_name = dict(zip(EDGE_TABLE_NAMES, EDGE_TABLES))
    assert "importedNames VARCHAR" in ddl_by_name["IMPORTS"]
    assert "confidence DOUBLE" in ddl_by_name["CALLS"]
    assert "refKey VARCHAR" in ddl_by_name["CONFIG_REFERENCES"]
    assert "symbol VARCHAR" in ddl_by_name["CONFIG_REFERENCES"]


def test_governance_subsets_are_valid():
    """The backend governance tuples must be subsets of the derived names."""
    from agentscaffold.graph.duckpgq_backend import (
        _GOVERNANCE_EDGE_TABLES,
        _GOVERNANCE_NODE_TABLES,
    )

    assert set(_GOVERNANCE_EDGE_TABLES) <= set(EDGE_TABLE_NAMES)
    assert set(_GOVERNANCE_NODE_TABLES) <= set(NODE_TABLE_NAMES)


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
    # Derived from the single source of truth -- asserts completeness, not a
    # hand-maintained subset, so this test cannot silently drift.
    for name in list(NODE_TABLE_NAMES) + list(EDGE_TABLE_NAMES):
        assert name in tables, f"Table not created: {name}"


def test_init_schema_is_idempotent(conn):
    """Calling init_schema twice must not raise."""
    init_schema(conn)
    init_schema(conn)


def test_graph_table_plan_impacts_query(conn):
    """Basic GRAPH_TABLE traversal over PLAN_IMPACTS edge returns correct rows."""
    init_schema(conn)
    conn.execute(
        "INSERT INTO File VALUES ('f:1', 'src/main.py', 'python', 100, '2026-01-01', 50, 'abc', '')"
    )
    conn.execute(
        "INSERT INTO Plan VALUES ('p:1', 1, 'Test Plan', 'COMPLETE', 'feature',"
        " 'docs/plans/1.md', '2026-01-01', '2026-01-01', NULL, '')"
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
        "INSERT INTO File VALUES ('f:a', 'a.py', 'python', 10, '', 5, '', ''), "
        "                        ('f:b', 'b.py', 'python', 10, '', 5, '', ''), "
        "                        ('f:c', 'c.py', 'python', 10, '', 5, '', '')"
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
    conn.execute("INSERT INTO File VALUES ('f:1', 'src/a.py', 'python', 10, '', 5, '', '')")
    conn.execute(
        "INSERT INTO Plan VALUES"
        " ('p:1', 1, 'Plan One', 'COMPLETE', 'feature', '', '2026-01-01', '', NULL, '')"
    )
    conn.execute(
        "INSERT INTO ADR VALUES"
        " ('adr:1', 1, 'ADR One', 'Accepted', '2026-01-01', '', '', '', '', '')"
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
