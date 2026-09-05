"""Evidence provenance and FINDING_ADDRESSED_BY (Plan 264)."""

from __future__ import annotations

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.duckpgq_schema import SCHEMA_VERSION, ensure_additive_columns
from agentscaffold.graph.findings import (
    get_open_findings,
    record_finding,
    record_findings_batch,
    resolve_finding,
)


@pytest.fixture()
def store():
    s = DuckPGQBackend(":memory:")
    s.init_schema()
    yield s
    s.close()


def _insert_plan(store: DuckPGQBackend, number: int = 264) -> str:
    plan_id = f"plan::{number}"
    store.create_node(
        "Plan",
        {"id": plan_id, "number": number, "title": "Evidence", "status": "In Progress"},
    )
    return plan_id


def test_omit_evidence_is_unspecified(store):
    result = record_finding(
        store,
        plan_number=264,
        review_type="pre_implementation",
        category="correctness",
        finding="omit must not look measured",
    )
    assert result["evidence_kind"] == "unspecified"
    assert result["evidence"] == ""
    rows = store.query(
        f"SELECT evidenceKind, evidence FROM ReviewFinding WHERE id = '{result['id']}'"
    )
    assert rows[0]["evidenceKind"] == "unspecified"
    assert rows[0]["evidence"] == ""


@pytest.mark.parametrize(
    "kind",
    ["command", "test", "file_ref", "graph_query", "external_doc", "inferred"],
)
def test_each_evidence_kind_round_trips(store, kind):
    result = record_finding(
        store,
        plan_number=264,
        review_type="pre_implementation",
        category="correctness",
        finding=f"kind {kind}",
        evidence_kind=kind,
        evidence=f"cite:{kind}",
    )
    assert result["evidence_kind"] == kind
    rows = store.query(
        f"SELECT evidenceKind, evidence FROM ReviewFinding WHERE id = '{result['id']}'"
    )
    assert rows[0]["evidenceKind"] == kind
    assert rows[0]["evidence"] == f"cite:{kind}"


def test_unknown_kind_becomes_unspecified(store):
    result = record_finding(
        store,
        plan_number=264,
        review_type="pre_implementation",
        category="correctness",
        finding="bad kind",
        evidence_kind="measured_really",
        evidence="nope",
    )
    assert result["evidence_kind"] == "unspecified"


def test_long_evidence_is_truncated(store):
    result = record_finding(
        store,
        plan_number=264,
        review_type="pre_implementation",
        category="correctness",
        finding="long cite",
        evidence_kind="command",
        evidence="x" * 5000,
    )
    assert result["evidence"].endswith(" ...[truncated]")
    assert len(result["evidence"]) <= 2000


def test_resolve_with_existing_plan_creates_addressed_by(store):
    plan_id = _insert_plan(store)
    recorded = record_finding(
        store,
        plan_number=264,
        review_type="pre_implementation",
        category="correctness",
        finding="needs a plan link",
        evidence_kind="inferred",
    )
    resolved = resolve_finding(
        store,
        recorded["id"],
        resolution="fixed in this plan",
        resolved_by_plan=264,
    )
    assert resolved["status"] == "resolved"
    assert resolved["addressed_by_plan"] == 264
    rows = store.query("SELECT src, dst FROM FINDING_ADDRESSED_BY")
    assert len(rows) == 1
    assert rows[0]["src"] == recorded["id"]
    assert rows[0]["dst"] == plan_id
    led = store.query("SELECT count(*) AS n FROM FINDING_LED_TO")
    assert led[0]["n"] == 0


def test_resolve_without_plan_vertex_creates_no_edge(store):
    recorded = record_finding(
        store,
        plan_number=264,
        review_type="pre_implementation",
        category="correctness",
        finding="plan vertex missing",
    )
    resolved = resolve_finding(
        store,
        recorded["id"],
        resolution="named plan 999",
        resolved_by_plan=999,
    )
    assert resolved["status"] == "resolved"
    assert resolved["addressed_by_plan"] is None
    rows = store.query("SELECT count(*) AS n FROM FINDING_ADDRESSED_BY")
    assert rows[0]["n"] == 0


