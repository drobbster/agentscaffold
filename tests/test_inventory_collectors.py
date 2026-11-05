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


def test_register_collector_validates_the_name() -> None:
    with pytest.raises(ValueError):
        collectors.register_collector("Bad-Name", {"x"}, [], lambda s, t: [])


def test_collector_for() -> None:
    assert collectors.collector_for("prefect:x") == "prefect"
    assert collectors.collector_for("config:x") is None
    assert collectors.collector_for("noprefix") is None
