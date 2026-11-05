"""Plan lint: Status vocabulary, adoption-date fields and component ids (Plan 282)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig, load_config
from agentscaffold.plan.lint import _lint_inventory_fields, _lint_plan

FIXTURE = Path(__file__).parent / "fixtures" / "system_inventory" / "project"


def _plan(meta: str, table: str = "") -> str:
    return f"# Plan 300: Work\n\n## 0. Metadata\n{meta}\n{table}\n## Execution Steps\n- [ ] One\n"


TABLE = (
    "## Component Lifecycle Changes\n| Component | Before | After | Action |\n|---|---|---|---|\n"
    "{rows}\n"
)


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, ScaffoldConfig]:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    return root, load_config(root / "scaffold.yaml")


def _issues(project: tuple[Path, ScaffoldConfig], text: str) -> list[str]:
    root, cfg = project
    return _lint_inventory_fields(text, cfg, root)


@pytest.mark.parametrize(
    "status",
    ["Draft", "Review (awaiting approval)", "COMPLETE (2026-07-09)", "in-progress", "Superseded"],
)
def test_qualified_status_lines_are_valid(project, status: str) -> None:
    assert _issues(project, _plan(f"- Status: {status}")) == []


@pytest.mark.parametrize("status", ["Unknown", "Blocked", "Paused until Q3"])
def test_statuses_outside_the_vocabulary_are_rejected(project, status: str) -> None:
    issues = _issues(project, _plan(f"- Status: {status}"))
    assert len(issues) == 1
    assert f"Status '{status}' is not one of" in issues[0]


def test_two_status_lines_are_flagged(project) -> None:
    issues = _issues(project, _plan("- Status: Draft\n| Status | Complete |"))
    assert issues == ["Plan has 2 Status lines; keep one"]


def test_upgrades_without_the_inventory_see_no_new_issues(tmp_path: Path) -> None:
    plan = tmp_path / "300-work.md"
    plan.write_text(_plan("- Status: Blocked\n- Components: not an id"))
    disabled = _lint_plan(plan, ScaffoldConfig(), tmp_path)
    assert disabled == _lint_plan(plan)
    assert not [i for i in disabled if "Status" in i or "Component" in i]


def test_fields_are_required_only_from_the_adoption_date(project) -> None:
    root, cfg = project
    cfg.inventory.plan_adoption_date = "2026-11-01"
    before = _plan("- Created: 2026-10-31")
    assert _lint_inventory_fields(before, cfg, root) == []

    after = _plan("- Created: 2026-11-01")
    assert _lint_inventory_fields(after, cfg, root) == [
        "Missing '- Status:' line (required from the inventory adoption date)",
        "Missing '- Roadmap Stage:' line (required from the adoption date)",
        "Missing '- Components:' line (required from the adoption date)",
        "Missing 'Component Lifecycle Changes' table (required from the adoption date)",
    ]

    complete = _plan(
        "- Created: 2026-11-02\n- Status: Draft\n- Roadmap Stage: 3\n- Components: none",
        TABLE.format(rows="| none | | | |"),
    )
    assert _lint_inventory_fields(complete, cfg, root) == []


def test_component_ids_are_checked(project) -> None:
    text = _plan(
        "- Status: Draft\n- Components: prefect:weekly-training, Weekly Training, prefect:ghost",
        TABLE.format(
            rows="| prefect:brand-new | new | experimental | Add it |\n"
            "| prefect:retired-sync | deprecated | removed | Delete it |"
        ),
    )
    assert _issues(project, text) == [
        "Component id 'Weekly Training' is not <kind-prefix>:<name>",
        "Component 'prefect:ghost' is not in docs/ai/system_inventory.yaml (a new one needs "
        "a Component Lifecycle Changes row with Before 'new')",
    ]


def test_closed_plans_skip_the_existence_check(project) -> None:
    text = _plan(
        "- Status: Complete\n- Components: prefect:removed-long-ago",
    )
    assert _issues(project, text) == []


def test_a_plan_from_the_template_passes_the_new_checks(project) -> None:
    from agentscaffold.rendering import get_default_context, render_template

    root, cfg = project
    cfg.inventory.plan_adoption_date = "2020-01-01"
    for template in (
        "core/plan_template.md.j2",
        "core/plan_template_bugfix.md.j2",
        "core/plan_template_refactor.md.j2",
    ):
        ctx = get_default_context(cfg)
        ctx.update(plan_number=300, plan_title="Work")
        text = render_template(template, ctx)
        assert "- Status: Draft" in text
        assert "### Component Lifecycle Changes" in text
        assert _lint_inventory_fields(text, cfg, root) == [], template
