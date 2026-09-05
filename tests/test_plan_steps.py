"""Plan 265: PlanStep ingest and pairwise dependency cycles."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.governance import process_governance
from agentscaffold.mcp.plan_card import count_execution_checkboxes, next_unchecked_step
from agentscaffold.mcp.server import _tool_compare_plans
from agentscaffold.plan.steps import parse_execution_steps, parse_step_dependencies
from agentscaffold.review.queries import plan_dependency_cycle


def _store() -> DuckPGQBackend:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    return store


def _write_plan(root: Path, number: int, body: str) -> Path:
    plans = root / "docs" / "ai" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / f"{number}-fixture.md"
    path.write_text(body)
    return path


_SAMPLE = """# Plan

## Tests
- [ ] unit
- [ ] integration

## 8. Execution Steps
- [ ] Step 1: Write tests (parenthetical note)
- [x] Step 2: Implement parser
- [ ] Step 3: Ingest

```
- [ ] not a step
```

## Completion Checklist
- [ ] All done
"""


def test_count_and_next_match_plan_247_shape() -> None:
    unchecked, checked = count_execution_checkboxes(_SAMPLE)
    assert unchecked == 2
    assert checked == 1
    assert next_unchecked_step(_SAMPLE) == "Step 1: Write tests (parenthetical note)"


def test_no_execution_steps_section_yields_zero() -> None:
    text = "# Plan\n\n## Tests\n- [ ] unit\n"
    assert count_execution_checkboxes(text) == (0, 0)
    assert next_unchecked_step(text) is None
    assert parse_execution_steps(text) == []


def test_code_fence_checkbox_is_not_counted() -> None:
    steps = parse_execution_steps(_SAMPLE)
    assert [s["step_number"] for s in steps] == [1, 2, 3]
    assert not any("not a step" in s["text"] for s in steps)


def test_parse_step_dependencies_both_clauses() -> None:
    raw = "needs 262 steps 1-9; steps 10-13 need 270"
    clauses = parse_step_dependencies(raw)
    assert clauses == [
        {
            "dest_number": 262,
            "from_step": None,
            "from_step_end": None,
            "to_step": 1,
            "to_step_end": 9,
        },
        {
            "dest_number": 270,
            "from_step": 10,
            "from_step_end": 13,
            "to_step": None,
            "to_step_end": None,
        },
    ]
    assert parse_step_dependencies("") == []
    assert parse_step_dependencies("none") == []


def test_ingest_plan_steps_and_qualified_edges(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        270,
        "# Plan 270\n\n"
        "- Step dependencies: needs 262 steps 1-9\n\n"
        "## 8. Execution Steps\n"
        "- [ ] Step 1: Wire the bar\n"
        "- [x] Step 2: Paper session\n",
    )
    _write_plan(
        tmp_path,
        262,
        "# Plan 262\n\n"
        "- Step dependencies: steps 10-13 need 270\n\n"
        "## 8. Execution Steps\n"
        "- [x] Step 1: Prefix\n"
        "- [ ] Step 10: Observe\n"
        "- [ ] Step 11: Enforce\n"
        "- [ ] Step 12: Docs one\n"
        "- [ ] Step 13: Docs two\n",
    )
    store = _store()
    try:
        process_governance(store, tmp_path)
        steps = store.query(
            "SELECT planNumber, stepNumber, checked, ordinal FROM PlanStep "
            "ORDER BY planNumber, ordinal"
        )
        assert len(steps) == 7
        assert any(r["planNumber"] == 270 and r["stepNumber"] == 1 for r in steps)
        edges = store.query(
            "SELECT src, dst, fromStep, fromStepEnd, toStep, toStepEnd FROM DEPENDS_ON_STEPS"
        )
        assert len(edges) == 2
        by_src = {r["src"]: r for r in edges}
        assert by_src["plan::270"]["dst"] == "plan::262"
        assert int(by_src["plan::270"]["toStep"]) == 1
        assert int(by_src["plan::270"]["toStepEnd"]) == 9
        assert by_src["plan::262"]["dst"] == "plan::270"
        assert int(by_src["plan::262"]["fromStep"]) == 10
        assert int(by_src["plan::262"]["fromStepEnd"]) == 13
        has_step = store.query("SELECT src, dst FROM PLAN_HAS_STEP")
        assert len(has_step) == 7
    finally:
        store.close()


def test_missing_step_dependencies_key_writes_no_qualified_edge(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        261,
        "# Plan 261\n\n## 8. Execution Steps\n- [ ] Step 1: Base\n",
    )
    _write_plan(
        tmp_path,
        264,
        "# Plan 264\n\n- Dependencies: 261\n\n## 8. Execution Steps\n- [ ] Step 1: Work\n",
    )
    store = _store()
    try:
        process_governance(store, tmp_path)
        assert store.query("SELECT src FROM DEPENDS_ON_STEPS") == []
        assert store.query("SELECT id FROM PlanStep")
        assert store.query("SELECT src, dst FROM DEPENDS_ON_PLAN")[0]["dst"] == "plan::261"
    finally:
        store.close()


def test_reindex_is_idempotent(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        265,
        "# Plan 265\n\n## 8. Execution Steps\n- [ ] Step 1: One\n- [ ] Step 2: Two\n",
    )
    store = _store()
    try:
        process_governance(store, tmp_path)
        process_governance(store, tmp_path)
        assert len(store.query("SELECT id FROM PlanStep")) == 2
        assert len(store.query("SELECT src FROM PLAN_HAS_STEP")) == 2
    finally:
        store.close()


def _handshake_repo(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        270,
        "# Plan 270\n\n- Step dependencies: needs 262 steps 1-9\n\n"
        "## 8. Execution Steps\n- [ ] Step 1: Wire\n",
    )
    _write_plan(
        tmp_path,
        262,
        "# Plan 262\n\n- Step dependencies: steps 10-13 need 270\n\n"
        "## 8. Execution Steps\n- [ ] Step 10: Observe\n",
    )


def test_handshake_fixture_is_apparent(tmp_path: Path) -> None:
    _handshake_repo(tmp_path)
    store = _store()
    try:
        process_governance(store, tmp_path)
        cycle = plan_dependency_cycle(store, 270, 262)
        assert cycle["status"] == "apparent"
        assert any(r.get("to_steps") == [1, 9] for r in cycle["ranges"])
        assert any(r.get("from_steps") == [10, 13] for r in cycle["ranges"])
        payload = _tool_compare_plans(store, {"plan_a": 270, "plan_b": 262}, {})
        assert payload["dependency_cycle"]["status"] == "apparent"
    finally:
        store.close()


def test_unqualified_mutual_dependency_is_genuine(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        10,
        "# Plan 10\n\n- Dependencies: 11\n\n## 8. Execution Steps\n- [ ] Step 1: A\n",
    )
    _write_plan(
        tmp_path,
        11,
        "# Plan 11\n\n- Dependencies: 10\n\n## 8. Execution Steps\n- [ ] Step 1: B\n",
    )
    store = _store()
    try:
        process_governance(store, tmp_path)
        cycle = plan_dependency_cycle(store, 10, 11)
        assert cycle["status"] == "genuine"
    finally:
        store.close()


def test_overlapping_ranges_are_genuine(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        20,
        "# Plan 20\n\n- Step dependencies: needs 21 steps 1-9\n\n"
        "## 8. Execution Steps\n- [ ] Step 1: A\n",
    )
    _write_plan(
        tmp_path,
        21,
        "# Plan 21\n\n- Step dependencies: steps 5-12 need 20\n\n"
        "## 8. Execution Steps\n- [ ] Step 5: B\n",
    )
    store = _store()
    try:
        process_governance(store, tmp_path)
        assert plan_dependency_cycle(store, 20, 21)["status"] == "genuine"
    finally:
        store.close()


def test_one_way_dependency_is_none(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        30,
        "# Plan 30\n\n- Dependencies: 31\n\n## 8. Execution Steps\n- [ ] Step 1: A\n",
    )
    _write_plan(
        tmp_path,
        31,
        "# Plan 31\n\n## 8. Execution Steps\n- [ ] Step 1: B\n",
    )
    store = _store()
    try:
        process_governance(store, tmp_path)
        assert plan_dependency_cycle(store, 30, 31)["status"] == "none"
        payload = _tool_compare_plans(store, {"plan_a": 30, "plan_b": 31}, {})
        assert payload["dependency_cycle"]["status"] == "none"
    finally:
        store.close()
