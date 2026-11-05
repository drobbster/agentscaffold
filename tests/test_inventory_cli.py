"""``scaffold inventory init | refresh | check`` (Plan 282)."""

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
    assert "10 components" in result.output
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


def test_refresh_without_an_inventory_exits_two(runner: CliRunner, fresh: Path) -> None:
    result = runner.invoke(app, ["inventory", "refresh"])
    assert result.exit_code == 2
    assert "init" in result.output


def test_bad_today_exits_two(runner: CliRunner, project: Path) -> None:
    result = runner.invoke(app, ["inventory", "check", "--today", "soon"])
    assert result.exit_code == 2
