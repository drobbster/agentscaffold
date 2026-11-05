"""Parsing a plan's component fields and Component Lifecycle Changes table."""

from __future__ import annotations

from agentscaffold.inventory.plan_table import (
    LifecycleRow,
    has_components_line,
    lifecycle_rows,
    plan_components,
)

PLAN = """# Plan 900: Example

## Metadata
- Components: `prefect:nightly-sync`, compose:db, prefect:nightly-sync

## 3. File Impact Map

### 3.1 Component Lifecycle Changes
<!-- One row per component whose lifecycle this plan changes. -->

| Component | Before | After | Action |
|---|---|---|---|
| none | | | |
| `prefect:nightly-sync` | Active | Deprecated | Stop the schedule |
| compose:db | new | active | Add the service |

Text after the table.

| Unrelated | Table |
|---|---|
| x | y |

## 4. Tests
| Component | Before | After | Action |
|---|---|---|---|
| prefect:other | active | removed | not in the section |
"""


def test_rows_are_read_until_the_table_ends() -> None:
    assert lifecycle_rows(PLAN) == [
        LifecycleRow("prefect:nightly-sync", "active", "deprecated", "Stop the schedule"),
        LifecycleRow("compose:db", "new", "active", "Add the service"),
    ]


def test_a_plan_without_the_section_has_no_table() -> None:
    assert lifecycle_rows("# Plan\n\n## Metadata\n- Components: none\n") is None


def test_a_section_without_a_table_has_no_table() -> None:
    text = "## Component Lifecycle Changes\n\nNothing yet.\n\n## Tests\n"
    assert lifecycle_rows(text) is None


def test_the_placeholder_row_alone_is_an_empty_table() -> None:
    text = (
        "### Component Lifecycle Changes\n"
        "| Component | Before | After | Action |\n"
        "|---|---|---|---|\n"
        "| none | | | |\n"
    )
    assert lifecycle_rows(text) == []


def test_components_are_deduplicated_in_order() -> None:
    assert plan_components(PLAN) == ["prefect:nightly-sync", "compose:db"]


def test_none_means_no_components() -> None:
    text = "- Components: none\n"
    assert plan_components(text) == []
    assert has_components_line(text)
    assert not has_components_line("- Status: Draft\n")
