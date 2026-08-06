"""Tests for selective governance pruning (Plan 219)."""

from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402
from agentscaffold.graph.prune import (  # noqa: E402
    apply_prune,
    parse_age,
    select_prunable,
)


@pytest.fixture()
def store():
    s = DuckPGQBackend(":memory:")
    s.init_schema()
    yield s
    s.close()


def _finding(store, fid, status):
    store.create_node(
        "ReviewFinding",
        {
            "id": fid,
            "reviewType": "brief",
            "planNumber": 1,
            "severity": "low",
            "category": "x",
            "finding": "f",
            "resolution": "",
            "status": status,
        },
    )


def _session(store, sid, date):
    store.create_node(
        "Session",
        {
            "id": sid,
            "date": date,
            "planNumbers": "[]",
            "filesModified": "[]",
            "summary": "s",
        },
    )


def _backlog(store, bid, status, archived_at):
    store.create_node(
        "BacklogItem",
        {
            "id": bid,
            "planNumber": 1,
            "title": "t",
            "priority": "P2",
            "effort": "M",
            "status": status,
            "source": "review",
            "createdAt": "2020-01-01T00:00:00+00:00",
            "archivedAt": archived_at,
        },
    )


def test_parse_age_valid():
    assert parse_age("30d") == 30
    assert parse_age("0d") == 0


@pytest.mark.parametrize("bad", ["30", "abc", "-5d", "d", ""])
def test_parse_age_invalid(bad):
    with pytest.raises(ValueError):
        parse_age(bad)


def test_select_is_status_aware(store):
    _finding(store, "rf::open", "open")
    _finding(store, "rf::resolved", "resolved")
    _session(store, "s::old", "2000-01-01T00:00:00+00:00")
    _session(store, "s::new", "2999-01-01T00:00:00+00:00")
    _backlog(store, "b::old", "archived", "2000-01-01T00:00:00+00:00")
    _backlog(store, "b::open", "open", "")
    _backlog(store, "b::new", "archived", "2999-01-01T00:00:00+00:00")

    selection = select_prunable(
        store,
        resolved_findings_before="30d",
        sessions_before="30d",
        archived_backlog_before="30d",
    )

    finding_ids = {r["id"] for r in selection["resolved_findings"]}
    session_ids = {r["id"] for r in selection["sessions"]}
    backlog_ids = {r["id"] for r in selection["archived_backlog"]}

    assert finding_ids == {"rf::resolved"}  # open finding untouched
    assert session_ids == {"s::old"}  # recent session untouched
    assert backlog_ids == {"b::old"}  # open + recent archived untouched


def test_select_only_requested_categories(store):
    _finding(store, "rf::resolved", "resolved")
    _session(store, "s::old", "2000-01-01T00:00:00+00:00")

    selection = select_prunable(store, sessions_before="1d")
    assert selection["resolved_findings"] == []
    assert {r["id"] for r in selection["sessions"]} == {"s::old"}


def _appendix_finding(store, fid, finding, review_type="plan_appendix"):
    store.create_node(
        "ReviewFinding",
        {
            "id": fid,
            "reviewType": review_type,
            "planNumber": 214,
            "severity": "medium",
            "category": "PATTERN",
            "finding": finding,
            "resolution": "",
            "status": "open",
        },
    )


def test_malformed_finding_selection_targets_fragments_only(store):
    """Plan 250: the store-level remedy for rows the old extractor manufactured.

    Anchoring the parser stops new ones, but nothing removes what is stored --
    create_node is ON CONFLICT DO NOTHING so re-indexing never deletes, and
    purging the serialized export is overwritten from the store on the next index.
    """
    _appendix_finding(store, "rf::bad", "` detector and reviewer memory become non-empty.")
    _appendix_finding(store, "rf::bad2", ") so the count stays at 1.")
    _appendix_finding(store, "rf::good", "Upstream contract is unversioned.")
    _appendix_finding(store, "rf::codespan", "`_FINDING_RE` is unanchored.")
    _appendix_finding(store, "rf::runtime", "` looks odd but came from review", "pre_review")

    selection = select_prunable(store, malformed_findings=True)

    assert {r["id"] for r in selection["malformed_findings"]} == {"rf::bad", "rf::bad2"}


def test_malformed_findings_are_not_selected_unless_asked(store):
    _appendix_finding(store, "rf::bad", "` detector and reviewer memory become non-empty.")

    assert select_prunable(store, sessions_before="1d")["malformed_findings"] == []


def test_apply_deletes_malformed_findings(store):
    _appendix_finding(store, "rf::bad", "` detector and reviewer memory become non-empty.")
    _appendix_finding(store, "rf::good", "Upstream contract is unversioned.")

    selection = select_prunable(store, malformed_findings=True)
    counts = apply_prune(store, selection)

    assert counts["malformed_findings"] == 1
    remaining = {r["id"] for r in store.query("SELECT id FROM ReviewFinding")}
    assert remaining == {"rf::good"}


def test_dry_run_then_apply_deletes(store):
    _finding(store, "rf::open", "open")
    _finding(store, "rf::resolved", "resolved")
    _session(store, "s::old", "2000-01-01T00:00:00+00:00")

    selection = select_prunable(
        store,
        resolved_findings_before="30d",
        sessions_before="30d",
    )

    # Dry run: selection computed but nothing deleted yet.
    assert store.node_count("ReviewFinding") == 2
    assert store.node_count("Session") == 1

    counts = apply_prune(store, selection)
    assert counts["resolved_findings"] == 1
    assert counts["sessions"] == 1

    assert store.node_count("ReviewFinding") == 1  # open finding survives
    assert store.node_count("Session") == 0


def test_apply_removes_session_edges(store):
    _session(store, "s::old", "2000-01-01T00:00:00+00:00")
    store.create_node(
        "File",
        {
            "id": "f1",
            "path": "a.py",
            "language": "python",
            "size": 1,
            "lastModified": "",
            "lineCount": 1,
            "contentHash": "",
        },
    )
    store.create_edge("SESSION_MODIFIED", "", "s::old", "", "f1")
    assert store.edge_count("SESSION_MODIFIED") == 1

    selection = select_prunable(store, sessions_before="1d")
    apply_prune(store, selection)

    assert store.node_count("Session") == 0
    assert store.edge_count("SESSION_MODIFIED") == 0
