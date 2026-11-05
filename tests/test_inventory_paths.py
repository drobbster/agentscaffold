"""Inventory path rules (contract v1, Paths) and path matching."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.inventory import paths


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "configs/", "./src/app.py", "@repo/airflow/dags/nightly.py", "a/b..c/d"],
)
def test_valid_paths(path: str) -> None:
    assert paths.path_problem(path) is None


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("//pkg/x", "'//'"),
        ("/etc/passwd", "absolute"),
        ("\\server\\share", "absolute"),
        ("C:/x", "absolute"),
        ("src\\app.py", "backslashes"),
        ("../shared/", "'..'"),
        ("src/../../x", "'..'"),
        ("@repo/../x", "'..'"),
        ("@repo//x", "malformed"),
    ],
)
def test_invalid_paths(path: str, reason: str) -> None:
    problem = paths.path_problem(path)
    assert problem is not None
    assert reason in problem


@pytest.mark.parametrize(
    ("entrypoint", "expected"),
    [
        ("flows/weekly.py:weekly_training", "flows/weekly.py"),
        ("app.py:main", "app.py"),
        ("scripts/run.sh", "scripts/run.sh"),
        ("@repo/dags/nightly.py:dag", "@repo/dags/nightly.py"),
        ("uvicorn app.main:app", None),
        ("python -m worker", None),
        ("postgres:16", None),
        ("mypkg.cli:main", None),
        (None, None),
        ("", None),
    ],
)
def test_entrypoint_path(entrypoint: str | None, expected: str | None) -> None:
    assert paths.entrypoint_path(entrypoint) == expected


def test_covers_and_touches() -> None:
    assert paths.covers("configs/", "configs/a.yaml")
    assert paths.covers("configs/", "configs")
    assert not paths.covers("configs/", "configs_old/a.yaml")
    assert paths.covers("src/app.py", "src/app.py")
    assert not paths.covers("src/app.py", "src/app.pyc")
    assert paths.covers("", "anything.py")
    # Editing a directory touches a file read below it.
    assert paths.touches("configs/risk/limits.yaml", "configs/")
    assert not paths.touches("configs/risk/limits.yaml", "src/")


def test_graph_path_for_project_relative(tmp_path: Path) -> None:
    assert paths.graph_path(tmp_path, "./src/app.py") == "src/app.py"
    assert paths.graph_path(tmp_path, "configs/") == "configs/"
    assert paths.graph_path(tmp_path, ".") == ""
    assert paths.graph_path(tmp_path, "../x") is None


def _monorepo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    project = tmp_path / "services" / "api"
    project.mkdir(parents=True)
    (project / "configs").mkdir()
    (tmp_path / "airflow" / "dags").mkdir(parents=True)
    (tmp_path / "airflow" / "dags" / "nightly.py").write_text("x = 1\n", encoding="utf-8")
    return project


def test_repo_path_inside_the_project_maps_to_project_relative(tmp_path: Path) -> None:
    project = _monorepo(tmp_path)
    assert paths.graph_path(project, "@repo/services/api/configs/") == "configs/"


def test_repo_path_outside_the_project_stays_repo_form(tmp_path: Path) -> None:
    project = _monorepo(tmp_path)
    assert paths.graph_path(project, "@repo/airflow/dags/nightly.py") == (
        "@repo/airflow/dags/nightly.py"
    )


def test_repo_path_without_a_vcs_root_is_unresolvable(tmp_path: Path) -> None:
    assert paths.graph_path(tmp_path, "@repo/x.py") is None


def test_to_inventory_path(tmp_path: Path) -> None:
    project = _monorepo(tmp_path)
    assert paths.to_inventory_path(project, project / "configs" / "a.yaml") == "configs/a.yaml"
    outside = tmp_path / "airflow" / "dags" / "nightly.py"
    assert paths.to_inventory_path(project, outside) == "@repo/airflow/dags/nightly.py"
