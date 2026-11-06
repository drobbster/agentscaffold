"""``scaffold inventory review``: the architecture review packet."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app
from agentscaffold.config import load_config
from agentscaffold.inventory import review
from agentscaffold.inventory.collectors import Collected, CollectionResult
from agentscaffold.inventory.schema import Component, Inventory

FIXTURES = Path(__file__).parent / "fixtures" / "system_inventory"
TODAY = dt.date(2026, 11, 5)
DAY = ["--today", TODAY.isoformat()]


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "project", root)
    return root


@pytest.fixture()
def clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with no debt once its review is recorded."""
    root = tmp_path / "clean"
    (root / "docs" / "ai" / "plans").mkdir(parents=True)
    (root / "scaffold.yaml").write_text(
        "project:\n  name: clean\ninventory:\n  enabled: true\n  collectors: [compose]\n"
    )
    (root / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:16\n    labels:\n"
        "      agentscaffold.owner_plan: '12'\n      agentscaffold.layer: '2'\n"
    )
    (root / "docs/ai/plans/012-db.md").write_text("# Plan 12\n\n- Status: Complete\n")
    monkeypatch.chdir(root)
    CliRunner().invoke(app, ["inventory", "init", *DAY])
    return root


def _packet(root: Path) -> dict:
    return review.build_packet(root, load_config(root / "scaffold.yaml"), today=TODAY)


def test_packet_sections_on_the_fixture(project: Path) -> None:
    packet = _packet(project)
    assert packet["components"] == 12
    assert packet["by_kind"]["service"] == 4
    assert packet["health"]["status"] == "ok"
    assert packet["review_due"] is True
    assert [u["component"] for u in packet["unresolved"]] == ["compose:sidecar"]
    assert packet["unresolved"][0]["missing"] == ["owner_plan", "layer"]
    assert "agentscaffold.owner_plan" in packet["unresolved"][0]["fix"]
    owner = packet["coverage"]["owner_plan"]
    assert (owner["resolved"], owner["total"], owner["pin"]) == (11, 12, 10)
    assert owner["file_impact_map_create"] == 1
    assert packet["check"]["errors"] == 9
    assert packet["has_debt"] is True
    assert all(u["confidence"] == "unconfirmed" for u in packet["unreferenced"])


def test_unreferenced_lists_missing_entrypoint_files_only(project: Path) -> None:
    before = {u["component"] for u in _packet(project)["unreferenced"]}
    assert "prefect:nightly-ingest" in before
    assert "prefect:retired-sync" not in before  # deprecated
    (project / "flows").mkdir()
    (project / "flows" / "ingest.py").write_text("def nightly_ingest(): ...\n")
    after = {u["component"] for u in _packet(project)["unreferenced"]}
    assert "prefect:nightly-ingest" not in after


def test_absent_health_is_not_evaluated(project: Path) -> None:
    (project / "outputs/governance/inventory_health.json").unlink()
    packet = _packet(project)
    assert packet["health"]["status"] == "not_evaluated"
    assert "Status: not evaluated." in review.render_markdown(packet)


def _job(cid: str, entrypoint: str, **kw: object) -> Collected:
    return Collected(cid, "scheduled_job", cid.split(":")[1], "prefect.yaml", entrypoint, **kw)  # type: ignore[arg-type]


def test_duplicate_candidates() -> None:
    a = _job("prefect:a", "flows/x.py:f", parameters={"mode": "full"})
    b = _job("prefect:b", "flows/x.py:f", parameters={"mode": "lite"})
    c = _job("prefect:c", "flows/y.py:f")
    d = _job("prefect:d", "flows/y.py:f")
    web1 = Collected("compose:web1", "service", "web1", "compose.yaml", "gunicorn app", image="w:1")
    web2 = Collected("compose:web2", "service", "web2", "compose.yaml", "gunicorn app", image="w:1")
    collected = CollectionResult(components=[a, b, c, d, web1, web2])
    inventory = Inventory(
        components=[Component(id=x.id, kind=x.kind, name=x.name) for x in collected.components]
    )
    found = review.duplicates(inventory, collected)
    assert [d["components"] for d in found] == [
        ["prefect:a", "prefect:b"],
        ["compose:web1", "compose:web2"],
    ]


@pytest.mark.parametrize(
    ("cid", "source", "expected"),
    [
        ("compose:api", "deploy/compose.yaml", "labels {agentscaffold.owner_plan: <owner_plan>"),
        ("prefect:nightly", "prefect.yaml", "tags [plan:<n>]"),
        ("github_workflows:ci", ".github/workflows/ci.yml", "# agentscaffold: owner_plan="),
        ("config:limits", None, "pin owner_plan on config:limits in the inventory"),
    ],
)
def test_cheapest_fix_names_the_annotation_for_the_source(
    cid: str, source: str | None, expected: str
) -> None:
    entry = Component(id=cid, name=cid.split(":")[1], source=source)
    assert expected in review.cheapest_fix(entry, ["owner_plan"])


def test_markdown_has_every_section(project: Path) -> None:
    text = review.render_markdown(_packet(project))
    for heading in (
        "# System inventory review, 2026-11-05",
        "## Lifecycle debt",
        "## Health",
        "## Unresolved owner or layer (INV-011)",
        "## Duplicate candidates (unconfirmed)",
        "## Unreferenced entrypoints (unconfirmed)",
        "## Derivation coverage",
        "## Check errors",
    ):
        assert heading in text


def test_cli_review_json_record_and_exit_code(clean: Path) -> None:
    runner = CliRunner()
    first = runner.invoke(app, ["inventory", "review", "--exit-code", *DAY])
    assert first.exit_code == 1, first.output
    assert "last_architecture_review is not recorded" in first.output

    recorded = runner.invoke(app, ["inventory", "review", "--record", *DAY])
    assert recorded.exit_code == 0
    data = yaml.safe_load((clean / "docs/ai/system_inventory.yaml").read_text())
    assert str(data["last_architecture_review"]) == "2026-11-05"

    after = runner.invoke(app, ["inventory", "review", "--exit-code", "--format", "json", *DAY])
    assert after.exit_code == 0, after.output
    packet = json.loads(after.output)
    assert packet["has_debt"] is False
    assert packet["unresolved"] == []
    assert packet["health"]["status"] == "not_evaluated"


def test_cli_review_without_an_inventory_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scaffold.yaml").write_text("project:\n  name: x\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["inventory", "review"])
    assert result.exit_code == 2
    assert "enable" in result.output


def test_cli_review_rejects_an_unknown_format(clean: Path) -> None:
    assert CliRunner().invoke(app, ["inventory", "review", "--format", "xml"]).exit_code == 2
