"""Plan 281 Phase B: precedent in the pre-implementation review and while coding.

The devil's advocate challenges gain ``PRECEDENT`` items (earlier findings and
ADRs about the plan's files), learning challenges are ranked by the same
scoring, the review brief carries a plan-level ``precedent`` section,
``scaffold_prepare_implementation`` returns a short reminder list, and
``scaffold_impact`` reports every governance fact about the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.config import load_config
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.findings import record_finding
from agentscaffold.review.brief import generate_brief
from agentscaffold.review.challenges import generate_challenges

pytest.importorskip("duckdb", reason="duckdb not installed")

ROUTER = "libs/data/router.py"
PLAN = 91

PLAN_91 = f"""# Plan 091: Router retries

## 0. Metadata
- Plan: {PLAN}
- Status: Draft

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| {ROUTER} | Modify | retries |
| src/data/router.py | Modify | old layout |

## 8. Execution Steps
- [ ] Step 1: Add retries.
"""

LEARNINGS = f"""# Learnings Tracker

| ID | Plan | Description | Target | Status |
|----|------|-------------|--------|--------|
| L050-1 | 50 | Older pending note about `{ROUTER}` | {ROUTER} | Pending |
| L080-1 | 80 | Newer incorporated note about `{ROUTER}` | {ROUTER} | Incorporated |
"""


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from tests.fixtures.lone_project import build_lone_project

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    root = build_lone_project(
        tmp_path,
        extra_files={
            f"docs/ai/plans/plan_{PLAN:03d}_router_retries.md": PLAN_91,
            "docs/ai/state/learnings_tracker.md": LEARNINGS,
        },
    )
    store = DuckPGQBackend(tmp_path / "lone.duckdb")
    try:
        for i in range(8):
            record_finding(
                store,
                plan_number=40 + i,
                review_type="devils_advocate",
                category="RISK",
                severity="high" if i == 7 else "medium",
                finding=f"Router risk number {i}.",
                file_paths=[ROUTER, "src/data/router.py"],
            )
        record_finding(
            store,
            plan_number=60,
            review_type="pre_review",
            category="HISTORY",
            finding="Router churn statistic.",
            file_paths=[ROUTER],
        )
    finally:
        store.close()
    return root


def _store(tmp_path: Path, read_only: bool = True) -> DuckPGQBackend:
    return DuckPGQBackend(tmp_path / "lone.duckdb", read_only=read_only)


def _challenges(repo: Path, tmp_path: Path):
    store = _store(tmp_path)
    try:
        return generate_challenges(
            store, PLAN, root=repo, config=load_config(repo / "scaffold.yaml")
        )
    finally:
        store.close()


def test_precedent_challenges_are_capped_and_deduplicated(repo: Path, tmp_path: Path):
    precedent = [c for c in _challenges(repo, tmp_path) if c.category == "PRECEDENT"]
    assert len(precedent) == 5
    ids = [c.evidence["precedent_id"] for c in precedent]
    assert len(set(ids)) == 5
    assert precedent[0].severity == "high"
    assert "Router risk number 7." in precedent[0].text
    assert all("Router churn statistic." not in c.text for c in precedent)


def test_precedent_challenge_cap_is_configurable(repo: Path, tmp_path: Path):
    config_path = repo / "scaffold.yaml"
    config_path.write_text(config_path.read_text() + "precedent:\n  max_challenges: 2\n")
    precedent = [c for c in _challenges(repo, tmp_path) if c.category == "PRECEDENT"]
    assert len(precedent) == 2


def test_learning_challenges_rank_by_precedent_not_status(repo: Path, tmp_path: Path):
    learning = [c for c in _challenges(repo, tmp_path) if c.category == "LEARNING"]
    ids = [c.evidence["learning_id"] for c in learning]
    assert ids.index("L080-1") < ids.index("L050-1")


def test_brief_has_a_plan_level_precedent_section(repo: Path, tmp_path: Path):
    store = _store(tmp_path)
    try:
        brief = generate_brief(store, PLAN, root=repo, config=load_config(repo / "scaffold.yaml"))
    finally:
        store.close()
    section = brief["precedent"]
    assert section["total"] >= 8
    assert 0 < len(section["items"]) <= 10
    assert section["items"][0]["id"].startswith("rf::")
    assert section["sources_unavailable"] == []


def test_cli_prints_precedent_as_json(repo: Path, monkeypatch: pytest.MonkeyPatch):
    import json

    from typer.testing import CliRunner

    from agentscaffold.cli import app

    monkeypatch.chdir(repo)
    result = CliRunner().invoke(
        app, ["review", "precedent", ROUTER, "--plan", str(PLAN), "--limit", "3", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["items"]) == 3
    assert payload["total"] > 3


def test_disabled_precedent_omits_every_section(repo: Path, tmp_path: Path):
    config_path = repo / "scaffold.yaml"
    config_path.write_text(config_path.read_text() + "precedent:\n  enabled: false\n")
    config = load_config(config_path)
    store = _store(tmp_path)
    try:
        brief = generate_brief(store, PLAN, root=repo, config=config)
        challenges = generate_challenges(store, PLAN, root=repo, config=config)
    finally:
        store.close()
    assert "precedent" not in brief
    assert not [c for c in challenges if c.category == "PRECEDENT"]
    assert [c for c in challenges if c.category == "LEARNING"]


def test_precedent_failure_leaves_brief_and_challenges_intact(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def boom(*_args, **_kwargs):
        raise RuntimeError("precedent source exploded")

    monkeypatch.setattr("agentscaffold.review.precedent.precedent_for_paths", boom)
    monkeypatch.setattr("agentscaffold.review.challenges.precedent_for_paths", boom)
    config = load_config(repo / "scaffold.yaml")
    store = _store(tmp_path)
    try:
        brief = generate_brief(store, PLAN, root=repo, config=config)
        challenges = generate_challenges(store, PLAN, root=repo, config=config)
    finally:
        store.close()
    assert "precedent" not in brief
    assert brief["file_profiles"]
    assert not [c for c in challenges if c.category == "PRECEDENT"]
    assert challenges


def _dispatch(name: str, repo: Path, monkeypatch: pytest.MonkeyPatch, **args) -> dict:
    from agentscaffold.mcp import freshness
    from agentscaffold.mcp.server import _dispatch_tool

    monkeypatch.setattr(
        freshness, "evaluate_freshness", lambda *_a, **_k: {"freshness_status": "fresh"}
    )
    return _dispatch_tool(name, {"working_path": str(repo), **args})


def test_prepare_implementation_returns_a_short_precedent_list(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    result = _dispatch("scaffold_prepare_implementation", repo, monkeypatch, plan_number=PLAN)
    items = result["precedent"]
    assert 0 < len(items) <= 5
    assert set(items[0]) == {"id", "kind", "match", "plan", "project", "text"}


def test_impact_reports_every_governance_fact_about_the_file(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    result = _dispatch("scaffold_impact", repo, monkeypatch, file_or_symbol=ROUTER)
    gov = result["governance_impact"]
    assert gov["counts"]["findings"] == 8
    assert len(gov["findings"]) == 8
    assert all(f["match"] in {"linked", "path"} for f in gov["findings"])
    assert all("churn statistic" not in f["text"] for f in gov["findings"])
    assert {lr["id"] for lr in gov["learnings"]} >= {"learning::L050-1", "learning::L080-1"}
    assert gov["counts"]["contracts"] == len(gov["contracts"])
    assert "Governance impact" in result["markdown"]


def test_impact_governance_section_is_not_capped(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path, read_only=False)
    try:
        for i in range(12):
            record_finding(
                store,
                plan_number=100 + i,
                review_type="devils_advocate",
                category="RISK",
                severity="low",
                finding=f"Further router risk {i}.",
                file_paths=[ROUTER],
            )
    finally:
        store.close()
    result = _dispatch("scaffold_impact", repo, monkeypatch, file_or_symbol=ROUTER)
    gov = result["governance_impact"]
    assert gov["counts"]["findings"] == 20
    assert len(gov["findings"]) == 20


def test_impact_without_precedent_is_unchanged(repo: Path, monkeypatch: pytest.MonkeyPatch):
    with_section = _dispatch("scaffold_impact", repo, monkeypatch, file_or_symbol=ROUTER)
    without = _dispatch(
        "scaffold_impact", repo, monkeypatch, file_or_symbol=ROUTER, include_precedent=False
    )
    assert "governance_impact" not in without
    skip = {"governance_impact", "markdown", "meta"}

    # Importer and caller queries have no ORDER BY, so two identical calls can
    # list the same rows in a different order.
    def unordered(payload: dict) -> dict:
        return {
            k: sorted(map(str, v)) if isinstance(v, list) else v
            for k, v in payload.items()
            if k not in skip
        }

    assert unordered(with_section) == unordered(without)
