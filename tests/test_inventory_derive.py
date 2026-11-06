"""Derivation of owner plan, layer, roadmap stage and since (contract v2, Derivation)."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

from agentscaffold.config import load_config
from agentscaffold.inventory import derive
from agentscaffold.inventory.collectors import collect
from agentscaffold.inventory.derive import Commit, PlanRecord
from agentscaffold.inventory.schema import Component, parse_inventory

TODAY = dt.date(2026, 11, 5)


class _History:
    """A GitHistory stand-in with fixed commits per source."""

    def __init__(self, commits: dict[str, list[Commit]] | None = None) -> None:
        self._commits = commits or {}

    def commits(self, source: str) -> list[Commit]:
        return self._commits.get(source, [])


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _commit(repo: Path, message: str, date: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, f"--date={date}T12:00:00")


def _plan(
    number: int, *files: tuple[str, bool], complete: bool = False, **kw: object
) -> PlanRecord:
    return PlanRecord(
        label=f"{number:03d}",
        number=number,
        complete=complete,
        layers=kw.get("layers"),  # type: ignore[arg-type]
        roadmap_stage=kw.get("roadmap_stage"),  # type: ignore[arg-type]
        files=list(files),
    )


def _job(**kw: object) -> Component:
    base: dict[str, object] = {
        "id": "prefect:j",
        "kind": "scheduled_job",
        "name": "j",
        "source": "prefect.yaml",
        "entrypoint": "flows/j.py:j",
    }
    base.update(kw)
    return Component.model_validate(base)


# ---------------------------------------------------------------------------
# Plan metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- Architecture Layer(s): 2, 4", ["2", "4"]),
        ("- Architecture Layers: L3 (data) and Layer 5", ["3", "5"]),
        ("- Architecture Layer: 4 (Model), 5", ["4", "5"]),
        (
            "- Architecture Layer: Cross-Cutting (records, audit), "
            "with read-only capture at 2-Alpha",
            "cross-cutting",
        ),
        ("- Architecture Layer: 2 + cross-cutting", ["2"]),
        ("- Architecture Layer: TBD", None),
        ("- Owner: someone", None),
    ],
)
def test_plan_layers(line: str, expected: object) -> None:
    assert derive.plan_layers(f"# Plan\n\n{line}\n") == expected


def test_plan_layers_reads_continuation_lines() -> None:
    text = "- Architecture Layer: 2,\n  4\n- Status: Draft\n"
    assert derive.plan_layers(text) == ["2", "4"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- Roadmap Stage: **Stage 3** (promotion)", "3"),
        ("- Roadmap Stage: 2-Alpha, then 3", "2-Alpha"),
        ("- Roadmap Stage: TBD", None),
    ],
)
def test_plan_roadmap_stage(line: str, expected: str | None) -> None:
    assert derive.plan_roadmap_stage(f"{line}\n") == expected


def test_plan_index_reads_status_layers_and_file_impact(tmp_path: Path) -> None:
    (tmp_path / "042-ingest.md").write_text(
        "# Plan 042\n\n- Status: Complete\n- Architecture Layer: 2\n- Roadmap Stage: 1\n\n"
        "## File Impact Map\n\n| File | Change Type | Description |\n|---|---|---|\n"
        "| `./flows/j.py` | Create | new flow |\n| `prefect.yaml` | Modify | register |\n"
    )
    (tmp_path / "notes.md").write_text("not a plan\n")
    (record,) = derive.plan_index(tmp_path).values()
    assert (record.label, record.number, record.complete) == ("042", 42, True)
    assert (record.layers, record.roadmap_stage) == (["2"], "1")
    assert record.files == [("flows/j.py", True), ("prefect.yaml", False)]
    assert derive.plan_index(tmp_path / "missing") == {}


# ---------------------------------------------------------------------------
# Owner, layer and stage rules
# ---------------------------------------------------------------------------


def _entry(component: Component, plans: dict[int, PlanRecord], **kw: object):
    return derive.derive_entry(
        component,
        kw.get("annotations", {}),  # type: ignore[arg-type]
        plans,
        kw.get("history", _History()),  # type: ignore[arg-type]
        layer_paths=kw.get("layer_paths", {}),  # type: ignore[arg-type]
        kind_layers=kw.get("kind_layers", {}),  # type: ignore[arg-type]
    )


def test_owner_is_the_lowest_numbered_plan_that_creates_the_entrypoint() -> None:
    plans = {
        12: _plan(12, ("flows/j.py", False), complete=True),
        20: _plan(20, ("flows/j.py", True), layers=["4"], roadmap_stage="5"),
        31: _plan(31, ("flows/j.py", True)),
    }
    entry = _entry(_job(), plans)
    assert (entry.owner_plan, entry.owner_from) == ("020", "file_impact_map_create")
    assert entry.touched_by == ["012", "031"]
    assert (entry.layer, entry.layer_from) == ("4", "owner_plan")
    assert (entry.roadmap_stage, entry.roadmap_stage_from) == ("5", "owner_plan")


def test_without_a_creator_the_latest_complete_plan_owns() -> None:
    plans = {
        12: _plan(12, ("src/flows/j.py", False), complete=True),
        15: _plan(15, ("flows/j.py", False), complete=True),
        40: _plan(40, ("flows/j.py", False)),
    }
    entry = _entry(_job(), plans)
    assert (entry.owner_plan, entry.owner_from) == ("015", "file_impact_map")
    assert entry.touched_by == ["012", "040"]


def test_without_a_complete_plan_the_latest_listing_plan_owns() -> None:
    plans = {12: _plan(12, ("flows/j.py", False)), 40: _plan(40, ("flows/j.py", False))}
    assert _entry(_job(), plans).owner_plan == "040"


def test_commit_citations_are_the_last_owner_rule() -> None:
    history = _History(
        {
            "prefect.yaml": [
                Commit("a", "2026-01-01", "Plan 12: add j", added=["  - name: j"]),
                Commit("b", "2026-02-01", "plan #40 tweak j schedule", added=["    j cron"]),
                Commit("c", "2026-03-01", "Plan 77: unrelated", added=["  - name: other"]),
                Commit("d", "2026-04-01", "Plan 999: not a known plan", added=["  - name: j"]),
            ]
        }
    )
    plans = {12: _plan(12), 40: _plan(40), 77: _plan(77)}
    entry = _entry(_job(entrypoint=None), plans, history=history)
    assert (entry.owner_plan, entry.owner_from) == ("040", "commit")


def test_an_annotation_wins_over_every_rule() -> None:
    plans = {20: _plan(20, ("flows/j.py", True), layers=["4"], roadmap_stage="5")}
    entry = _entry(
        _job(), plans, annotations={"owner_plan": "77", "layer": "2", "roadmap_stage": "1"}
    )
    assert (entry.owner_plan, entry.owner_from) == ("77", "annotation")
    assert entry.touched_by == ["020"]
    assert (entry.layer, entry.layer_from) == ("2", "annotation")
    assert (entry.roadmap_stage, entry.roadmap_stage_from) == ("1", "annotation")


def test_layer_falls_back_to_layer_paths_then_kind_layers() -> None:
    by_path = _entry(_job(), {}, layer_paths={"2": ["flows/**"], "9": ["other/"]})
    assert (by_path.layer, by_path.layer_from) == ("2", "layer_paths")
    by_kind = _entry(_job(), {}, kind_layers={"scheduled_job": "3"})
    assert (by_kind.layer, by_kind.layer_from) == ("3", "kind_layers")
    nothing = _entry(_job(), {})
    assert (nothing.owner_plan, nothing.layer, nothing.roadmap_stage) == (None, None, None)


def test_a_multi_layer_owner_plan_gives_a_layer_list() -> None:
    plans = {20: _plan(20, ("flows/j.py", True), layers=["2", "4"])}
    assert _entry(_job(), plans).layer == ["2", "4"]


def test_a_workflow_is_owned_through_its_source_file() -> None:
    workflow = Component(
        id="github_workflows:ci", kind="workflow", name="ci", source=".github/workflows/ci.yml"
    )
    plans = {7: _plan(7, (".github/workflows/ci.yml", True))}
    assert _entry(workflow, plans).owner_plan == "007"


# ---------------------------------------------------------------------------
# Git: since and commit citations
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "prefect.yaml").write_text(
        "deployments:\n  - name: first\n    entrypoint: flows/a.py:a\n"
    )
    _commit(tmp_path, "Plan 3: add first", "2026-01-10")
    (tmp_path / "prefect.yaml").write_text(
        "deployments:\n  - name: first\n    entrypoint: flows/a.py:a\n"
        "  - name: second\n    entrypoint: flows/b.py:b\n"
    )
    _commit(tmp_path, "Plan 5: add second", "2026-03-20")
    (tmp_path / "prefect.yaml").write_text(
        "deployments:\n  - name: first # moved\n    entrypoint: flows/a2.py:a\n"
        "  - name: second\n    entrypoint: flows/b.py:b\n"
    )
    _commit(tmp_path, "Plan 9: move first", "2026-05-01")
    return tmp_path


def test_since_is_the_commit_that_added_the_defining_line(repo: Path) -> None:
    history = derive.GitHistory(repo)
    first = _job(id="prefect:first", name="first")
    second = _job(id="prefect:second", name="second")
    assert derive.since(history, first) == "2026-01-10"
    assert derive.since(history, second) == "2026-03-20"


def test_since_falls_back_to_the_first_commit_then_none(repo: Path) -> None:
    history = derive.GitHistory(repo)
    renamed = _job(id="prefect:gone", name="gone")
    assert derive.since(history, renamed) == "2026-01-10"
    assert derive.since(history, _job(source="missing.yaml")) is None


def test_cited_plans_most_recent_first(repo: Path) -> None:
    history = derive.GitHistory(repo)
    first = _job(id="prefect:first", name="first")
    assert derive.cited_plans(history, first, {3, 5, 9}) == [9, 3]
    assert derive.cited_plans(history, first, {3}) == [3]


def test_git_history_reads_each_source_once(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    real = subprocess.run

    def spy(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(derive.subprocess, "run", spy)
    history = derive.GitHistory(repo)
    history.commits("prefect.yaml")
    history.commits("prefect.yaml")
    assert len(calls) == 1


def test_no_git_means_no_history(tmp_path: Path) -> None:
    (tmp_path / "prefect.yaml").write_text("deployments: []\n")
    assert derive.GitHistory(tmp_path / "nowhere").commits("prefect.yaml") == []


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def test_derive_over_a_project(tmp_path: Path) -> None:
    (tmp_path / "scaffold.yaml").write_text(
        "inventory:\n  enabled: true\n  collectors:\n    - name: compose\n"
        "  kind_layers:\n    service: '5'\n"
    )
    (tmp_path / "compose.yaml").write_text(
        "services:\n"
        "  api:\n    image: x\n    command: python -m api\n"
        "  cache:\n    image: redis\n    labels: {agentscaffold.owner_plan: '7'}\n"
    )
    plans = tmp_path / "docs" / "ai" / "plans"
    plans.mkdir(parents=True)
    (plans / "007-cache.md").write_text("- Status: Complete\n- Architecture Layer: 3\n")
    (tmp_path / "docs/ai/roadmap.md").write_text(
        "| Stage | Gate met |\n|---|---|\n| 1 | Yes |\n| 2 | No |\n"
    )
    config = load_config(tmp_path / "scaffold.yaml")
    collected = collect(tmp_path, [("compose", [])])
    inventory = parse_inventory(
        "schema_version: 1\ncomponents:\n"
        "  - id: compose:api\n    kind: service\n    name: api\n    source: compose.yaml\n"
        "  - id: compose:cache\n    kind: service\n    name: cache\n    source: compose.yaml\n"
    )
    derived = derive.derive(tmp_path, config, inventory, collected, today=TODAY, history=_History())
    assert (derived.current_roadmap_stage, derived.current_roadmap_stage_from) == ("2", "roadmap")
    api, cache = derived.components["compose:api"], derived.components["compose:cache"]
    assert (api.owner_plan, api.layer, api.layer_from) == (None, "5", "kind_layers")
    assert (cache.owner_plan, cache.owner_from) == ("7", "annotation")
    assert (cache.layer, cache.layer_from) == ("3", "owner_plan")
    assert derived.generated_at == "2026-11-05"
