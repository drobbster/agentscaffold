"""System inventory contract v1: the conformance fixtures (Plan 282).

``tests/fixtures/system_inventory/expected.json`` lists the findings each check
must produce on the synthetic project beside it. A fixture change is a contract
change. Messages are implementation wording; ids, severities and components are
the contract.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest

from agentscaffold.config import load_config
from agentscaffold.inventory import checks, health
from agentscaffold.inventory.project import check_project, load_project_inventory
from agentscaffold.inventory.schema import Component, InventoryError, parse_inventory

FIXTURES = Path(__file__).parent / "fixtures" / "system_inventory"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
TODAY = dt.date.fromisoformat(EXPECTED["today"])


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / EXPECTED["project"], root)
    return root


def _keys(findings: list[dict]) -> list[tuple]:
    return sorted((f["id"], f["severity"], f["component"] or "") for f in findings)


def test_checks_produce_the_expected_findings(project: Path) -> None:
    report = check_project(project, load_config(project / "scaffold.yaml"), today=TODAY, files=[])
    data = report.to_dict()

    assert data["schema_version"] == 1
    assert data["mode"] == "warn"
    assert _keys(data["findings"]) == _keys(EXPECTED["findings"])
    assert data["summary"] == EXPECTED["summary"]
    assert report.exit_code == 0


def test_changed_files_mode_adds_inv_008(project: Path) -> None:
    report = check_project(
        project,
        load_config(project / "scaffold.yaml"),
        today=TODAY,
        changed_files=EXPECTED["changed_files"],
        files=[],
    )
    inv008 = [f.to_dict() for f in report.findings if f.id == "INV-008"]
    assert _keys(inv008) == _keys(EXPECTED["changed_file_findings"])


def test_inv_008_runs_only_in_changed_files_mode(project: Path) -> None:
    report = check_project(project, load_config(project / "scaffold.yaml"), today=TODAY, files=[])
    assert not [f for f in report.findings if f.id == "INV-008"]


def test_every_finding_matches_the_output_shape(project: Path) -> None:
    report = check_project(project, load_config(project / "scaffold.yaml"), today=TODAY, files=[])
    for finding in report.to_dict()["findings"]:
        assert set(finding) == {"id", "severity", "component", "message"}
        assert finding["severity"] == (
            "warning" if finding["id"] in checks.WARNING_CHECKS else "error"
        )
        assert finding["message"]


def test_fail_mode_exits_non_zero_on_errors(project: Path) -> None:
    config = load_config(project / "scaffold.yaml")
    config.inventory.enforcement = "fail"
    report = check_project(project, config, today=TODAY, files=[])
    assert report.mode == "fail"
    assert report.exit_code == 1


def test_warnings_alone_never_fail(project: Path) -> None:
    findings = [checks.Finding("INV-007", "warning", "compose:api", "x")]
    assert checks.exit_code(findings, "fail") == 0


def test_warn_until_turns_warn_into_fail() -> None:
    assert checks.effective_mode("warn", "2026-11-01", TODAY) == "fail"
    assert checks.effective_mode("warn", "2026-11-05", TODAY) == "warn"
    assert checks.effective_mode("warn", None, TODAY) == "warn"
    assert checks.effective_mode("fail", "2027-01-01", TODAY) == "fail"


def test_health_rules(project: Path) -> None:
    config = load_config(project / "scaffold.yaml")
    inventory = load_project_inventory(project, config)
    snapshot = health.read_snapshot(
        project / config.inventory.health_snapshot,
        today=TODAY,
        max_bytes=config.inventory.health_max_bytes,
        stale_days=7,
    )
    assert snapshot.status == "ok"
    failing = [r["component"] for r in health.failing(inventory, snapshot, days=14)]
    zombies = [r["component"] for r in health.zombies(inventory, snapshot, days=90)]
    assert failing == EXPECTED["health"]["failing"]
    assert zombies == EXPECTED["health"]["zombies"]


@pytest.mark.parametrize(
    "text",
    ["components: [\n", "- just a list\n", "schema_version: 2\ncomponents: []\n"],
)
def test_unreadable_inventories_raise(text: str) -> None:
    with pytest.raises(InventoryError):
        parse_inventory(text)


def test_dates_and_numbers_are_read_as_text() -> None:
    inventory = parse_inventory(
        "schema_version: 1\ncurrent_roadmap_stage: 3\nlast_architecture_review: 2026-10-28\n"
        "components:\n  - id: config:x\n    owner_plan: 080\n    since: 2026-01-02\n"
    )
    assert inventory.current_roadmap_stage == "3"
    assert inventory.last_review_date == dt.date(2026, 10, 28)
    entry = inventory.components[0]
    assert entry.since_date == dt.date(2026, 1, 2)
    assert entry.owner_plan is not None


@pytest.mark.parametrize(
    ("lifecycle", "extra", "missing"),
    [
        ("paused", {}, {"reason", "review_by", "exit_criteria"}),
        ("experimental", {"reason": "r", "review_by": "2027-01-01"}, {"exit_criteria"}),
        ("deprecated", {"reason": "r", "review_by": "2027-01-01"}, {"replaced_by"}),
        ("deprecated", {"reason": "r", "review_by": "2027-01-01", "replaced_by": None}, set()),
        ("shadow", {}, set()),
    ],
)
def test_required_fields_follow_the_lifecycle(
    lifecycle: str, extra: dict, missing: set[str]
) -> None:
    entry = Component(
        id="config:x",
        kind="config_family",
        name="x",
        layer="1",
        owner_plan="1",
        roadmap_stage="1",
        lifecycle=lifecycle,
        since="2026-01-01",
        **extra,
    )
    finding = checks.check_required(entry, set())
    if not missing:
        assert finding is None
    else:
        assert finding is not None
        for name in missing:
            assert name in finding.message


def test_collected_kinds_need_a_source() -> None:
    entry = Component(
        id="prefect:j",
        kind="scheduled_job",
        name="j",
        entrypoint="flows/j.py:j",
        layer="1",
        owner_plan="1",
        roadmap_stage="1",
        lifecycle="active",
        since="2026-01-01",
    )
    finding = checks.check_required(entry, {"scheduled_job"})
    assert finding is not None and "source" in finding.message
    assert checks.check_required(entry, set()) is None


def test_fixture_is_synthetic() -> None:
    """The fixtures copy shapes, not content: no machine-specific paths."""
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "/Users/" not in text
            assert "/home/" not in text
