"""``scaffold inventory enable``: one command, every asset, idempotent."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import yaml
from rich.console import Console
from typer.testing import CliRunner

from agentscaffold.cli import app
from agentscaffold.inventory import enable
from agentscaffold.inventory.enable import edit_scaffold_yaml
from agentscaffold.inventory.roadmap import current_stage
from agentscaffold.rendering import render_template

TODAY = dt.date(2026, 11, 5)
DAY = ["--today", TODAY.isoformat()]
DEFAULTS = ["compose", "github_workflows", "pyproject_scripts"]


# ---------------------------------------------------------------------------
# scaffold.yaml edit
# ---------------------------------------------------------------------------


def test_adds_the_block_when_absent_and_keeps_comments() -> None:
    text = "# my project\nproject:\n  name: demo  # keep\n"
    edit = edit_scaffold_yaml(text, today=TODAY, roadmap="docs/ai/strategy_roadmap.md")
    assert edit.text.startswith(text.rstrip("\n"))
    assert "name: demo  # keep" in edit.text
    assert yaml.safe_load(edit.text)["inventory"] == {
        "enabled": True,
        "enforcement": "warn",
        "review_overdue": "error",
        "plan_adoption_date": "2026-11-05",
        "roadmap": {"path": "docs/ai/strategy_roadmap.md"},
    }
    assert "inventory.enabled: true" in edit.changes


def test_flips_enabled_and_keeps_the_projects_choices() -> None:
    text = (
        "project:\n  name: demo\n"
        "inventory:\n  enabled: false  # pilot\n  enforcement: fail\n  path: inv.yaml\n"
        "other: 1\n"
    )
    edit = edit_scaffold_yaml(text, today=TODAY)
    data = yaml.safe_load(edit.text)
    assert data["inventory"] == {
        "enabled": True,
        "enforcement": "fail",
        "path": "inv.yaml",
        "review_overdue": "error",
        "plan_adoption_date": "2026-11-05",
    }
    assert data["other"] == 1
    assert edit.changes == [
        "inventory.enabled: true",
        "inventory.review_overdue",
        "inventory.plan_adoption_date",
    ]


def test_adds_enabled_to_a_block_without_it() -> None:
    text = "inventory:\n    path: inv.yaml\n"
    data = yaml.safe_load(edit_scaffold_yaml(text, today=TODAY).text)
    assert data["inventory"]["enabled"] is True
    assert data["inventory"]["path"] == "inv.yaml"


def test_a_null_block_is_filled() -> None:
    data = yaml.safe_load(edit_scaffold_yaml("inventory:\n", today=TODAY).text)
    assert data["inventory"]["enabled"] is True


def test_an_enabled_block_is_unchanged() -> None:
    text = (
        "inventory:\n  enabled: true\n  enforcement: warn\n  review_overdue: warn\n"
        '  plan_adoption_date: "2026-01-01"\n'
    )
    edit = edit_scaffold_yaml(text, today=TODAY, roadmap="ROADMAP.md")
    assert edit.changes == ["inventory.roadmap"]
    assert edit_scaffold_yaml(edit.text, today=TODAY, roadmap="ROADMAP.md").changes == []
    assert yaml.safe_load(edit.text)["inventory"]["review_overdue"] == "warn"


def test_detected_collectors_join_an_implicit_default_list() -> None:
    edit = edit_scaffold_yaml(
        "project:\n  name: demo\n", today=TODAY, collectors=DEFAULTS, extra_collectors=["prefect"]
    )
    assert yaml.safe_load(edit.text)["inventory"]["collectors"] == [*DEFAULTS, "prefect"]


def test_detected_collectors_append_to_an_explicit_list() -> None:
    text = "inventory:\n  enabled: true\n  collectors:\n    - compose\n    - name: custom\n"
    edit = edit_scaffold_yaml(text, today=TODAY, extra_collectors=["prefect"])
    collectors = yaml.safe_load(edit.text)["inventory"]["collectors"]
    assert collectors == ["compose", {"name": "custom"}, "prefect"]
    assert "inventory.collectors + prefect" in edit.changes


def test_a_flow_style_block_returns_a_snippet() -> None:
    text = "inventory: {enabled: false}\n"
    edit = edit_scaffold_yaml(text, today=TODAY)
    assert edit.text == text
    assert yaml.safe_load(edit.snippet)["inventory"]["enabled"] is True


# ---------------------------------------------------------------------------
# run_enable, end to end
# ---------------------------------------------------------------------------

ROADMAP = """\
# Roadmap

| Stage | Goal | Gate met |
|---|---|---|
| 1 | Build | Yes, 2026-01-01 |
| 2 | Run | No |
"""

MANUAL = """\
# Agent Operating Rules

## Planning Rules
Plan first.

## Runbook Rules
Keep it current.
"""


@pytest.fixture()
def upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An existing project with no inventory config and nested sources (L282-1)."""
    root = tmp_path / "proj"
    (root / "deploy").mkdir(parents=True)
    (root / "ops" / "flows").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "docs" / "ai").mkdir(parents=True)
    (root / "scaffold.yaml").write_text("project:\n  name: upgrade\n")
    (root / "deploy" / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:16\n  api:\n    command: python -m api\n"
    )
    (root / "ops" / "flows" / "prefect.yaml").write_text(
        "deployments:\n  - name: nightly\n    entrypoint: flows/nightly.py:run\n"
        "    schedules:\n      - cron: '0 1 * * *'\n"
    )
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\non: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps: []\n"
    )
    (root / "docs" / "ai" / "strategy_roadmap.md").write_text(ROADMAP)
    (root / "AGENTS.md").write_text(MANUAL)
    monkeypatch.chdir(root)
    return root


