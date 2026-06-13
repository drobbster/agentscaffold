"""Tests for record_findings_batch (Plan 151)."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """In-memory DuckPGQBackend with schema initialised."""
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    s = DuckPGQBackend(":memory:")
    s.init_schema()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# record_findings_batch
# ---------------------------------------------------------------------------


def test_record_findings_batch_empty(store):
    from agentscaffold.graph.findings import record_findings_batch

    result = record_findings_batch(
        store, plan_number=151, review_type="quant_architect", findings=[]
    )
    assert result["ids"] == []
    assert result["count"] == 0
    assert result["elapsed_ms"] == 0.0


def test_record_findings_batch_single(store):
    from agentscaffold.graph.findings import record_findings_batch

    result = record_findings_batch(
        store,
        plan_number=151,
        review_type="quant_architect",
        findings=[{"category": "correctness", "finding": "Off-by-one in risk calc"}],
    )
    assert result["count"] == 1
    assert len(result["ids"]) == 1
    assert result["ids"][0].startswith("rf::")


def test_record_findings_batch_multiple(store):
    from agentscaffold.graph.findings import record_findings_batch

    findings = [
        {"category": "correctness", "finding": "Finding A", "severity": "high"},
        {"category": "performance", "finding": "Finding B", "severity": "medium"},
        {"category": "risk", "finding": "Finding C", "severity": "low"},
    ]
    result = record_findings_batch(
        store, plan_number=151, review_type="security", findings=findings
    )
    assert result["count"] == 3
    assert len(set(result["ids"])) == 3  # all unique


def test_record_findings_batch_persists_to_db(store):
    from agentscaffold.graph.findings import record_findings_batch

    findings = [
        {"category": "correctness", "finding": "Persisted finding"},
        {"category": "risk", "finding": "Another persisted finding"},
    ]
    record_findings_batch(store, plan_number=151, review_type="devils_advocate", findings=findings)

    rows = store.query("SELECT id FROM ReviewFinding WHERE planNumber = 151")
    assert len(rows) == 2


def test_record_findings_batch_default_severity(store):
    from agentscaffold.graph.findings import record_findings_batch

    result = record_findings_batch(
        store,
        plan_number=151,
        review_type="quant_architect",
        findings=[{"category": "performance", "finding": "Slow query"}],
    )
    fid = result["ids"][0]
    rows = store.query(f"SELECT severity FROM ReviewFinding WHERE id = '{fid}'")
    assert rows[0]["severity"] == "medium"


def test_record_findings_batch_custom_severity(store):
    from agentscaffold.graph.findings import record_findings_batch

    result = record_findings_batch(
        store,
        plan_number=151,
        review_type="security",
        findings=[{"category": "auth", "finding": "Missing rate limit", "severity": "critical"}],
    )
    fid = result["ids"][0]
    rows = store.query(f"SELECT severity FROM ReviewFinding WHERE id = '{fid}'")
    assert rows[0]["severity"] == "critical"


def test_record_findings_batch_all_status_open(store):
    from agentscaffold.graph.findings import record_findings_batch

    findings = [{"category": "c", "finding": f"F{i}"} for i in range(5)]
    result = record_findings_batch(
        store, plan_number=151, review_type="quant_architect", findings=findings
    )

    for fid in result["ids"]:
        rows = store.query(f"SELECT status FROM ReviewFinding WHERE id = '{fid}'")
        assert rows[0]["status"] == "open"


def test_record_findings_batch_result_metadata(store):
    from agentscaffold.graph.findings import record_findings_batch

    result = record_findings_batch(
        store,
        plan_number=151,
        review_type="security",
        findings=[{"category": "c", "finding": "f"}],
    )
    assert result["plan_number"] == 151
    assert result["review_type"] == "security"
    assert "elapsed_ms" in result
    assert "created_at" in result


def test_record_findings_batch_deterministic_ids(store):
    """Same content generates the same IDs (no duplicates in graph but IDs stable)."""
    from agentscaffold.graph.findings import record_findings_batch

    findings = [{"category": "correctness", "finding": "Stable ID test"}]
    r1 = record_findings_batch(
        store, plan_number=151, review_type="quant_architect", findings=findings
    )
    r2 = record_findings_batch(
        store, plan_number=151, review_type="quant_architect", findings=findings
    )
    assert r1["ids"][0] == r2["ids"][0]


def test_record_findings_batch_with_file_paths(store):
    """file_paths on items are accepted without raising (file may not exist in graph)."""
    from agentscaffold.graph.findings import record_findings_batch

    findings = [
        {
            "category": "correctness",
            "finding": "Bug in file",
            "file_paths": ["packages/agentscaffold/src/agentscaffold/graph/backlog.py"],
        }
    ]
    result = record_findings_batch(
        store, plan_number=151, review_type="quant_architect", findings=findings
    )
    assert result["count"] == 1


# ---------------------------------------------------------------------------
# MCP tool dispatch
# ---------------------------------------------------------------------------


def test_mcp_record_findings_batch_basic(store):
    from agentscaffold.mcp.server import _tool_record_findings_batch

    meta = {"session": "test"}
    args = {
        "plan_number": 151,
        "review_type": "quant_architect",
        "findings": [
            {"category": "correctness", "finding": "MCP batch finding A"},
            {"category": "risk", "finding": "MCP batch finding B", "severity": "high"},
        ],
    }
    result = _tool_record_findings_batch(store, args, meta)
    assert result["count"] == 2
    assert result["meta"] == meta


def test_mcp_record_findings_batch_empty(store):
    from agentscaffold.mcp.server import _tool_record_findings_batch

    result = _tool_record_findings_batch(
        store,
        {"plan_number": 151, "review_type": "security", "findings": []},
        {},
    )
    assert result["count"] == 0
    assert result["ids"] == []


def test_mcp_record_findings_batch_missing_plan_number(store):
    from agentscaffold.mcp.server import _tool_record_findings_batch

    result = _tool_record_findings_batch(
        store,
        {"review_type": "security", "findings": []},
        {},
    )
    assert "error" in result


def test_mcp_record_findings_batch_missing_review_type(store):
    from agentscaffold.mcp.server import _tool_record_findings_batch

    result = _tool_record_findings_batch(
        store,
        {"plan_number": 151, "findings": []},
        {},
    )
    assert "error" in result


def test_mcp_record_findings_batch_invalid_findings_type(store):
    from agentscaffold.mcp.server import _tool_record_findings_batch

    result = _tool_record_findings_batch(
        store,
        {"plan_number": 151, "review_type": "security", "findings": "not a list"},
        {},
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# Coexistence: batch does not break existing single record_finding
# ---------------------------------------------------------------------------


def test_batch_and_single_coexist(store):
    """Mixing single and batch record calls should not conflict."""
    from agentscaffold.graph.findings import record_finding, record_findings_batch

    single = record_finding(
        store,
        plan_number=151,
        review_type="quant_architect",
        category="correctness",
        finding="Single finding",
    )
    batch = record_findings_batch(
        store,
        plan_number=151,
        review_type="security",
        findings=[{"category": "risk", "finding": "Batch finding"}],
    )

    rows = store.query("SELECT id FROM ReviewFinding WHERE planNumber = 151")
    assert len(rows) == 2
    ids = {r["id"] for r in rows}
    assert single["id"] in ids
    assert batch["ids"][0] in ids
