"""Plan 281 Phase B: precedent retrieval for the files a plan touches.

``precedent_for`` returns earlier findings, learnings and ADRs relevant to a
set of paths, ranked by how they matched: graph links, then the ``paths``
column (or, for rows recorded before it existed, the text), then earlier
plans that changed the same files, then ADRs governing those plans.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.review.precedent import (
    MATCH_ORDER,
    PrecedentSource,
    open_precedent_sources,
    precedent_for,
)

pytest.importorskip("duckdb", reason="duckdb not installed")

CORE = "src/app/core.py"
PLAN = 300


@pytest.fixture()
def graph():
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    _seed(store)
    yield store
    store.close()


def _finding(
    store: DuckPGQBackend,
    fid: str,
    plan: int,
    *,
    review_type: str = "devils_advocate",
    severity: str = "medium",
    category: str = "RISK",
    paths: list[str] | None = None,
    status: str = "open",
    text: str | None = None,
    linked: bool = False,
) -> None:
    store.create_node(
        "ReviewFinding",
        {
            "id": fid,
            "reviewType": review_type,
            "planNumber": plan,
            "severity": severity,
            "category": category,
            "finding": text or f"finding {fid}",
            "resolution": "",
            "status": status,
            "paths": json.dumps(paths or []),
        },
    )
    if linked:
        store.create_edge("FINDING_ABOUT_FILE", "ReviewFinding", fid, "File", f"file::{CORE}")


def _learning(store: DuckPGQBackend, lid: str, plan: int, paths: list[str]) -> None:
    store.create_node(
        "Learning",
        {
            "id": f"learning::{lid}",
            "learningId": lid,
            "planNumber": plan,
            "description": f"learning {lid}",
            "target": "",
            "status": "Pending",
            "paths": json.dumps(paths),
        },
    )


def _seed(store: DuckPGQBackend) -> None:
    store.create_node(
        "File",
        {
            "id": f"file::{CORE}",
            "path": CORE,
            "language": "python",
            "size": 1,
            "lastModified": "0",
            "lineCount": 1,
            "contentHash": "h",
        },
    )
    # linked
    _finding(store, "rf::linked250", 250, paths=[CORE], linked=True)
    _finding(store, "rf::linked255", 255, paths=[CORE], status="resolved", linked=True)
    # path
    _finding(store, "rf::path260", 260, review_type="expansion", severity="high", paths=[CORE])
    _finding(
        store, "rf::auto270", 270, review_type="pre_review", severity="critical",
        category="DEPENDENCY", paths=[CORE],
    )  # fmt: skip
    _finding(store, "rf::legacy240", 240, severity="low", text=f"`{CORE}:12` leaks a handle")
    _learning(store, "L230-1", 230, [CORE])
    # excluded: statistic category, and the plan's own finding
    _finding(
        store, "rf::stat265", 265, review_type="pre_review", category="HISTORY",
        paths=[CORE], linked=True,
    )  # fmt: skip
    _finding(store, "rf::own300", PLAN, paths=[CORE])
    # plan overlap: plan 200 changed CORE; its finding names another file
    store.create_node(
        "Plan",
        {
            "id": "plan::200",
            "number": 200,
            "title": "Earlier core change",
            "status": "Complete",
            "impactPaths": json.dumps([CORE, "docs/x.md"]),
        },
    )
    _finding(store, "rf::overlap200", 200, severity="high", paths=["docs/x.md"])
    _learning(store, "L200-1", 200, ["docs/x.md"])
    # adr governing plan 200
    store.create_node("ADR", {"id": "adr::7", "number": 7, "title": "Core boundaries"})
    store.create_edge("ADR_GOVERNS", "ADR", "adr::7", "Plan", "plan::200")


def _ids(result) -> list[str]:
    return [item.id for item in result.items]


def test_ranking_by_match_then_authorship_then_severity_then_plan(graph):
    result = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None)
    assert _ids(result) == [
        "rf::linked255",
        "rf::linked250",
        "rf::path260",
        "learning::L230-1",
        "rf::legacy240",
        "rf::auto270",
        "rf::overlap200",
        "learning::L200-1",
        "adr::7",
    ]
    assert [i.match for i in result.items] == [
        "linked", "linked", "path", "path", "path", "path", "plan_overlap", "plan_overlap", "adr",
    ]  # fmt: skip
    assert result.total == 9


def test_items_carry_the_path_and_plan_they_matched_through(graph):
    result = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None)
    by_id = {i.id: i for i in result.items}
    assert by_id["rf::legacy240"].path == CORE
    assert by_id["rf::overlap200"].path == CORE
    assert by_id["adr::7"].plan_number == 200
    assert by_id["adr::7"].kind == "adr"
    assert all(i.project == "here" for i in result.items)


def test_statistic_categories_and_the_plans_own_findings_are_excluded(graph):
    result = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None)
    assert "rf::stat265" not in _ids(result)
    assert "rf::own300" not in _ids(result)


def test_status_does_not_affect_ranking(graph):
    graph.execute("UPDATE ReviewFinding SET status = 'resolved' WHERE id = 'rf::linked250'")
    graph.execute("UPDATE ReviewFinding SET status = 'open' WHERE id = 'rf::linked255'")
    result = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=2)
    assert _ids(result) == ["rf::linked255", "rf::linked250"]


def test_budget_caps_items_but_not_total(graph):
    result = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=3)
    assert len(result.items) == 3
    assert result.total == 9


def test_a_finding_matched_two_ways_appears_once_at_its_best_match(graph):
    result = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None)
    assert _ids(result).count("rf::linked250") == 1


def test_match_kinds_restrict_what_is_returned(graph):
    result = precedent_for(
        [PrecedentSource("here", graph)],
        [CORE],
        plan_number=PLAN,
        budget=None,
        match_kinds=("linked", "path", "adr"),
    )
    assert "rf::overlap200" not in _ids(result)
    assert "learning::L200-1" not in _ids(result)
    assert "adr::7" in _ids(result)


def test_semantic_is_off_unless_asked(graph):
    assert "semantic" in MATCH_ORDER
    result = precedent_for(
        [PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None,
        query_text="core boundaries",
    )  # fmt: skip
    assert all(i.match != "semantic" for i in result.items)


def test_semantic_matches_rank_last_and_carry_a_score(graph, monkeypatch: pytest.MonkeyPatch):
    from agentscaffold.graph import search

    _finding(graph, "rf::similar210", 210, text="Boundaries of the core module leak.")
    hits = [
        search.SearchResult("rf::similar210", "", "", "ReviewFinding", 0.81234, "semantic"),
        search.SearchResult("rf::linked250", "", "", "ReviewFinding", 0.7, "semantic"),
    ]
    monkeypatch.setattr(search, "hybrid_search", lambda *_a, **_k: hits)

    off = precedent_for(
        [PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None,
        query_text="core boundaries",
    )  # fmt: skip
    assert "rf::similar210" not in _ids(off)

    on = precedent_for(
        [PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None,
        query_text="core boundaries", semantic=True,
    )  # fmt: skip
    last = on.items[-1]
    assert (last.id, last.match, last.score) == ("rf::similar210", "semantic", 0.8123)
    assert [i.match for i in on.items].count("semantic") == 1


def test_semantic_hits_rank_by_similarity_not_severity(graph, monkeypatch: pytest.MonkeyPatch):
    from agentscaffold.graph import search

    _finding(graph, "rf::close", 201, text="Core boundaries leak.", severity="low")
    _finding(graph, "rf::far", 230, text="Something about core.", severity="critical")
    hits = [
        search.SearchResult("rf::far", "", "", "ReviewFinding", 0.4, "semantic"),
        search.SearchResult("rf::close", "", "", "ReviewFinding", 0.9, "semantic"),
    ]
    monkeypatch.setattr(search, "hybrid_search", lambda *_a, **_k: hits)
    result = precedent_for(
        [PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None,
        query_text="core boundaries", semantic=True, match_kinds=("semantic",),
    )  # fmt: skip
    assert _ids(result) == ["rf::close", "rf::far"]


def test_rerank_is_passed_to_the_semantic_search(graph, monkeypatch: pytest.MonkeyPatch):
    from agentscaffold.graph import search

    calls: list[bool] = []

    def fake(*_a, **kwargs):
        calls.append(kwargs.get("rerank", False))
        return []

    monkeypatch.setattr(search, "hybrid_search", fake)
    for rerank in (False, True):
        precedent_for(
            [PrecedentSource("here", graph)], [CORE], plan_number=PLAN,
            query_text="core boundaries", semantic=True, rerank=rerank,
        )  # fmt: skip
    assert calls == [False, True]


def test_output_is_deterministic(graph):
    first = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None)
    second = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None)
    assert [i.to_dict() for i in first.items] == [i.to_dict() for i in second.items]


def test_item_text_is_one_line_and_bounded(graph):
    graph.execute(
        "UPDATE ReviewFinding SET finding = 'line one\nline two " + "x" * 400 + "'"
        " WHERE id = 'rf::linked250'"
    )
    result = precedent_for([PrecedentSource("here", graph)], [CORE], plan_number=PLAN, budget=None)
    text = next(i.text for i in result.items if i.id == "rf::linked250")
    assert "\n" not in text
    assert len(text) <= 240


def test_no_paths_means_no_precedent(graph):
    result = precedent_for([PrecedentSource("here", graph)], [], plan_number=PLAN)
    assert result.items == []


# ---------------------------------------------------------------------------
# Sources across registered projects
# ---------------------------------------------------------------------------


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _index(root: Path):
    from agentscaffold.config import find_config, load_config
    from agentscaffold.graph import open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    config = load_config(find_config(start=root))
    run_pipeline(root=root, config=config)
    return open_graph(config, start=root)


def test_precedent_is_read_from_a_named_source_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from agentscaffold.graph.findings import record_finding
    from agentscaffold.workspace_registry import register_workspace

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    gov, pkg = tmp_path / "gov", tmp_path / "pkg"
    (gov / "docs/ai/plans").mkdir(parents=True)
    _write(gov / "scaffold.yaml", "framework:\n  project_name: gov\n")
    _write(pkg / "scaffold.yaml", "framework:\n  project_name: pkg\n")
    _write(pkg / "src/pkg/foo.py", "def foo():\n    return 1\n")

    gov_store = _index(gov)
    record_finding(
        gov_store,
        plan_number=12,
        review_type="devils_advocate",
        category="RISK",
        finding="foo() returns a constant.",
        file_paths=["src/pkg/foo.py"],
    )
    gov_store.close()
    pkg_store = _index(pkg)
    register_workspace(gov, name="gov")
    register_workspace(pkg, name="pkg")

    config = ScaffoldConfig.model_validate({"precedent": {"sources": ["gov", "ghost"]}})
    try:
        with open_precedent_sources(pkg_store, root=pkg, config=config) as opened:
            names = [s.name for s in opened.sources]
            result = precedent_for(opened.sources, ["src/pkg/foo.py"], budget=None)
            unavailable = opened.unavailable
    finally:
        pkg_store.close()

    assert names == ["pkg", "gov"]
    assert [(i.project, i.match) for i in result.items] == [("gov", "path")]
    assert unavailable == [{"project": "ghost", "reason": "not_registered"}]


def test_precedent_sources_must_be_project_names():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ScaffoldConfig.model_validate({"precedent": {"sources": ["../gov"]}})
