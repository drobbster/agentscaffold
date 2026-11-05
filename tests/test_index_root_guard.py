"""``scaffold index`` refuses a directory that only contains projects.

Two shapes reach the pipeline without a project to index: an unregistered
monorepo root that contains registered team folders (which used to build an
in-tree graph of the whole repository), and a multi-project workspace root that
is not itself a project (which used to fail with a bare ``ScopingError``). Both
now refuse with the same message naming the projects. Every directory that is
or sits inside a project indexes as before.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app
from agentscaffold.graph import index
from agentscaffold.graph.scoping import IndexRootError, check_index_root


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.delenv("AGENTSCAFFOLD_DB_PATH", raising=False)


def _project(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scaffold.yaml").write_text(f"framework:\n  project_name: {name}\n")
    (directory / "module.py").write_text("def f():\n    return 1\n")
    return directory


def _register(root: Path, projects: list[tuple[str, str]] | None = None) -> None:
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(root, projects=projects)


def _monorepo(tmp_path: Path) -> Path:
    """A company repo with one registered team folder and no scaffold.yaml at its root."""
    repo = tmp_path / "monorepo"
    (repo / ".git").mkdir(parents=True)
    (repo / "services" / "other").mkdir(parents=True)
    _register(_project(repo / "teams" / "payments", "payments"))
    return repo


def _multi_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    _project(ws / "alpha", "alpha")
    _project(ws / "beta", "beta")
    (ws / "workspace.yaml").write_text(
        yaml.safe_dump(
            {"projects": [{"name": "alpha", "path": "alpha"}, {"name": "beta", "path": "beta"}]},
            sort_keys=False,
        )
    )
    return ws


# ---------------------------------------------------------------------------
# Refused
# ---------------------------------------------------------------------------


def test_unregistered_monorepo_root_is_refused_naming_the_project(tmp_path: Path):
    repo = _monorepo(tmp_path)

    with pytest.raises(IndexRootError) as excinfo:
        check_index_root(repo)

    assert "payments" in str(excinfo.value)
    assert "--force-root" in str(excinfo.value)


def test_index_refuses_before_writing_anything(tmp_path: Path):
    repo = _monorepo(tmp_path)

    with pytest.raises(IndexRootError):
        index(path=repo)

    assert not (repo / ".scaffold").exists()


def test_multi_project_workspace_root_is_refused_not_a_scoping_error(tmp_path: Path):
    ws = _multi_workspace(tmp_path)

    with pytest.raises(IndexRootError) as excinfo:
        check_index_root(ws)

    assert "alpha" in str(excinfo.value) and "beta" in str(excinfo.value)


def test_registered_multi_project_workspace_root_is_refused(tmp_path: Path):
    ws = _multi_workspace(tmp_path)
    _register(ws, projects=[("alpha", "alpha"), ("beta", "beta")])

    with pytest.raises(IndexRootError):
        check_index_root(ws)


def test_force_root_proceeds(tmp_path: Path):
    repo = _monorepo(tmp_path)

    with patch("agentscaffold.graph.pipeline.run_pipeline", return_value={}) as pipeline:
        index(path=repo, force_root=True)

    assert pipeline.called


# ---------------------------------------------------------------------------
# Unaffected
# ---------------------------------------------------------------------------


def test_lone_unregistered_repo_root_is_allowed(tmp_path: Path):
    check_index_root(_project(tmp_path / "solo", "solo"))


def test_registered_lone_repo_root_is_allowed(tmp_path: Path):
    project = _project(tmp_path / "solo", "solo")
    _register(project)
    check_index_root(project)


def test_registered_project_inside_a_monorepo_is_allowed(tmp_path: Path):
    repo = _monorepo(tmp_path)
    check_index_root(repo / "teams" / "payments")


def test_subdirectory_of_a_project_is_allowed(tmp_path: Path):
    ws = _multi_workspace(tmp_path)
    (ws / "alpha" / "pkg").mkdir()
    check_index_root(ws / "alpha" / "pkg")


def test_workspace_project_member_is_allowed(tmp_path: Path):
    ws = _multi_workspace(tmp_path)
    _register(ws, projects=[("alpha", "alpha"), ("beta", "beta")])
    check_index_root(ws / "alpha")


def test_project_at_the_workspace_root_is_allowed(tmp_path: Path):
    """A workspace whose root is itself a project (``path: .``) indexes that project."""
    ws = tmp_path / "ws"
    _project(ws, "root")
    _project(ws / "sub", "sub")
    (ws / "workspace.yaml").write_text(
        yaml.safe_dump(
            {"projects": [{"name": "root", "path": "."}, {"name": "sub", "path": "sub"}]},
            sort_keys=False,
        )
    )
    _register(ws, projects=[("root", "."), ("sub", "sub")])
    check_index_root(ws)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_index_at_a_monorepo_root_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _monorepo(tmp_path)
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(app, ["index", str(repo)])

    assert result.exit_code != 0
    assert "payments" in result.output


def test_cli_index_force_root_proceeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _monorepo(tmp_path)
    monkeypatch.chdir(repo)

    with patch("agentscaffold.graph.pipeline.run_pipeline", return_value={}) as pipeline:
        result = CliRunner().invoke(app, ["index", str(repo), "--force-root"])

    assert result.exit_code == 0, result.output
    assert pipeline.called
