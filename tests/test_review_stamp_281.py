"""Plan 281 Step A0: the pre-implementation review stamp survives reindexing.

``stamp_plan_reviewed`` wrote ``Plan.reviewedAt``. Plan rows are derived
governance: a reindex after any governance doc change deletes and re-ingests
them, and a schema rebuild drops them. The stamp was lost each time, so the
strict gate refused plans that had been reviewed. The stamp now lives in the
preserved ``PlanReview`` table.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscaffold.config import load_config
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.review.queries import (
    get_plan_review,
    get_plan_reviewed_at,
    stamp_plan_reviewed,
)

pytest.importorskip("duckdb", reason="duckdb not installed")

PLAN = 90
STRICT = "freshness:\n  gate_strict: true\n"


def _project(tmp_path: Path, extra_config: str = "") -> Path:
    from tests.fixtures.lone_project import build_lone_project

    return build_lone_project(tmp_path, draft_plan=True, extra_config=extra_config)


def _db(tmp_path: Path) -> Path:
    return tmp_path / "lone.duckdb"


def _stamp(tmp_path: Path, **kwargs: object) -> str:
    store = DuckPGQBackend(_db(tmp_path))
    try:
        ts = stamp_plan_reviewed(store, PLAN, **kwargs)
    finally:
        store.close()
    assert ts is not None
    return ts


def _reviewed_at(tmp_path: Path) -> str | None:
    store = DuckPGQBackend(_db(tmp_path), read_only=True)
    try:
        return get_plan_reviewed_at(store, PLAN)
    finally:
        store.close()


def _edit_plan(repo: Path) -> None:
    plan = next((repo / "docs" / "ai" / "plans").glob(f"plan_{PLAN:03d}_*.md"))
    plan.write_text(plan.read_text() + "- [ ] Step 3: Document the budget.\n")


def test_stamp_survives_an_incremental_reindex_of_its_plan(tmp_path: Path):
    repo = _project(tmp_path)
    ts = _stamp(tmp_path)

    _edit_plan(repo)
    run_pipeline(repo, load_config(repo / "scaffold.yaml"), incremental=True, quiet=True)

    assert _reviewed_at(tmp_path) == ts


def test_stamp_survives_a_full_reindex(tmp_path: Path):
    repo = _project(tmp_path)
    ts = _stamp(tmp_path)

    _edit_plan(repo)
    run_pipeline(repo, load_config(repo / "scaffold.yaml"), quiet=True)

    assert _reviewed_at(tmp_path) == ts


def test_stamp_survives_a_schema_rebuild(tmp_path: Path):
    repo = _project(tmp_path)
    ts = _stamp(tmp_path)

    store = DuckPGQBackend(_db(tmp_path))
    try:
        store.execute("UPDATE GraphMeta SET schemaVersion = schemaVersion - 1")
    finally:
        store.close()
    run_pipeline(repo, load_config(repo / "scaffold.yaml"), quiet=True)

    assert _reviewed_at(tmp_path) == ts


def test_upgrading_a_graph_from_before_the_table_keeps_its_stamps(tmp_path: Path):
    repo = _project(tmp_path)
    legacy = "2026-10-01T12:00:00+00:00"
    store = DuckPGQBackend(_db(tmp_path))
    try:
        store.execute("DROP TABLE PlanReview")
        store.execute(f"UPDATE Plan SET reviewedAt = '{legacy}' WHERE number = {PLAN}")
        store.execute("UPDATE GraphMeta SET schemaVersion = 11")
    finally:
        store.close()

    run_pipeline(repo, load_config(repo / "scaffold.yaml"), quiet=True)

    store = DuckPGQBackend(_db(tmp_path), read_only=True)
    try:
        rows = store.query("SELECT planNumber, reviewedAt FROM PlanReview")
        review = get_plan_review(store, PLAN)
    finally:
        store.close()
    assert [(r["planNumber"], r["reviewedAt"]) for r in rows] == [(PLAN, legacy)]
    assert review == {"reviewedAt": legacy, "reviewedCommits": {}}


def test_stamp_is_written_to_the_governance_artifact(tmp_path: Path):
    from agentscaffold.graph.governance_store import serialize_governance

    _project(tmp_path)
    ts = _stamp(tmp_path)

    store = DuckPGQBackend(_db(tmp_path), read_only=True)
    try:
        path = serialize_governance(store, tmp_path / "governance.json")
    finally:
        store.close()

    rows = json.loads(path.read_text())["nodes"]["PlanReview"]["rows"]
    assert [(r["planNumber"], r["reviewedAt"]) for r in rows] == [(PLAN, ts)]


def test_restamping_replaces_the_time_and_commits(tmp_path: Path):
    _project(tmp_path)
    first = _stamp(tmp_path, commits={"lone": "aaa111"})
    second = _stamp(tmp_path, commits={"lone": "bbb222"})

    store = DuckPGQBackend(_db(tmp_path), read_only=True)
    try:
        review = get_plan_review(store, PLAN)
        count = store.query("SELECT COUNT(*) AS n FROM PlanReview")[0]["n"]
    finally:
        store.close()

    assert second >= first
    assert review == {"reviewedAt": second, "reviewedCommits": {"lone": "bbb222"}}
    assert count == 1


def test_a_plan_not_in_the_graph_is_not_stamped(tmp_path: Path):
    _project(tmp_path)
    store = DuckPGQBackend(_db(tmp_path))
    try:
        assert stamp_plan_reviewed(store, 999) is None
        assert get_plan_reviewed_at(store, 999) is None
    finally:
        store.close()


def test_a_graph_without_the_table_falls_back_to_the_plan_column(tmp_path: Path):
    store = DuckPGQBackend(":memory:")
    try:
        store.init_schema()
        store.execute(
            "INSERT INTO Plan (id, number, title, reviewedAt)"
            " VALUES ('plan::152', 152, 't', '2026-03-17T00:00:00+00:00')"
        )
        store.execute("DROP TABLE PlanReview")
        assert get_plan_reviewed_at(store, 152) == "2026-03-17T00:00:00+00:00"
        assert get_plan_reviewed_at(store, 153) is None
    finally:
        store.close()


def _prepare(repo: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from agentscaffold.mcp import freshness
    from agentscaffold.mcp.server import _dispatch_tool

    # The fixture is not a git repo, so freshness would read "unknown" and
    # defer the gate before the review check runs.
    monkeypatch.setattr(
        freshness, "evaluate_freshness", lambda *_a, **_k: {"freshness_status": "fresh"}
    )
    return _dispatch_tool(
        "scaffold_prepare_implementation",
        {"working_path": str(repo), "plan_number": PLAN, "gate_transition": True},
    )


def test_strict_gate_refuses_an_unreviewed_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _project(tmp_path, extra_config=STRICT)
    result = _prepare(repo, monkeypatch)
    assert result.get("gate_deferred") is True
    assert f"Run 'begin plan {PLAN}' first." in result["error"]


def test_strict_gate_passes_a_reviewed_plan_after_its_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _project(tmp_path, extra_config=STRICT)
    _stamp(tmp_path)

    _edit_plan(repo)
    run_pipeline(repo, load_config(repo / "scaffold.yaml"), incremental=True, quiet=True)

    result = _prepare(repo, monkeypatch)
    assert result.get("gate_deferred") is not True
    assert result.get("plan_number") == PLAN
