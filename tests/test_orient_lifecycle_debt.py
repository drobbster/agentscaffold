"""Orientation's ``lifecycle_debt`` from the system inventory (Plan 282)."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentscaffold.config import load_config
from agentscaffold.mcp.session_brief import DEBT_CAP, lifecycle_debt

FIXTURE = Path(__file__).parent / "fixtures" / "system_inventory" / "project"
TODAY = dt.date(2026, 11, 5)
INVENTORY = Path("docs") / "ai" / "system_inventory.yaml"
SNAPSHOT = Path("outputs") / "governance" / "inventory_health.json"


class _Store:
    def __init__(self, plans: list[dict[str, Any]] | None = None) -> None:
        self.plans = plans or []

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.plans


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    return root


def _debt(root: Path, store: Any = None, **kwargs: Any) -> dict[str, Any] | None:
    cfg = load_config(root / "scaffold.yaml")
    return lifecycle_debt(store or _Store(), root, cfg, today=TODAY, **kwargs)


def test_the_fixture_debt(project: Path) -> None:
    debt = _debt(project)
    assert debt == {
        "expired_reviews": {
            "count": 1,
            "items": ["prefect:weekly-training (review by 2026-10-31)"],
        },
        # Days count from the snapshot's generated_at (2026-11-04), not today.
        "failing": {"count": 1, "items": ["prefect:nightly-ingest (21 days)"]},
        "zombies": {"count": 1, "items": ["prefect:weekly-training (171 days)"]},
        "architecture_review": "last review 2026-09-01 is 65 days old (cadence 30 days)",
    }


def test_disabled_inventory_has_no_debt_key(project: Path) -> None:
    cfg = load_config(project / "scaffold.yaml")
    cfg.inventory.enabled = False
    assert lifecycle_debt(_Store(), project, cfg, today=TODAY) is None


def test_an_unreadable_inventory_says_so(project: Path) -> None:
    (project / INVENTORY).write_text("components: [\n")
    debt = _debt(project)
    assert debt is not None
    assert "cannot be read" in debt["error"]


def test_overdue_deprecations_are_their_own_category(project: Path) -> None:
    path = project / INVENTORY
    path.write_text(path.read_text().replace("review_by: 2026-12-31", "review_by: 2026-10-01"))
    debt = _debt(project)
    assert debt is not None
    assert debt["overdue_deprecations"]["items"] == ["prefect:retired-sync (review by 2026-10-01)"]


def test_no_snapshot_means_no_health_categories(project: Path) -> None:
    (project / SNAPSHOT).unlink()
    debt = _debt(project)
    assert debt is not None
    assert "failing" not in debt
    assert "zombies" not in debt
    assert "health_snapshot" not in debt


def test_a_stale_snapshot_is_reported(project: Path) -> None:
    path = project / SNAPSHOT
    data = json.loads(path.read_text())
    data["generated_at"] = "2026-09-01T00:00:00Z"
    path.write_text(json.dumps(data))
    debt = _debt(project)
    assert debt is not None
    assert debt["health_snapshot"]["status"] == "stale"


def test_a_missing_review_date_is_debt(project: Path) -> None:
    path = project / INVENTORY
    data = yaml.safe_load(path.read_text())
    data.pop("last_architecture_review")
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    debt = _debt(project)
    assert debt is not None
    assert debt["architecture_review"] == "last_architecture_review is not recorded"


def test_stale_drafts_come_from_the_graph(project: Path) -> None:
    store = _Store(
        [
            {"number": 7, "status": "Draft", "createdDate": "2026-08-01"},
            {"number": 8, "status": "draft", "createdDate": "2026-10-20"},
            {"number": 9, "status": "Complete", "createdDate": "2026-01-01"},
            {"number": 10, "status": "Draft", "createdDate": "unknown"},
        ]
    )
    debt = _debt(project, store)
    assert debt is not None
    assert debt["stale_drafts"] == {"count": 1, "items": ["Plan 7 (96 days)"]}


def test_items_are_capped_but_counts_are_not(project: Path) -> None:
    store = _Store(
        [{"number": n, "status": "Draft", "createdDate": "2026-01-01"} for n in range(25)]
    )
    debt = _debt(project, store)
    assert debt is not None
    assert debt["stale_drafts"]["count"] == 25
    assert len(debt["stale_drafts"]["items"]) == DEBT_CAP


def test_orient_brief_carries_lifecycle_debt(tmp_path: Path, project: Path) -> None:
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.pipeline import run_pipeline
    from agentscaffold.mcp.session_brief import build_session_brief

    config = yaml.safe_load((project / "scaffold.yaml").read_text())
    config["graph"] = {"db_path": str(tmp_path / "graph.duckdb"), "embeddings": False}
    (project / "scaffold.yaml").write_text(yaml.safe_dump(config))
    cfg = load_config(project / "scaffold.yaml")
    run_pipeline(project, cfg, quiet=True)

    store = DuckPGQBackend(Path(str(cfg.graph.db_path)), read_only=True)
    try:
        brief = build_session_brief(store, root=project, workflow={}, open_session=None, config=cfg)
        assert isinstance(brief["lifecycle_debt"], dict)
        cfg.inventory.enabled = False
        brief = build_session_brief(store, root=project, workflow={}, open_session=None, config=cfg)
        assert "lifecycle_debt" not in brief
    finally:
        store.close()
