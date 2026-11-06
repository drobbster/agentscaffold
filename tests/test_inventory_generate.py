"""``scaffold inventory init`` / ``refresh`` text generation.

Refresh edits text in place so comments survive; an edit it cannot verify is
not written and the caller gets a snippet instead.
"""

from __future__ import annotations

import datetime as dt

import yaml

from agentscaffold.inventory.collectors import Collected, CollectionResult
from agentscaffold.inventory.derived_file import Derived, DerivedEntry
from agentscaffold.inventory.generate import (
    add_manual_section,
    init_text,
    pin_derived_text,
    refresh_text,
    set_top_level,
)
from agentscaffold.inventory.schema import parse_inventory

TODAY = dt.date(2026, 11, 5)


def _collected(*components: Collected) -> CollectionResult:
    result = CollectionResult(collectors=["prefect"], kinds={"scheduled_job", "manual_job"})
    result.components.extend(components)
    return result


JOB = Collected("prefect:nightly", "scheduled_job", "nightly", "prefect.yaml", "flows/n.py:n")
PAUSED = Collected(
    "prefect:weekly", "scheduled_job", "weekly", "prefect.yaml", "flows/w.py:w", paused=True
)
NEW = Collected("prefect:report", "manual_job", "report", "prefect.yaml", "flows/r.py:r")

EXISTING = """\
# Our inventory. Keep this comment.
schema_version: 1
current_roadmap_stage: "3"
last_architecture_review: 2026-10-28
review_cadence_days: 30
components:
  # Nightly ingest, owned by plan 101.
  - id: prefect:nightly
    kind: scheduled_job
    name: nightly
    source: prefect.yaml
    entrypoint: flows/old.py:n   # moved in plan 120
    reads:
      - configs/ingest/
    layer: "2"
    owner_plan: "101"
    roadmap_stage: "2"
    lifecycle: active
    since: 2026-03-02
"""


def test_init_lists_every_collected_component() -> None:
    text = init_text(_collected(PAUSED, JOB), TODAY)
    inventory = parse_inventory(text)
    assert [c.id for c in inventory.components] == ["prefect:nightly", "prefect:weekly"]
    weekly = inventory.by_id()["prefect:weekly"]
    assert weekly.lifecycle == "paused"
    assert weekly.since == "2026-11-05"
    assert weekly.layer is None and weekly.owner_plan is None
    assert text.startswith("# System inventory")


def test_init_writes_no_derived_fields_and_uses_given_since_dates() -> None:
    cache = Collected("compose:cache", "service", "cache", "compose.yaml", None, image="redis:7")
    text = init_text(_collected(JOB, cache), TODAY, {"prefect:nightly": "2026-01-10"})
    for key in ("layer:", "owner_plan:", "roadmap_stage:", "current_roadmap_stage:"):
        assert key not in text
    by_id = parse_inventory(text).by_id()
    assert by_id["prefect:nightly"].since == "2026-01-10"
    assert by_id["compose:cache"].since == "2026-11-05"
    assert by_id["compose:cache"].image == "redis:7"
    assert "image" not in yaml.safe_load(text)["components"][1]


def test_pin_derived_copies_unpinned_values_only() -> None:
    derived = Derived(
        components={
            "prefect:nightly": DerivedEntry(owner_plan="999", layer="7", roadmap_stage="9"),
            "prefect:report": DerivedEntry(owner_plan="120", layer=["2", "4"], roadmap_stage="3"),
            "prefect:absent": DerivedEntry(owner_plan="1"),
        }
    )
    base = refresh_text(EXISTING, _collected(JOB, NEW), TODAY).text
    result = pin_derived_text(base, derived)
    assert result.in_place
    assert sorted((cid, key) for cid, key, _old, _new in result.updated) == [
        ("prefect:report", "layer"),
        ("prefect:report", "owner_plan"),
        ("prefect:report", "roadmap_stage"),
    ]
    by_id = parse_inventory(result.text).by_id()
    assert by_id["prefect:nightly"].owner_plan == "101"
    assert by_id["prefect:report"].owner_plan == "120"
    assert by_id["prefect:report"].layer == "2, 4"
    assert "# Our inventory. Keep this comment." in result.text


def test_pin_derived_with_nothing_to_pin_is_unchanged() -> None:
    result = pin_derived_text(EXISTING, Derived())
    assert result.text == EXISTING and not result.updated


def test_set_top_level_replaces_or_inserts_after_schema_version() -> None:
    replaced = set_top_level(EXISTING, "last_architecture_review", "2026-11-05")
    assert replaced is not None
    assert "last_architecture_review: '2026-11-05'" in replaced
    assert "# Our inventory. Keep this comment." in replaced
    inserted = set_top_level("schema_version: 1\ncomponents: []\n", "review_cadence_days", 14)
    assert inserted == "schema_version: 1\nreview_cadence_days: 14\ncomponents: []\n"


def test_set_top_level_refuses_a_block_value() -> None:
    text = "schema_version: 1\nlast_architecture_review:\n  nested: 1\ncomponents: []\n"
    assert set_top_level(text, "last_architecture_review", "2026-11-05") is None