def _snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_enable_delivers_every_asset(upgrade: Path) -> None:
    result = CliRunner().invoke(app, ["inventory", "enable", *DAY])
    assert result.exit_code == 0, result.output

    inv = yaml.safe_load((upgrade / "scaffold.yaml").read_text())["inventory"]
    assert inv["enabled"] is True
    assert inv["review_overdue"] == "error"
    assert inv["roadmap"] == {"path": "docs/ai/strategy_roadmap.md"}
    assert inv["collectors"] == [*DEFAULTS, "prefect"]

    data = yaml.safe_load((upgrade / "docs/ai/system_inventory.yaml").read_text())
    ids = {c["id"] for c in data["components"]}
    assert ids == {
        "compose:db",
        "compose:api",
        "prefect:nightly",
        "github_workflows:ci",
        "github_workflows:inventory-review",
    }
    derived = yaml.safe_load((upgrade / "docs/ai/system_inventory.derived.yaml").read_text())
    assert derived["current_roadmap_stage"] == "2"

    assert (upgrade / "docs/ai/prompts/architecture_review.md").is_file()
    manual = (upgrade / "AGENTS.md").read_text()
    assert manual.index("## Component Lifecycle") < manual.index("## Runbook Rules")
    assert "Plan first." in manual
    assert (upgrade / ".github/workflows/inventory-review.yml").is_file()

    out = " ".join(result.output.split())
    assert "Inventory: 5 components" in out, out
    assert "current roadmap stage: 2 (from roadmap)" in out
    assert "scaffold inventory review" in out


def test_compose_services_have_no_entrypoint_error(upgrade: Path) -> None:
    CliRunner().invoke(app, ["inventory", "enable", *DAY])
    check = CliRunner().invoke(app, ["inventory", "check", "--format", "json", *DAY])
    findings = json.loads(check.output)["findings"]
    assert not [f for f in findings if f["id"] == "INV-003"]


def test_a_second_run_changes_nothing(upgrade: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["inventory", "enable", *DAY]).exit_code == 0
    before = _snapshot(upgrade)
    second = runner.invoke(app, ["inventory", "enable", *DAY])
    assert second.exit_code == 0, second.output
    assert _snapshot(upgrade) == before
    assert "Set inventory" not in second.output


def test_dry_run_writes_nothing(upgrade: Path) -> None:
    before = _snapshot(upgrade)
    result = CliRunner().invoke(app, ["inventory", "enable", "--dry-run", *DAY])
    assert result.exit_code == 0, result.output
    assert _snapshot(upgrade) == before
    out = " ".join(result.output.split())
    assert "Would set inventory.enabled: true" in out
    assert "Would install docs/ai/prompts/architecture_review.md" in out
    assert "Would add 'Component Lifecycle' to AGENTS.md" in out
    assert "Would write .github/workflows/inventory-review.yml" in out


def test_existing_assets_are_never_overwritten(upgrade: Path) -> None:
    (upgrade / "docs/ai/prompts").mkdir(parents=True)
    prompt = upgrade / "docs/ai/prompts/architecture_review.md"
    prompt.write_text("# ours\n")
    workflow = upgrade / ".github/workflows/inventory-review.yml"
    workflow.write_text("# ours\n")
    assert CliRunner().invoke(app, ["inventory", "enable", *DAY]).exit_code == 0
    assert prompt.read_text() == "# ours\n"
    assert workflow.read_text() == "# ours\n"


def test_no_workflow_without_a_workflows_directory(upgrade: Path) -> None:
    for path in (upgrade / ".github/workflows").iterdir():
        path.unlink()
    (upgrade / ".github/workflows").rmdir()
    assert CliRunner().invoke(app, ["inventory", "enable", *DAY]).exit_code == 0
    assert not (upgrade / ".github/workflows").exists()


def test_an_uneditable_config_stops_with_a_snippet(upgrade: Path) -> None:
    (upgrade / "scaffold.yaml").write_text("project:\n  name: x\ninventory: {enabled: false}\n")
    result = CliRunner().invoke(app, ["inventory", "enable", *DAY])
    assert result.exit_code == 1
    assert "by hand" in result.output
    assert not (upgrade / "docs/ai/system_inventory.yaml").exists()


def test_without_scaffold_yaml_exits_two(tmp_path: Path) -> None:
    code = enable.run_enable(tmp_path, dry_run=False, today=TODAY, console=Console())
    assert code == 2


def test_reingest_reports_a_graph_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import agentscaffold.graph as graph

    def busy(*_a: object, **_k: object) -> None:
        raise RuntimeError("graph is locked")

    monkeypatch.setattr(graph, "graph_available", lambda *_a, **_k: True)
    monkeypatch.setattr(graph, "open_graph", busy)
    console = Console(record=True, width=200)
    enable.reingest_components(tmp_path, object(), console=console)
    assert "Graph not updated (graph is locked); run `scaffold index`." in console.export_text()


def test_the_roadmap_template_has_a_stage_table() -> None:
    text = render_template("project/strategy_roadmap.md.j2", {"project_name": "demo"})
    assert current_stage(text) == "1"
