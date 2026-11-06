"""``scaffold inventory init | refresh | check``."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app

FIXTURES = Path(__file__).parent / "fixtures" / "system_inventory"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
TODAY = ["--today", EXPECTED["today"]]


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "project", root)
    monkeypatch.chdir(root)
    return root


@pytest.fixture()
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "scaffold.yaml").write_text(
        "project:\n  name: fresh\ninventory:\n  enabled: true\n  collectors: [compose]\n",
        encoding="utf-8",
    )
    (root / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:16\n", encoding="utf-8"
    )
    monkeypatch.chdir(root)
    return root


def _json(output: str) -> dict:
    return json.loads(output[output.index("{") :])


def test_check_json_matches_the_contract_shape(runner: CliRunner, project: Path) -> None:
    result = runner.invoke(app, ["inventory", "check", "--format", "json", *TODAY])
    assert result.exit_code == 0, result.output
    data = _json(result.output)
    assert set(data) >= {"schema_version", "mode", "findings", "summary"}
    assert data["summary"]["errors"] == EXPECTED["summary"]["errors"]
    assert {f["id"] for f in data["findings"]} >= {"INV-001", "INV-010"}


def test_check_text_lists_findings_and_summary(runner: CliRunner, project: Path) -> None:
    result = runner.invoke(app, ["inventory", "check", *TODAY])
    assert result.exit_code == 0
    assert "INV-004" in result.output
    assert "INV-011" in result.output
    assert "12 components" in result.output
    assert "mode: warn" in result.output


def test_check_fail_mode_exits_one(runner: CliRunner, project: Path) -> None:
    config = yaml.safe_load((project / "scaffold.yaml").read_text())
    config["inventory"]["enforcement"] = "fail"
    (project / "scaffold.yaml").write_text(yaml.safe_dump(config))
    result = runner.invoke(app, ["inventory", "check", *TODAY])
    assert result.exit_code == 1


def test_check_warn_until_passed_exits_one(runner: CliRunner, project: Path) -> None:
    config = yaml.safe_load((project / "scaffold.yaml").read_text())
    config["inventory"]["warn_until"] = "2026-11-01"
    (project / "scaffold.yaml").write_text(yaml.safe_dump(config))
    result = runner.invoke(app, ["inventory", "check", "--format", "json", *TODAY])
    assert result.exit_code == 1
    assert _json(result.output)["mode"] == "fail"


def test_check_changed_files_from_a_file(runner: CliRunner, project: Path) -> None:
    changed = project / "changed.txt"
    changed.write_text("\n".join(EXPECTED["changed_files"]) + "\n")
    result = runner.invoke(
        app, ["inventory", "check", "--format", "json", "--changed-files", str(changed), *TODAY]
    )
    ids = [(f["id"], f["component"]) for f in _json(result.output)["findings"]]
    assert ("INV-008", "prefect:weekly-training") in ids
    assert ("INV-008", "prefect:retired-sync") in ids


def test_check_changed_files_from_stdin(runner: CliRunner, project: Path) -> None:
    result = runner.invoke(
        app,
        ["inventory", "check", "--format", "json", "--changed-files", "-", *TODAY],
        input="scripts/sync/run.py\n",
    )
    ids = [(f["id"], f["component"]) for f in _json(result.output)["findings"]]
    assert ("INV-008", "prefect:retired-sync") in ids


def test_check_malformed_inventory_exits_two(runner: CliRunner, project: Path) -> None:
    (project / "docs" / "ai" / "system_inventory.yaml").write_text("schema_version: 9\n")
    result = runner.invoke(app, ["inventory", "check", "--format", "json", *TODAY])
    assert result.exit_code == 2
    assert "error" in _json(result.output)


def test_check_disabled_without_a_file_is_a_no_op(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scaffold.yaml").write_text("project:\n  name: x\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["inventory", "check"])
    assert result.exit_code == 0
    assert "not enabled" in result.output


def test_check_rejects_an_unknown_format(runner: CliRunner, project: Path) -> None:
    result = runner.invoke(app, ["inventory", "check", "--format", "xml"])
    assert result.exit_code == 2


def test_init_writes_the_inventory_then_refuses_to_overwrite(
    runner: CliRunner, fresh: Path
) -> None:
    result = runner.invoke(app, ["inventory", "init", *TODAY])
    assert result.exit_code == 0, result.output
    text = (fresh / "docs" / "ai" / "system_inventory.yaml").read_text()
    assert "compose:db" in text
    again = runner.invoke(app, ["inventory", "init"])
    assert again.exit_code == 1
    assert "refresh" in again.output


def test_init_dry_run_writes_nothing(runner: CliRunner, fresh: Path) -> None:
    result = runner.invoke(app, ["inventory", "init", "--dry-run", *TODAY])
    assert result.exit_code == 0
    assert "compose:db" in result.output
    assert not (fresh / "docs" / "ai" / "system_inventory.yaml").exists()


def _domain_project(root: Path, inventory_block: str) -> None:
    (root / "scaffold.yaml").write_text(
        f"project:\n  name: fresh\ndomains:\n  - trading\n{inventory_block}", encoding="utf-8"
    )
    (root / "prefect.yaml").write_text(
        "deployments:\n  - name: nightly-sync\n    entrypoint: flows/sync.py:sync\n",
        encoding="utf-8",
    )


def test_init_without_a_collector_list_adds_the_domain_collectors(
    runner: CliRunner, fresh: Path
) -> None:
    _domain_project(fresh, "")
    result = runner.invoke(app, ["inventory", "init", "--dry-run", *TODAY])
    assert result.exit_code == 0, result.output
    assert "compose:db" in result.output
    assert "prefect:nightly-sync" in result.output


def test_an_explicit_collector_list_is_used_as_written(runner: CliRunner, fresh: Path) -> None:
    _domain_project(fresh, "inventory:\n  collectors: [compose]\n")
    result = runner.invoke(app, ["inventory", "init", "--dry-run", *TODAY])
    assert result.exit_code == 0, result.output
    assert "compose:db" in result.output
    assert "prefect:nightly-sync" not in result.output


def test_init_adds_the_manual_section_to_explicit_step_lists(
    runner: CliRunner, fresh: Path
) -> None:
    config = fresh / "scaffold.yaml"
    config.write_text(
        config.read_text() + "agents:\n  governance:\n    steps:\n      implementation:\n"
        "        - Execution Rules\n"
    )
    result = runner.invoke(app, ["inventory", "init", *TODAY])
    assert result.exit_code == 0
    steps = yaml.safe_load(config.read_text())["agents"]["governance"]["steps"]
    assert steps["implementation"] == ["Execution Rules", "Component Lifecycle"]


def test_refresh_adds_new_components(runner: CliRunner, fresh: Path) -> None:
    runner.invoke(app, ["inventory", "init", *TODAY])
    (fresh / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:16\n  cache:\n    image: redis:7\n"
    )
    dry = runner.invoke(app, ["inventory", "refresh", "--dry-run", *TODAY])
    assert dry.exit_code == 0
    assert "added compose:cache" in dry.output
    path = fresh / "docs" / "ai" / "system_inventory.yaml"
    assert "compose:cache" not in path.read_text()

    result = runner.invoke(app, ["inventory", "refresh", *TODAY])
    assert result.exit_code == 0
    assert "compose:cache" in path.read_text()
    assert "up to date" in runner.invoke(app, ["inventory", "refresh"]).output


DERIVED = Path("docs") / "ai" / "system_inventory.derived.yaml"
LABELLED = (
    "services:\n  db:\n    image: postgres:16\n    labels:\n"
    "      agentscaffold.owner_plan: '12'\n      agentscaffold.layer: '2'\n"
)


def test_init_writes_the_derived_file_and_reports_coverage(runner: CliRunner, fresh: Path) -> None:
    (fresh / "compose.yaml").write_text(LABELLED)
    result = runner.invoke(app, ["inventory", "init", *TODAY])
    assert result.exit_code == 0, result.output
    assert "owner_plan: 1/1 derived (annotation 1)" in result.output
    derived = yaml.safe_load((fresh / DERIVED).read_text())
    assert derived["components"]["compose:db"]["owner_plan"] == "12"
    inventory = (fresh / "docs" / "ai" / "system_inventory.yaml").read_text()
    assert "owner_plan" not in inventory

    check = runner.invoke(app, ["inventory", "check", "--format", "json", *TODAY])
    data = _json(check.output)
    assert not [f for f in data["findings"] if f["id"] in ("INV-003", "INV-011")]
    assert not [n for n in data.get("notices", []) if n["kind"] == "derived_file"]


def test_init_dry_run_writes_no_derived_file(runner: CliRunner, fresh: Path) -> None:
    result = runner.invoke(app, ["inventory", "init", "--dry-run", *TODAY])
    assert result.exit_code == 0
    assert "Would write docs/ai/system_inventory.derived.yaml" in result.output
    assert not (fresh / DERIVED).exists()


def test_refresh_rederives_and_leaves_an_unchanged_derived_file_alone(
    runner: CliRunner, fresh: Path
) -> None:
    runner.invoke(app, ["inventory", "init", *TODAY])
    assert "owner_plan" not in (fresh / DERIVED).read_text()
    (fresh / "compose.yaml").write_text(LABELLED)
    result = runner.invoke(app, ["inventory", "refresh", "--today", "2026-11-06"])
    assert result.exit_code == 0, result.output
    text = (fresh / DERIVED).read_text()
    assert "owner_plan: '12'" in text and "2026-11-06" in text
    again = runner.invoke(app, ["inventory", "refresh", "--today", "2026-11-07"])
    assert "is up to date" in again.output
    assert (fresh / DERIVED).read_text() == text


def test_refresh_pin_derived_copies_values_into_the_inventory(
    runner: CliRunner, fresh: Path
) -> None:
    (fresh / "compose.yaml").write_text(LABELLED)
    runner.invoke(app, ["inventory", "init", *TODAY])
    result = runner.invoke(app, ["inventory", "refresh", "--pin-derived", *TODAY])
    assert result.exit_code == 0, result.output
    assert "Pinned 2 derived values" in result.output
    entry = yaml.safe_load((fresh / "docs" / "ai" / "system_inventory.yaml").read_text())
    (db,) = entry["components"]
    assert (db["owner_plan"], db["layer"]) == ("12", "2")


def test_init_dates_since_from_git(runner: CliRunner, fresh: Path) -> None:
    import subprocess

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(fresh), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("add", "compose.yaml")
    git("commit", "-q", "-m", "add db", "--date=2026-02-03T10:00:00")
    runner.invoke(app, ["inventory", "init", *TODAY])
    data = yaml.safe_load((fresh / "docs" / "ai" / "system_inventory.yaml").read_text())
    assert data["components"][0]["since"] == "2026-02-03"


def test_a_v1_inventory_upgrades_with_no_config_change(runner: CliRunner, fresh: Path) -> None:
    """Fully pinned, no derived file, no new scaffold.yaml keys: checks stay clean."""
    path = fresh / "docs" / "ai" / "system_inventory.yaml"
    path.parent.mkdir(parents=True)
    v1 = (
        "schema_version: 1\ncurrent_roadmap_stage: '2'\nlast_architecture_review: 2026-11-01\n"
        "review_cadence_days: 30\ncomponents:\n"
        "  - id: compose:db\n    kind: service\n    name: db\n    source: compose.yaml\n"
        "    entrypoint: postgres\n    layer: '1'\n    owner_plan: '5'\n"
        "    roadmap_stage: '1'\n    lifecycle: active\n    since: 2026-01-01\n"
    )
    path.write_text(v1)
    plans = fresh / "docs" / "ai" / "plans"
    plans.mkdir()
    (plans / "005-db.md").write_text("# Plan 5\n\n- Status: Complete\n")

    before = _json(runner.invoke(app, ["inventory", "check", "--format", "json", *TODAY]).output)
    assert before["findings"] == []
    assert [n["kind"] for n in before["notices"]] == ["derived_file"]

    assert runner.invoke(app, ["inventory", "refresh", *TODAY]).exit_code == 0
    (db,) = yaml.safe_load(path.read_text())["components"]
    assert (db["owner_plan"], db["layer"], db["roadmap_stage"]) == ("5", "1", "1")
    assert db["image"] == "postgres:16"
    after = _json(runner.invoke(app, ["inventory", "check", "--format", "json", *TODAY]).output)
    assert after["findings"] == []
    assert "notices" not in after


def test_refresh_without_an_inventory_exits_two(runner: CliRunner, fresh: Path) -> None:
    result = runner.invoke(app, ["inventory", "refresh"])
    assert result.exit_code == 2
    assert "init" in result.output


def test_bad_today_exits_two(runner: CliRunner, project: Path) -> None:
    result = runner.invoke(app, ["inventory", "check", "--today", "soon"])
    assert result.exit_code == 2