def test_resolve_unknown_finding_creates_no_edge(store):
    _insert_plan(store)
    result = resolve_finding(
        store,
        "rf::doesnotexist",
        resolution="nope",
        resolved_by_plan=264,
    )
    assert result["status"] == "not_found"
    rows = store.query("SELECT count(*) AS n FROM FINDING_ADDRESSED_BY")
    assert rows[0]["n"] == 0


def test_batch_carries_per_item_evidence(store):
    result = record_findings_batch(
        store,
        plan_number=264,
        review_type="pre_implementation",
        findings=[
            {
                "category": "correctness",
                "finding": "measured",
                "evidence_kind": "test",
                "evidence": "tests/test_findings_evidence.py",
            },
            {"category": "completeness", "finding": "omitted"},
        ],
    )
    assert result["count"] == 2
    rows = {
        r["finding"]: r["evidenceKind"]
        for r in store.query("SELECT finding, evidenceKind FROM ReviewFinding")
    }
    assert rows["measured"] == "test"
    assert rows["omitted"] == "unspecified"


def test_open_findings_surface_evidence(store):
    record_finding(
        store,
        plan_number=264,
        review_type="pre_implementation",
        category="correctness",
        finding="visible evidence",
        evidence_kind="graph_query",
        evidence="SELECT count(*) FROM FINDING_ADDRESSED_BY",
    )
    open_rows = get_open_findings(store, plan_number=264)
    assert open_rows[0]["rf.evidenceKind"] == "graph_query"
    assert "FINDING_ADDRESSED_BY" in open_rows[0]["rf.evidence"]


def test_mcp_function_ids_create_about_func(store, monkeypatch):
    monkeypatch.setattr("agentscaffold.mcp.server._current_project_or_none", lambda: None)
    store.create_node(
        "Function",
        {"id": "func::a.py::foo::1", "name": "foo", "filePath": "a.py"},
    )
    from agentscaffold.mcp.server import _tool_record_finding

    result = _tool_record_finding(
        store,
        {
            "plan_number": 264,
            "review_type": "pre_implementation",
            "category": "correctness",
            "finding": "symbol-level",
            "function_ids": ["func::a.py::foo::1"],
            "evidence_kind": "file_ref",
            "evidence": "a.py:1",
        },
        {},
    )
    assert result["status"] == "open"
    rows = store.query("SELECT dst FROM FINDING_ABOUT_FUNC")
    assert rows[0]["dst"] == "func::a.py::foo::1"


def test_upgrade_adds_columns_and_keeps_existing_rows():
    """Plan 256 guard: ALTER on an old ReviewFinding / Learning table."""
    store = DuckPGQBackend(":memory:")
    conn = store._conn
    conn.execute("DROP TABLE IF EXISTS ReviewFinding")
    conn.execute("DROP TABLE IF EXISTS Learning")
    conn.execute(
        """
        CREATE TABLE ReviewFinding (
            id VARCHAR PRIMARY KEY,
            reviewType VARCHAR,
            planNumber BIGINT,
            severity VARCHAR,
            category VARCHAR,
            finding VARCHAR,
            resolution VARCHAR,
            status VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE Learning (
            id VARCHAR PRIMARY KEY,
            learningId VARCHAR,
            planNumber BIGINT,
            description VARCHAR,
            target VARCHAR,
            status VARCHAR
        )
        """
    )
    conn.execute(
        "INSERT INTO ReviewFinding VALUES "
        "('rf::old', 'pre', 1, 'high', 'correctness', 'legacy', '', 'open')"
    )
    conn.execute(
        "INSERT INTO Learning VALUES "
        "('learning::L1', 'L1', 1, 'legacy learning', 'standards', 'pending')"
    )
    ensure_additive_columns(conn)
    finding = conn.execute(
        "SELECT evidenceKind, finding FROM ReviewFinding WHERE id = 'rf::old'"
    ).fetchone()
    learning = conn.execute(
        "SELECT evidenceKind, description FROM Learning WHERE id = 'learning::L1'"
    ).fetchone()
    assert finding[0] == "unspecified"
    assert finding[1] == "legacy"
    assert learning[0] == "unspecified"
    assert learning[1] == "legacy learning"
    assert SCHEMA_VERSION == 10
    store.close()