def test_init_with_nothing_collected_is_valid() -> None:
    inventory = parse_inventory(init_text(_collected(), TODAY))
    assert inventory.components == []


def test_refresh_updates_collector_fields_and_keeps_comments() -> None:
    result = refresh_text(EXISTING, _collected(JOB), TODAY)
    assert result.in_place
    assert result.updated == [("prefect:nightly", "entrypoint", "flows/old.py:n", "flows/n.py:n")]
    assert "# Our inventory. Keep this comment." in result.text
    assert "# Nightly ingest, owned by plan 101." in result.text
    entry = parse_inventory(result.text).by_id()["prefect:nightly"]
    assert entry.entrypoint == "flows/n.py:n"
    assert entry.owner_plan == "101"
    assert entry.reads == ["configs/ingest/"]


def test_refresh_appends_new_components_inside_the_list() -> None:
    result = refresh_text(EXISTING + "# trailing note\n", _collected(JOB, NEW), TODAY)
    assert result.in_place
    assert result.added == ["prefect:report"]
    inventory = parse_inventory(result.text)
    assert [c.id for c in inventory.components] == ["prefect:nightly", "prefect:report"]
    assert inventory.by_id()["prefect:report"].lifecycle == "active"
    assert "# trailing note" in result.text


def test_refresh_never_touches_human_fields() -> None:
    before = parse_inventory(EXISTING).by_id()["prefect:nightly"]
    result = refresh_text(EXISTING, _collected(JOB, NEW), TODAY)
    after = parse_inventory(result.text).by_id()["prefect:nightly"]
    for field in ("reads", "layer", "owner_plan", "roadmap_stage", "lifecycle", "since"):
        assert getattr(after, field) == getattr(before, field)


def test_refresh_with_no_changes_returns_the_text_unchanged() -> None:
    current = Collected(
        "prefect:nightly", "scheduled_job", "nightly", "prefect.yaml", "flows/old.py:n"
    )
    result = refresh_text(EXISTING, _collected(current), TODAY)
    assert not result.changed
    assert result.text == EXISTING


def test_refresh_fills_an_empty_inline_list() -> None:
    text = init_text(_collected(), TODAY)
    result = refresh_text(text, _collected(JOB), TODAY)
    assert result.in_place
    assert [c.id for c in parse_inventory(result.text).components] == ["prefect:nightly"]


def test_refresh_falls_back_to_a_snippet_for_flow_style() -> None:
    text = (
        "schema_version: 1\n"
        "components: [{id: 'prefect:nightly', kind: scheduled_job, name: nightly,"
        " source: prefect.yaml, entrypoint: 'flows/old.py:n'}]\n"
    )
    result = refresh_text(text, _collected(JOB, NEW), TODAY)
    assert not result.in_place
    assert result.text == text
    assert "prefect:report" in result.snippet
    assert result.problem


def test_refresh_leaves_unrelated_entries_alone() -> None:
    text = EXISTING + (
        '  - id: config:limits\n    kind: config_family\n    name: limits\n    layer: "3"\n'
    )
    result = refresh_text(text, _collected(JOB), TODAY)
    assert result.in_place
    assert parse_inventory(result.text).by_id()["config:limits"].layer == "3"


SCAFFOLD_WITH_LISTS = """\
# project config
agents:
  governance:
    steps:
      implementation:
        - Execution Rules   # keep
        - Test Requirements
      completion:
        - Retrospective Requirements
    optional: []
"""


def test_manual_section_is_added_to_explicit_lists_only() -> None:
    edit = add_manual_section(SCAFFOLD_WITH_LISTS)
    assert not edit.needs_human
    assert edit.changed_lists == [
        "agents.governance.steps.implementation",
        "agents.governance.steps.completion",
        "agents.governance.optional",
    ]
    data = yaml.safe_load(edit.text)
    steps = data["agents"]["governance"]["steps"]
    assert steps["implementation"][-1] == "Component Lifecycle"
    assert steps["completion"][-1] == "Component Lifecycle"
    assert data["agents"]["governance"]["optional"] == ["Component Lifecycle"]
    assert "# keep" in edit.text
    assert "# project config" in edit.text


def test_manual_section_untouched_when_lists_use_defaults() -> None:
    text = "project:\n  name: x\n"
    edit = add_manual_section(text)
    assert edit.text == text
    assert edit.changed_lists == []
    assert not edit.needs_human


def test_manual_section_is_idempotent() -> None:
    once = add_manual_section(SCAFFOLD_WITH_LISTS).text
    twice = add_manual_section(once)
    assert twice.changed_lists == []
    assert twice.text == once


def test_manual_section_flow_list_needs_a_human() -> None:
    text = "agents:\n  governance:\n    steps:\n      implementation: [Execution Rules]\n"
    edit = add_manual_section(text)
    assert edit.text == text
    assert edit.needs_human
    assert "Component Lifecycle" in edit.snippet
