"""Plan 281 precedent study harness: plan selection, pooled sheet, scoring."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentscaffold.review.precedent import PrecedentItem
from eval.precedent.run_precedent_eval import (
    ARMS,
    BLENDS,
    LABELS_FILE,
    RANKINGS_FILE,
    blend,
    decide,
    is_complete,
    open_slices,
    pool,
    require_current_schema,
    score,
    select_plans,
    write_scores,
    write_sheet,
)

pytest.importorskip("duckdb", reason="duckdb not installed")

ROUTER = "libs/data/router.py"


def _plan(number: int, status: str, files: list[str]) -> str:
    rows = "\n".join(f"| {f} | Modify | change |" for f in files)
    return (
        f"# Plan {number:03d}: Router change {number}\n\n## 0. Metadata\n- Plan: {number}\n"
        f"- Status: {status}\n\n## 6. File Impact Map\n| File | Change Type | Notes |\n"
        f"|------|-------------|-------|\n{rows}\n\n## 8. Execution Steps\n- [x] Step 1: Do it.\n"
    )


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.findings import record_finding
    from tests.fixtures.lone_project import build_lone_project

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    plans = {
        10: _plan(10, "Complete", [ROUTER]),
        20: _plan(20, "Complete", [ROUTER]),
        30: _plan(30, "Complete", [ROUTER]),
        35: _plan(35, "Draft", [ROUTER]),
        36: _plan(36, "Complete", []),
    }
    root = build_lone_project(
        tmp_path,
        extra_files={f"docs/ai/plans/plan_{n:03d}_router.md": body for n, body in plans.items()},
    )
    store = DuckPGQBackend(tmp_path / "lone.duckdb")
    try:
        for number in (10, 20, 40):
            record_finding(
                store,
                plan_number=number,
                review_type="devils_advocate",
                category="RISK",
                finding=f"Router risk from plan {number}.",
                file_paths=[ROUTER],
            )
    finally:
        store.close()
    return root


def test_selection_takes_completed_plans_that_list_files(repo: Path):
    with open_slices(["lone"]) as slices:
        store = slices[0].sources[0].store
        cases = select_plans(store, "lone", scope_project=None, count=20, holdout=1)
        again = select_plans(store, "lone", scope_project=None, count=20, holdout=1)
        two = select_plans(store, "lone", scope_project=None, count=2, holdout=1)
    numbers = [c.number for c in cases]
    assert numbers == sorted(numbers)
    assert {10, 20, 30} <= set(numbers)
    assert not {35, 36} & set(numbers)
    assert [c.split for c in cases].count("holdout") == 1
    assert [c.split for c in cases] == [c.split for c in again]
    assert next(c for c in cases if c.number == 10).paths == [ROUTER]
    assert [c.number for c in two] == numbers[-2:]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Complete", True),
        ("COMPLETE (2026-07-10)", True),
        ("**Complete** (approved 2026-07-30 by daverobb)", True),
        ("Complete -- released as 0.10.6 on 2026-08-13", True),
        ("done", True),
        ("Draft", False),
        ("In Progress", False),
        ("Incomplete", False),
        ("unknown", False),
        (None, False),
    ],
)
def test_free_text_statuses_count_as_complete(status, expected):
    assert is_complete(status) is expected


def test_sheet_pools_only_earlier_precedent(repo: Path, tmp_path: Path):
    out = tmp_path / "study"
    write_sheet(out, ["lone"], count=20, holdout=1)
    labels = yaml.safe_load((out / LABELS_FILE).read_text())
    plans = {p["plan"]: p for p in labels["slices"][0]["plans"]}

    def texts(number: int) -> set[str]:
        return {c["text"] for c in plans[number]["candidates"]}

    assert texts(10) == set()
    assert texts(20) == {"Router risk from plan 10."}
    assert texts(30) == {"Router risk from plan 10.", "Router risk from plan 20."}
    assert all(c["relevant"] is None for p in plans.values() for c in p["candidates"])
    assert set(labels["slices"][0]["plans"][0]) >= {"plan", "split", "title", "paths"}

    import json

    rankings = json.loads((out / RANKINGS_FILE).read_text())
    arms = rankings["slices"]["lone"]["30"]["arms"]
    assert set(arms) == {a.name for a in ARMS} | {name for name, _, _ in BLENDS}
    assert len(arms["semantic_only"]) <= 5


def test_sheet_never_overwrites_labels(repo: Path, tmp_path: Path):
    out = tmp_path / "study"
    write_sheet(out, ["lone"], count=20, holdout=1)
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        write_sheet(out, ["lone"], count=20, holdout=1)


def test_labelled_sheet_scores_end_to_end(repo: Path, tmp_path: Path):
    out = tmp_path / "study"
    write_sheet(out, ["lone"], count=20, holdout=3)
    labels = yaml.safe_load((out / LABELS_FILE).read_text())
    for plan in labels["slices"][0]["plans"]:
        for cand in plan["candidates"]:
            cand["relevant"] = "yes"
    (out / LABELS_FILE).write_text(yaml.safe_dump(labels, sort_keys=False))
    result = write_scores(out)
    lone = result["slices"]["lone"]
    assert lone["plans"] == 3
    assert lone["unjudged"] == 0
    assert lone["arms"]["links"]["recall_at_k"] == 1.0
    assert (out / "results.json").exists()


def test_unknown_project_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    with pytest.raises(SystemExit, match="cannot open project 'ghost'"):
        with open_slices(["ghost"]):
            pass


def test_a_graph_without_stored_paths_is_refused():
    class Stale:
        def query(self, sql: str):
            if "impactPaths" in sql:
                raise RuntimeError("Binder Error: column impactPaths not found")
            return []

    with pytest.raises(SystemExit, match="predates Plan 281"):
        require_current_schema(Stale(), "old")


def _item(project: str, node: str) -> PrecedentItem:
    return PrecedentItem(
        kind="finding", id=node, match="path", path="", plan_number=1, text=node, project=project
    )


def test_pool_deduplicates_and_hides_arm_order():
    a, b, c = _item("p", "a"), _item("p", "b"), _item("q", "a")
    first = pool({"links": [a, b], "paths": [b, c]})
    second = pool({"paths": [c, b], "links": [b, a]})
    assert [i.id for i in first] == [i.id for i in second]
    assert len(first) == 3


def _labels(plans: list[tuple[int, str, dict[str, str]]]) -> dict:
    return {
        "slices": [
            {
                "project": "s",
                "plans": [
                    {
                        "plan": number,
                        "split": split,
                        "candidates": [{"key": k, "relevant": v} for k, v in verdicts.items()],
                    }
                    for number, split, verdicts in plans
                ],
            }
        ]
    }


def test_score_is_recall_and_precision_at_five_on_the_holdout():
    labels = _labels(
        [
            (1, "holdout", {"x": "yes", "y": "yes", "z": "no", "w": ""}),
            (2, "holdout", {"x": "no"}),
            (3, "tuning", {"x": "yes"}),
        ]
    )
    rankings = {
        "k": 5,
        "arms": ["links", "semantic"],
        "slices": {
            "s": {
                "1": {"arms": {"links": ["x", "z"], "semantic": []}},
                "2": {"arms": {"links": ["x"], "semantic": ["x"]}},
                "3": {"arms": {"links": [], "semantic": ["x"]}},
            }
        },
    }
    result = score(labels, rankings)["slices"]["s"]
    assert result["plans"] == 2
    assert result["unjudged"] == 1
    links = result["arms"]["links"]
    assert links["recall_at_k"] == 0.5
    assert links["precision_at_k"] == 0.25
    assert (links["plans_with_relevant"], links["plans_with_results"]) == (1, 2)
    semantic = result["arms"]["semantic"]
    assert semantic["recall_at_k"] == 0.0
    assert semantic["precision_at_k"] == 0.0


def _slice(links: float, semantic: float, precision: float, arm: str = "semantic") -> dict:
    return {
        "arms": {
            "links": {"recall_at_k": links},
            "paths": {"recall_at_k": links},
            "overlap": {"recall_at_k": links},
            arm: {"recall_at_k": semantic, "precision_at_k": precision},
        }
    }


def test_semantic_defaults_on_only_when_it_helps_every_slice():
    both = decide({"a": _slice(0.4, 0.6, 0.6), "b": _slice(0.3, 0.5, 0.5)})
    assert both["semantic_default"] is True
    assert both["passes_everywhere"] == ["semantic"]
    assert both["rerank"] is False

    one = decide({"a": _slice(0.4, 0.6, 0.6), "b": _slice(0.3, 0.4, 0.9)})
    assert one["semantic_default"] is False
    assert one["passes_in_some_slices"] == {"semantic": ["a"]}

    imprecise = decide({"a": _slice(0.1, 0.9, 0.4)})
    assert imprecise["semantic_default"] is False


def test_a_blend_passing_everywhere_proposes_slots_not_a_default():
    result = decide(
        {"a": _slice(0.4, 0.6, 0.6, arm="blend"), "b": _slice(0.3, 0.5, 0.5, arm="blend")}
    )
    assert result["semantic_default"] is False
    assert result["propose_semantic_slots"] is True
    assert result["rerank"] is False

    rerank_only = decide({"a": _slice(0.1, 0.5, 0.9, arm="blend_rerank")})
    assert rerank_only["propose_semantic_slots"] is True
    assert rerank_only["rerank"] is True


def test_blend_reserves_semantic_slots_and_refills():
    structural = ["s1", "s2", "s3", "s4", "s5"]
    assert blend(structural, ["m1", "m2", "m3"]) == ["s1", "s2", "s3", "m1", "m2"]
    assert blend(structural, ["s1", "m1"]) == ["s1", "s2", "s3", "m1", "s4"]
    assert blend(structural, []) == structural
    assert blend(["s1"], ["m1", "m2", "m3"]) == ["s1", "m1", "m2"]
