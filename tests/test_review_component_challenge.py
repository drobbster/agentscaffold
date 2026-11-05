"""COMPONENT challenges in the pre-implementation review.

One challenge per paused or deprecated component whose ``reads`` or entrypoint
the plan's File Impact Map touches. Not capped, always shown and always
recorded, like PRECEDENT.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentscaffold.config import ScaffoldConfig, load_config
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.mcp.detail import apply_detail
from agentscaffold.review.challenges import Challenge, _check_components, generate_challenges
from agentscaffold.review.filters import ALWAYS_SHOWN_CATEGORIES

pytest.importorskip("duckdb", reason="duckdb not installed")

FIXTURE = Path(__file__).parent / "fixtures" / "system_inventory" / "project"
PLAN = """\
# Plan 200: Retune training

| Field | Value |
|-------|-------|
| Title | Retune training |
| Status | Draft |
| Type | feature |
| Created | 2026-11-01 |

## File Impact Map

| File | Change Type | Description |
|------|-------------|-------------|
| configs/training/lr.py | modify | New rate |
| flows/weekly.py | modify | Use the new rate |
| scripts/sync/run.py | modify | Touch the old sync |
| configs/ingest/sources.py | modify | Active component; no challenge |

## Execution Steps

- [ ] Step 1: Retune
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def indexed(tmp_path: Path) -> tuple[Path, Any]:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    config = yaml.safe_load((root / "scaffold.yaml").read_text())
    config["graph"] = {"db_path": str(tmp_path / "graph.duckdb"), "embeddings": False}
    (root / "scaffold.yaml").write_text(yaml.safe_dump(config))
    _write(root / "flows" / "weekly.py", "def weekly_training():\n    return 1\n")
    _write(root / "configs" / "training" / "lr.py", "RATE = 0.1\n")
    _write(root / "configs" / "ingest" / "sources.py", "SOURCES = []\n")
    _write(root / "scripts" / "sync" / "run.py", "def main():\n    return 0\n")
    _write(root / "docs" / "ai" / "plans" / "200-retune-training.md", PLAN)
    cfg = load_config(root / "scaffold.yaml")
    run_pipeline(root, cfg, quiet=True)
    return root, cfg


def _store(cfg: Any) -> DuckPGQBackend:
    return DuckPGQBackend(Path(str(cfg.graph.db_path)), read_only=True)


def test_one_challenge_per_dormant_component(indexed: tuple[Path, Any]) -> None:
    root, cfg = indexed
    store = _store(cfg)
    try:
        challenges = generate_challenges(store, 200, root=root, config=cfg)
    finally:
        store.close()
    component = [c for c in challenges if c.category == "COMPONENT"]
    by_id = {c.evidence["component"]: c for c in component}
    # Paused and deprecated only: the active nightly ingest is not challenged.
    assert set(by_id) == {"prefect:weekly-training", "prefect:retired-sync"}
    weekly = by_id["prefect:weekly-training"]
    # Touched through both reads and the entrypoint, raised once.
    assert weekly.evidence["touched"] == ["configs/training/lr.py", "flows/weekly.py"]
    assert weekly.severity == "medium"
    assert "paused since 2026-06-16" in weekly.text
    assert "review by 2026-10-31" in weekly.text
    assert "exit: Training environment backlog item closed" in weekly.text
    assert "Component Lifecycle Changes table" in weekly.text
    assert "replaced by prefect:nightly-ingest" in by_id["prefect:retired-sync"].text


def test_no_challenges_when_the_inventory_is_disabled(indexed: tuple[Path, Any]) -> None:
    root, cfg = indexed
    cfg.inventory.enabled = False
    store = _store(cfg)
    try:
        challenges = generate_challenges(store, 200, root=root, config=cfg)
    finally:
        store.close()
    assert not [c for c in challenges if c.category == "COMPONENT"]


def test_brief_has_a_component_lifecycle_section(indexed: tuple[Path, Any]) -> None:
    from agentscaffold.review.brief import format_brief_markdown, generate_brief

    root, cfg = indexed
    store = _store(cfg)
    try:
        brief = generate_brief(store, 200, root=root, config=cfg)
    finally:
        store.close()
    assert [h["component"] for h in brief["components"]] == [
        "prefect:weekly-training",
        "prefect:retired-sync",
    ]
    markdown = format_brief_markdown(brief)
    assert "## Component lifecycle" in markdown
    assert "- prefect:weekly-training: paused since 2026-06-16" in markdown


def _hit(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "component": f"prefect:job-{n}",
        "lifecycle": "paused",
        "since": "2026-01-01",
        "reason": "r",
        "review_by": "2027-01-01",
        "exit_criteria": "e",
        "touched": [f"configs/job{n}.yaml"],
        "broad_reads": [],
        **extra,
    }


def test_twelve_component_challenges_survive_the_summary_with_precedent() -> None:
    challenges: list[Challenge] = []
    _check_components([_hit(n) for n in range(12)], challenges)
    precedent = [Challenge(category="PRECEDENT", text=f"p{n}", severity="medium") for n in range(5)]
    others = [Challenge(category="HISTORY", text=f"h{n}", severity="high") for n in range(9)]
    payload = {"challenges": [c.__dict__ for c in [*others, *challenges, *precedent]]}

    trimmed = apply_detail(payload, "summary")["challenges"]
    categories = [c["category"] for c in trimmed]
    assert categories.count("COMPONENT") == 12
    assert categories.count("PRECEDENT") == 5
    assert categories.count("HISTORY") == 5


def test_broad_reads_are_called_out() -> None:
    out: list[Challenge] = []
    _check_components([_hit(1, broad_reads=["./"])], out)
    assert "cover much of the repository" in out[0].text
    assert out[0].evidence["broad_reads"] == ["./"]


def test_component_is_always_shown_and_recorded() -> None:
    from agentscaffold.mcp.server import _select_findings_to_persist

    assert "COMPONENT" in ALWAYS_SHOWN_CATEGORIES
    kept = _select_findings_to_persist(
        [
            {"category": "COMPONENT", "severity": "medium", "finding": "Component a:b"},
            {"category": "HISTORY", "severity": "medium", "finding": "noise"},
        ],
        [],
    )
    assert [f["category"] for f in kept] == ["COMPONENT"]


def test_recorded_component_findings_are_not_echoed_as_precedent() -> None:
    assert "COMPONENT" in ScaffoldConfig().precedent.automated_skip_categories
