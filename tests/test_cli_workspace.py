"""CLI tests for ``scaffold workspace`` (Plan 225, Step 6).

Covers the read-only ``list`` (single + multi) and ``onboard`` (manifest
creation, the single->multi transition, relative-path storage, and duplicate
rejection). The destructive ``--migrate-existing`` re-key is exercised at the
backend level in test_multiproject_safety.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agentscaffold.cli import app


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
    (root / ".git").mkdir(exist_ok=True)
    return root


def test_workspace_list_single_project(tmp_path, monkeypatch, cli_runner):
    proj = _project(tmp_path / "solo")
    monkeypatch.chdir(proj)
    result = cli_runner.invoke(app, ["workspace", "list"])
    assert result.exit_code == 0
    assert "single-project" in result.output
    assert "solo" in result.output


def test_workspace_onboard_creates_manifest_and_goes_multi(tmp_path, monkeypatch, cli_runner):
    ws = tmp_path / "ws"
    ws.mkdir()
    _project(ws / "alpha")
    _project(ws / "beta")
    monkeypatch.chdir(ws)

    r1 = cli_runner.invoke(app, ["workspace", "onboard", "alpha"])
    assert r1.exit_code == 0, r1.output
    assert (ws / "workspace.yaml").is_file()

    r2 = cli_runner.invoke(app, ["workspace", "onboard", "beta"])
    assert r2.exit_code == 0, r2.output
    assert "multi-project" in r2.output

    manifest = yaml.safe_load((ws / "workspace.yaml").read_text())
    names = [p["name"] for p in manifest["projects"]]
    assert names == ["alpha", "beta"]
    # Paths are stored relative to the workspace root.
    assert {p["path"] for p in manifest["projects"]} == {"alpha", "beta"}


def test_workspace_onboard_rejects_duplicate(tmp_path, monkeypatch, cli_runner):
    ws = tmp_path / "ws"
    ws.mkdir()
    _project(ws / "alpha")
    monkeypatch.chdir(ws)

    assert cli_runner.invoke(app, ["workspace", "onboard", "alpha"]).exit_code == 0
    again = cli_runner.invoke(app, ["workspace", "onboard", "alpha"])
    assert again.exit_code == 0
    assert "already registered" in again.output


def test_workspace_onboard_missing_dir_errors(tmp_path, monkeypatch, cli_runner):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    result = cli_runner.invoke(app, ["workspace", "onboard", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_workspace_list_multi_after_onboard(tmp_path, monkeypatch, cli_runner):
    ws = tmp_path / "ws"
    ws.mkdir()
    _project(ws / "alpha")
    _project(ws / "beta")
    monkeypatch.chdir(ws)
    cli_runner.invoke(app, ["workspace", "onboard", "alpha"])
    cli_runner.invoke(app, ["workspace", "onboard", "beta"])

    result = cli_runner.invoke(app, ["workspace", "list"])
    assert result.exit_code == 0
    assert "multi-project" in result.output
    assert "alpha" in result.output and "beta" in result.output
