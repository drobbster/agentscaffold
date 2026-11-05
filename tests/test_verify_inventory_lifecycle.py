"""The ``inventory_lifecycle`` verification row and COMPONENT disposition (Plan 282)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from agentscaffold.config import ComplianceConfig, load_config
from agentscaffold.review.changes import ChangeSet
from agentscaffold.review.verify import (
    COMPLIANCE_CHECKS,
    _check_disposition,
    _check_inventory_lifecycle,
    _Root,
)

FIXTURE = Path(__file__).parent / "fixtures" / "system_inventory" / "project"


def _table(*rows: tuple[str, str, str, str]) -> str:
    body = "\n".join(f"| {c} | {b} | {a} | {x} |" for c, b, a, x in rows)
    return (
        "# Plan 300: Work\n\n## Component Lifecycle Changes\n\n"
        "| Component | Before | After | Action |\n|---|---|---|---|\n"
        f"{body}\n\n## Execution Steps\n- [x] Step 1\n"
    )


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    return root


def _check(root: Path, text: str, files: list[str]) -> tuple[str, str, dict[str, Any]]:
    cfg = load_config(root / "scaffold.yaml")
    changes = ChangeSet(root=root, files=files, source="unmerged_branch", detail="")
    return _check_inventory_lifecycle(text, [_Root("project", root, cfg, changes)], cfg)


def test_the_row_is_registered_and_warns_by_default() -> None:
    assert "inventory_lifecycle" in COMPLIANCE_CHECKS
    assert ComplianceConfig().level("inventory_lifecycle") == "warn"


def test_skips_without_a_table_or_a_dormant_change(project: Path) -> None:
    status, detail, _ = _check(project, "# Plan 300\n", ["flows/ingest.py"])
    assert status == "skip"
    assert "No Component Lifecycle Changes table" in detail


def test_skips_when_the_inventory_is_disabled(project: Path) -> None:
    cfg = load_config(project / "scaffold.yaml")
    cfg.inventory.enabled = False
    changes = ChangeSet(root=project, files=["flows/weekly.py"], source="x", detail="")
    status, _, _ = _check_inventory_lifecycle("", [_Root("project", project, cfg, changes)], cfg)
    assert status == "skip"


def test_a_reflected_table_passes(project: Path) -> None:
    text = _table(
        ("prefect:weekly-training", "paused", "paused", "Kept paused"),
        ("prefect:retired-sync", "deprecated", "deprecated", "Still retiring"),
    )
    status, detail, _ = _check(project, text, ["flows/weekly.py", "scripts/sync/run.py"])
    assert status == "pass", detail
    assert "All 2" in detail


def test_an_unreflected_row_is_a_violation(project: Path) -> None:
    text = _table(
        ("prefect:weekly-training", "paused", "active", "Resumed"),
        ("prefect:retired-sync", "deprecated", "removed", "Deleted"),
        ("prefect:ghost", "active", "paused", "Typo"),
    )
    status, _, evidence = _check(project, text, [])
    assert status == "violation"
    assert evidence["unreflected"] == [
        "prefect:weekly-training: inventory says paused, table says active",
        "prefect:retired-sync: still listed, but After is removed",
        "prefect:ghost: not in the inventory",
    ]


def test_a_dormant_change_without_a_row_is_a_violation(project: Path) -> None:
    text = _table(("prefect:weekly-training", "paused", "paused", "Kept paused"))
    status, detail, evidence = _check(
        project, text, ["flows/weekly.py", "scripts/sync/run.py", "README.md"]
    )
    assert status == "violation"
    assert "1 paused or deprecated component(s) changed without a table row" in detail
    assert [f["component"] for f in evidence["inv_008"]] == ["prefect:retired-sync"]
    assert all(f["id"] == "INV-008" for f in evidence["inv_008"])


def test_an_unreadable_inventory_is_a_violation(project: Path) -> None:
    (project / "docs" / "ai" / "system_inventory.yaml").write_text("components: [\n")
    status, detail, _ = _check(project, _table(("a:b", "x", "y", "z")), [])
    assert status == "violation"
    assert "cannot be read" in detail


class _Store:
    """Answers the two queries the disposition row makes."""

    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings

    def query(self, sql: str) -> list[dict[str, Any]]:
        if "FROM Plan" in sql:
            return [{"project": ""}]
        return self.findings


def _finding(fid: str, text: str, status: str = "open") -> dict[str, Any]:
    return {
        "id": fid,
        "reviewType": "pre_review",
        "category": "COMPONENT",
        "status": status,
        "finding": text,
    }


def test_a_component_finding_is_answered_by_a_table_row(project: Path) -> None:
    cfg = load_config(project / "scaffold.yaml")
    plan = {"p.id": "plan::300", "p.number": 300}
    store = _Store(
        [
            _finding("f1", "Component prefect:weekly-training is paused since 2026-06-16."),
            _finding("f2", "Component prefect:retired-sync is deprecated."),
        ]
    )
    text = _table(("prefect:weekly-training", "paused", "paused", "Kept paused"))

    status, _, evidence = _check_disposition(store, plan, cfg, text)  # type: ignore[arg-type]
    assert status == "violation"
    assert evidence["undisposed"] == ["f2"]

    store.findings[1]["status"] = "not_applicable"
    status, _, _ = _check_disposition(store, plan, cfg, text)  # type: ignore[arg-type]
    assert status == "pass"
