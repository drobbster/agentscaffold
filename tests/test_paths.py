"""Tests for unified project-root and governance-path resolution (Plan 221)."""

from __future__ import annotations

from pathlib import Path

import yaml

from agentscaffold.config import ScaffoldConfig, load_config
from agentscaffold.paths import ResolvedPaths, resolve_root


def _write_scaffold(dir_path: Path, graph: dict | None = None) -> Path:
    data: dict = {"framework": {"project_name": "T"}}
    if graph is not None:
        data["graph"] = graph
    path = dir_path / "scaffold.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_resolve_root_prefers_scaffold_yaml(tmp_path: Path) -> None:
    """A directory with scaffold.yaml is the root, even nested under .git."""
    (tmp_path / ".git").mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    _write_scaffold(proj)
    sub = proj / "src" / "deep"
    sub.mkdir(parents=True)

    assert resolve_root(sub) == proj.resolve()


def test_resolve_root_falls_back_to_git(tmp_path: Path) -> None:
    """With no scaffold.yaml, the nearest .git ancestor is the root."""
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)

    assert resolve_root(sub) == tmp_path.resolve()


def test_resolve_root_falls_back_to_start(tmp_path: Path) -> None:
    """With no scaffold.yaml and no .git, the start dir is the root."""
    sub = tmp_path / "x"
    sub.mkdir()

    assert resolve_root(sub) == sub.resolve()


def test_resolved_paths_defaults_equal_literals(tmp_path: Path) -> None:
    """Uncustomized config reproduces the historical hardcoded literals."""
    rp = ResolvedPaths(ScaffoldConfig(), tmp_path)

    assert rp.plans_dir == tmp_path / "docs/ai/plans"
    assert rp.contracts_dir == tmp_path / "docs/ai/contracts"
    assert rp.studies_dir == tmp_path / "docs/studies"
    assert rp.adrs_dir == tmp_path / "docs/ai/adrs"
    assert rp.spikes_dir == tmp_path / "docs/ai/spikes"
    assert rp.learnings_file == tmp_path / "docs/ai/state/learnings_tracker.md"
    assert rp.workflow_state_file == tmp_path / "docs/ai/state/workflow_state.md"
    assert rp.backlog_file == tmp_path / "docs/ai/backlog.md"
    assert rp.standards_dir == tmp_path / "docs/ai/standards"
    assert rp.prompts_dir == tmp_path / "docs/ai/prompts"
    assert rp.security_dir == tmp_path / "docs/security"
    assert rp.db_path == tmp_path / ".scaffold/graph.duckdb"


def test_resolved_paths_honor_customized_config(tmp_path: Path) -> None:
    """Customized graph.* paths take effect through the accessor."""
    cfg = load_config(
        _write_scaffold(tmp_path, graph={"plans_dir": "plans/", "db_path": "var/graph.duckdb"})
    )
    rp = ResolvedPaths(cfg, tmp_path)

    assert rp.plans_dir == tmp_path / "plans"
    assert rp.db_path == tmp_path / "var/graph.duckdb"


def test_resolved_paths_absolute_db_path_is_honored(tmp_path: Path) -> None:
    """An absolute db_path is not re-rooted."""
    abs_db = tmp_path / "elsewhere" / "graph.duckdb"
    cfg = load_config(_write_scaffold(tmp_path, graph={"db_path": str(abs_db)}))
    rp = ResolvedPaths(cfg, tmp_path / "ignored")

    assert rp.db_path == abs_db


def test_discover_loads_config_and_root(tmp_path: Path) -> None:
    """discover() finds scaffold.yaml from a nested start dir."""
    _write_scaffold(tmp_path, graph={"plans_dir": "custom-plans/"})
    sub = tmp_path / "nested"
    sub.mkdir()

    rp = ResolvedPaths.discover(sub)
    assert rp.root == tmp_path.resolve()
    assert rp.plans_dir == tmp_path.resolve() / "custom-plans"
