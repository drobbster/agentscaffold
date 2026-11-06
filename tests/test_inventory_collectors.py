"""Shipped inventory collectors and source discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.inventory import collectors
from agentscaffold.inventory.collectors import (
    collect,
    read_compose,
    read_github_workflow,
    read_prefect,
    read_pyproject_scripts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "system_inventory" / "project"


def test_prefect_kinds_paused_and_parameters() -> None:
    text = (FIXTURE / "prefect.yaml").read_text(encoding="utf-8")
    found = {c.id: c for c in read_prefect("prefect.yaml", text)}

    assert set(found) == {
        "prefect:weekly-training",
        "prefect:weekly-training-copy",
        "prefect:nightly-ingest",
        "prefect:backfill",
        "prefect:unlisted-report",
    }
    assert found["prefect:weekly-training"].kind == "scheduled_job"
    assert found["prefect:weekly-training"].paused is True
    assert found["prefect:weekly-training-copy"].paused is False
    assert found["prefect:nightly-ingest"].kind == "scheduled_job"  # singular schedule
    assert found["prefect:backfill"].kind == "manual_job"
    assert found["prefect:weekly-training"].parameters == {"mode": "full"}
    assert (
        found["prefect:weekly-training"].parameters_key()
        == found["prefect:weekly-training-copy"].parameters_key()
    )


def test_prefect_paused_flag_and_rebased_entrypoint() -> None:
    text = """
deployments:
  - name: a
    paused: true
    entrypoint: flows/a.py:a
    schedules: [{cron: "0 1 * * *"}]
  - name: b
    entrypoint: b.py:b
    schedules: []
"""
    found = {c.id: c for c in read_prefect("pipelines/prefect.yaml", text)}
    assert found["prefect:a"].paused is True
    assert found["prefect:a"].entrypoint == "pipelines/flows/a.py:a"
    assert found["prefect:b"].kind == "manual_job"
    assert found["prefect:b"].entrypoint == "pipelines/b.py:b"


def test_prefect_ignores_nameless_deployments() -> None:
    found = read_prefect("prefect.yaml", "deployments:\n  - entrypoint: x.py:f\n  - 3\n")
    assert found == []


def test_compose_services() -> None:
    text = (FIXTURE / "compose.yaml").read_text(encoding="utf-8")
    found = {c.id: c for c in read_compose("compose.yaml", text)}
    assert found["compose:api"].kind == "service"
    assert found["compose:api"].entrypoint == "uvicorn app.main:app"
    assert found["compose:worker"].entrypoint == "python -m worker"


def test_github_workflow_named_by_stem() -> None:
    found = read_github_workflow(".github/workflows/ci.yml", "on: push\njobs: {}\n")
    assert [(c.id, c.kind, c.name) for c in found] == [("github_workflows:ci", "workflow", "ci")]


def test_pyproject_scripts() -> None:
    text = '[project]\nname = "x"\n\n[project.scripts]\nscaffold = "pkg.cli:app"\n'
    found = read_pyproject_scripts("pyproject.toml", text)
    assert [(c.id, c.entrypoint) for c in found] == [("pyproject_scripts:scaffold", "pkg.cli:app")]


def test_collect_uses_default_sources_and_records_kinds(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("services:\n  db: {image: postgres:16}\n")
    result = collect(tmp_path, [("compose", []), ("prefect", [])])
    assert result.collectors == ["compose", "prefect"]
    assert result.kinds == {"service", "scheduled_job", "manual_job"}
    assert [c.id for c in result.components] == ["compose:db"]
    assert result.sources_read == ["compose.yaml"]


def test_collect_reports_unreadable_sources_and_unknown_collectors(tmp_path: Path) -> None:
    (tmp_path / "prefect.yaml").write_text("deployments: [\n")
    result = collect(tmp_path, [("prefect", []), ("nope", [])])
    assert result.components == []
    assert any("cannot read prefect.yaml" in p for p in result.problems)
    assert any("unknown collector 'nope'" in p for p in result.problems)


def test_collect_globs_and_skips_invalid_sources(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("on: push\n")
    (workflows / "release.yaml").write_text("on: push\n")
    result = collect(
        tmp_path,
        [("github_workflows", [".github/workflows/*.yml", ".github/workflows/*.yaml", "../x"])],
    )
    assert sorted(c.id for c in result.components) == [
        "github_workflows:ci",
        "github_workflows:release",
    ]


def test_repo_source_in_a_monorepo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    project = tmp_path / "svc"
    project.mkdir()
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "prefect.yaml").write_text(
        "deployments:\n  - name: j\n    entrypoint: flows/j.py:j\n"
    )
    result = collect(project, [("prefect", ["@repo/deploy/prefect.yaml"])])
    (job,) = result.components
    assert job.source == "@repo/deploy/prefect.yaml"
    assert job.entrypoint == "@repo/deploy/flows/j.py:j"


def test_compose_records_image_and_falls_back_to_entrypoint_then_dockerfile() -> None:
    text = """
