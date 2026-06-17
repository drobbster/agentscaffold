"""Integration tests for Plan 221 path/root unification.

Verifies the two intended behavior changes:
1. CLI commands honor a customized ``graph.*`` path instead of the hardcoded
   ``docs/ai/*`` literal.
2. ``open_graph`` resolves a relative ``db_path`` against the project root, so
   it finds the graph when invoked from a subdirectory.
"""

from __future__ import annotations

from pathlib import Path


def _write_project(proj: Path, graph_yaml: str = "") -> None:
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "scaffold.yaml").write_text(
        "framework:\n  project_name: test\n  architecture_layers: 3\n" + graph_yaml
    )


def test_plan_create_honors_customized_plans_dir(tmp_path: Path, monkeypatch) -> None:
    """A customized graph.plans_dir is where new plans land."""
    proj = tmp_path / "proj"
    _write_project(proj, "graph:\n  plans_dir: planning/specs/\n")
    monkeypatch.chdir(proj)

    from agentscaffold.plan.create import run_plan_create

    run_plan_create(name="custom-dir-feature", plan_type="feature")

    custom = sorted((proj / "planning" / "specs").glob("*.md"))
    assert len(custom) == 1
    assert not (proj / "docs" / "ai" / "plans").exists()


def test_study_create_honors_customized_studies_dir(tmp_path: Path, monkeypatch) -> None:
    """A customized graph.studies_dir is where new studies land."""
    proj = tmp_path / "proj"
    _write_project(proj, "graph:\n  studies_dir: research/\n")
    monkeypatch.chdir(proj)

    from agentscaffold.study.create import run_study_create

    run_study_create(name="custom-study")

    assert len(sorted((proj / "research").glob("STU-*.md"))) == 1


def test_plan_create_from_subdirectory_uses_project_root(tmp_path: Path, monkeypatch) -> None:
    """Invoked from a nested dir, the plan still lands under the project root."""
    proj = tmp_path / "proj"
    _write_project(proj)
    sub = proj / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)

    from agentscaffold.plan.create import run_plan_create

    run_plan_create(name="subdir-feature", plan_type="feature")

    plans = sorted((proj / "docs" / "ai" / "plans").glob("*.md"))
    assert len(plans) == 1


def test_open_graph_resolves_db_from_subdirectory(tmp_path: Path, monkeypatch) -> None:
    """open_graph finds the root-anchored DB even when cwd is a subdirectory."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph
    from agentscaffold.graph.pipeline import run_pipeline

    proj = tmp_path / "proj"
    _write_project(proj)
    src = proj / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 1\n")

    config = load_config(proj / "scaffold.yaml")
    run_pipeline(proj, config)

    expected_db = proj / ".scaffold" / "graph.duckdb"
    assert expected_db.is_file()

    sub = proj / "src"
    monkeypatch.chdir(sub)
    cfg_from_sub = load_config()

    assert graph_available(cfg_from_sub) is True
    store = open_graph(cfg_from_sub)
    try:
        assert store.node_count("File") >= 1
    finally:
        store.close()
