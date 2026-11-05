"""Finding dispositions and the readers that must respect them."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.findings import (
    DISPOSITIONS,
    get_open_findings,
    record_finding,
    resolve_finding,
)

pytest.importorskip("duckdb", reason="duckdb not installed")

PLAN = 90


@pytest.fixture()
def store():
    s = DuckPGQBackend(":memory:")
    s.init_schema()
    s.execute(
        "INSERT INTO Plan (id, number, title, status, project)"
        f" VALUES ('plan::{PLAN}', {PLAN}, 'Retry budget', 'In Progress', '')"
    )
    yield s
    s.close()


def _finding(store, text: str = "The retry budget is unbounded.") -> str:
    out = record_finding(
        store,
        plan_number=PLAN,
        review_type="devils_advocate",
        category="RISK",
        finding=text,
    )
    return out["id"]


def _status(store, fid: str) -> tuple[str, str]:
    row = store.query(f"SELECT status, resolution FROM ReviewFinding WHERE id = '{fid}'")[0]
    return row["status"], row["resolution"]


def test_dispositions_are_the_three_statuses():
    assert DISPOSITIONS == ("resolved", "deferred", "not_applicable")


def test_resolve_without_a_disposition_resolves_as_before(store):
    fid = _finding(store)
    result = resolve_finding(store, fid, resolution="Capped at three retries.")
    assert result["status"] == "resolved"
    assert _status(store, fid) == ("resolved", "Capped at three retries.")


@pytest.mark.parametrize("disposition", ["deferred", "not_applicable"])
def test_deferred_and_not_applicable_are_recorded_with_their_reason(store, disposition):
    fid = _finding(store)
    result = resolve_finding(store, fid, resolution="Out of scope here.", disposition=disposition)
    assert result["status"] == disposition
    assert result["disposition"] == disposition
    assert _status(store, fid) == (disposition, "Out of scope here.")


@pytest.mark.parametrize("disposition", ["deferred", "not_applicable"])
@pytest.mark.parametrize("reason", ["", "   "])
def test_deferred_and_not_applicable_need_a_reason(store, disposition, reason):
    fid = _finding(store)
    result = resolve_finding(store, fid, resolution=reason, disposition=disposition)
    assert result["status"] == "refused"
    assert "reason" in result["error"]
    assert _status(store, fid)[0] == "open"


def test_an_unknown_disposition_is_refused(store):
    fid = _finding(store)
    result = resolve_finding(store, fid, resolution="x", disposition="wontfix")
    assert result["status"] == "refused"
    assert _status(store, fid)[0] == "open"


def test_a_deferral_can_name_its_backlog_item(store):
    from agentscaffold.graph.backlog import record_backlog_item

    item = record_backlog_item(store, title="Bound the retry budget", plan_number=PLAN)
    fid = _finding(store)
    result = resolve_finding(
        store, fid, resolution="Tracked.", disposition="deferred", backlog_id=item["id"]
    )
    assert result["backlog_id"] == item["id"]
    row = store.query(f"SELECT backlogId FROM ReviewFinding WHERE id = '{fid}'")[0]
    assert row["backlogId"] == item["id"]

    exported = store.export_governance()
    store.execute(f"DELETE FROM ReviewFinding WHERE id = '{fid}'")
    store.import_governance(exported)
    assert _status(store, fid)[0] == "deferred"
    row = store.query(f"SELECT backlogId FROM ReviewFinding WHERE id = '{fid}'")[0]
    assert row["backlogId"] == item["id"]


def test_an_unknown_backlog_item_is_refused(store):
    fid = _finding(store)
    result = resolve_finding(
        store, fid, resolution="Tracked.", disposition="deferred", backlog_id="backlog::nope"
    )
    assert result["status"] == "refused"
    assert _status(store, fid)[0] == "open"


def test_open_finding_readers_exclude_every_disposition(store):
    ids = {d: _finding(store, f"Finding for {d}.") for d in DISPOSITIONS}
    still_open = _finding(store, "Still open.")
    for disposition, fid in ids.items():
        resolve_finding(store, fid, resolution="Reason.", disposition=disposition)
    open_ids = {r["rf.id"] for r in get_open_findings(store, plan_number=PLAN)}
    assert open_ids == {still_open}


def test_plan_card_counts_only_open_findings(store):
    from agentscaffold.mcp.plan_card import _open_finding_summary

    deferred = _finding(store, "Deferred one.")
    _finding(store, "Open one.")
    resolve_finding(store, deferred, resolution="Later.", disposition="deferred")
    assert _open_finding_summary(store, PLAN)["count"] == 1


def test_prune_takes_not_applicable_with_resolved_and_keeps_deferred(store):
    from agentscaffold.graph.prune import select_prunable

    ids = {d: _finding(store, f"Prune {d}.") for d in DISPOSITIONS}
    for disposition, fid in ids.items():
        resolve_finding(store, fid, resolution="Reason.", disposition=disposition)
    selected = select_prunable(store, resolved_findings_before="0d")["resolved_findings"]
    assert {r["id"] for r in selected} == {ids["resolved"], ids["not_applicable"]}


def test_re_recording_a_deferred_finding_keeps_its_disposition(store):
    fid = _finding(store)
    resolve_finding(store, fid, resolution="Later.", disposition="deferred")
    assert _finding(store) == fid
    assert _status(store, fid)[0] == "deferred"


def _dispatch(repo: Path, monkeypatch: pytest.MonkeyPatch, name: str, **args) -> dict:
    from agentscaffold.mcp import freshness
    from agentscaffold.mcp.server import _dispatch_tool

    monkeypatch.setattr(
        freshness, "evaluate_freshness", lambda *_a, **_k: {"freshness_status": "fresh"}
    )
    return _dispatch_tool(name, {"working_path": str(repo), **args})


def test_the_resolve_tool_accepts_a_disposition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.fixtures.lone_project import build_lone_project

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    repo = build_lone_project(tmp_path, draft_plan=True)
    recorded = _dispatch(
        repo,
        monkeypatch,
        "scaffold_record_finding",
        plan_number=PLAN,
        review_type="devils_advocate",
        category="RISK",
        finding="Budget unbounded.",
    )
    refused = _dispatch(
        repo,
        monkeypatch,
        "scaffold_resolve_finding",
        finding_id=recorded["id"],
        resolution=" ",
        disposition="deferred",
    )
    assert refused.get("error")
    deferred = _dispatch(
        repo,
        monkeypatch,
        "scaffold_resolve_finding",
        finding_id=recorded["id"],
        resolution="Next release.",
        disposition="deferred",
    )
    assert deferred["status"] == "deferred"