services:
  cache: {image: fixture/cache:7}
  web:
    entrypoint: ["gunicorn", "app:wsgi"]
  builder:
    build: {context: ./svc, dockerfile: Dockerfile.prod}
  short:
    build: ./other
  remote:
    build: https://example.com/repo.git
"""
    found = {c.id: c for c in read_compose("deploy/compose.yaml", text)}
    assert found["compose:cache"].image == "fixture/cache:7"
    assert found["compose:cache"].entrypoint is None
    assert found["compose:web"].entrypoint == "gunicorn app:wsgi"
    assert found["compose:builder"].entrypoint == "deploy/svc/Dockerfile.prod"
    assert found["compose:short"].entrypoint == "deploy/other/Dockerfile"
    assert found["compose:remote"].entrypoint is None


def test_default_sources_find_nested_files(tmp_path: Path) -> None:
    nested = tmp_path / "services" / "ingest"
    nested.mkdir(parents=True)
    (nested / "docker-compose.prod.yml").write_text("services:\n  a: {image: x}\n")
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "prefect.yaml").write_text(
        "deployments:\n  - name: j\n    entrypoint: flows/j.py:j\n"
    )
    result = collect(tmp_path, [("compose", []), ("prefect", [])])
    assert sorted(c.id for c in result.components) == ["compose:a", "prefect:j"]
    assert result.sources_by_collector["compose"] == ["services/ingest/docker-compose.prod.yml"]
    (job,) = [c for c in result.components if c.id == "prefect:j"]
    assert job.entrypoint == "pipelines/flows/j.py:j"


def test_default_sources_skip_ignored_directories(tmp_path: Path) -> None:
    for skipped in ("node_modules/pkg", ".venv/lib", "build/out"):
        directory = tmp_path / skipped
        directory.mkdir(parents=True)
        (directory / "compose.yaml").write_text("services:\n  hidden: {image: x}\n")
    (tmp_path / ".gitignore").write_text("build/\n")
    result = collect(tmp_path, [("compose", [])])
    assert result.components == []


def test_an_anchored_glob_does_not_search_nested_directories(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "compose.yaml").write_text("services:\n  x: {image: x}\n")
    assert collect(tmp_path, [("compose", ["compose.yaml"])]).components == []
    assert [c.id for c in collect(tmp_path, [("compose", ["a/**/compose.yaml"])]).components] == [
        "compose:x"
    ]


def test_collectors_that_find_nothing_leave_a_notice(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    result = collect(tmp_path, [("compose", []), ("prefect", [])])
    assert any(
        "collector compose read 1 file(s) but found no components" in n for n in result.notices
    )
    assert any(n.startswith("collector prefect matched no files") for n in result.notices)
    assert result.problems == []


def test_register_collector_validates_the_name() -> None:
    with pytest.raises(ValueError):
        collectors.register_collector("Bad-Name", {"x"}, [], lambda s, t: [])


def test_collector_for() -> None:
    assert collectors.collector_for("prefect:x") == "prefect"
    assert collectors.collector_for("config:x") is None
    assert collectors.collector_for("noprefix") is None
