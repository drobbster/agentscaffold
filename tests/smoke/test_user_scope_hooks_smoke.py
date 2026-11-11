"""End-to-end smoke for user-scope install and the routed edit hook.

Driven through the installed console scripts, as an editor would: install
writes a user-level ``hooks.json``; running the command it registered, from the
editor's configuration directory, must answer at once and leave a detached
worker to index the project that owns the edited file -- a project nested below
its repository root, which project-level hooks cannot reach.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCAFFOLD = Path(sys.executable).parent / "scaffold"
SCAFFOLD_HOOK = Path(sys.executable).parent / "scaffold-hook"

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.name == "nt" or not (SCAFFOLD.exists() and SCAFFOLD_HOOK.exists()),
        reason="needs the scaffold and scaffold-hook console scripts on a POSIX host",
    ),
]


def _scaffold(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCAFFOLD), *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=300
    )


def _hook(command: str, payload: dict, *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        command,
        shell=True,  # noqa: S602 - the command line the install wrote, run as the editor does
        input=json.dumps(payload),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_user_scope_hook_indexes_a_nested_project(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    scaffold_home = tmp_path / "agentscaffold-home"
    scaffold_home.mkdir()
    # The graph's state directory derives from HOME, so this process and the
    # scripts it runs must agree on it.
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(scaffold_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("SCAFFOLD_HOOK_DISABLE", raising=False)
    env = dict(os.environ)

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    project = repo / "services" / "api"
    (project / "src").mkdir(parents=True)
    (project / "scaffold.yaml").write_text("agents:\n  agents_md: false\n")
    (project / "src" / "app.py").write_text("def handler():\n    return 1\n")
    project = project.resolve()

    registered = _scaffold(
        "project", "register", str(project), "--name", "api", cwd=project, env=env
    )
    assert registered.returncode == 0, registered.stderr

    installed = _scaffold(
        "agents", "install", "--scope", "user", "--client", "cursor", cwd=project, env=env
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    hooks = json.loads((home / ".cursor" / "hooks.json").read_text())["hooks"]

    opened = _hook(
        hooks["workspaceOpen"][0]["command"],
        {"workspace_roots": [str(repo)]},
        cwd=home / ".cursor",
        env=env,
    )
    plugin_paths = json.loads(opened)["pluginPaths"]
    assert len(plugin_paths) == 2 and all(Path(p).is_dir() for p in plugin_paths)

    started = time.monotonic()
    answered = _hook(
        hooks["afterFileEdit"][0]["command"],
        {"file_path": str(project / "src" / "app.py")},
        cwd=home / ".cursor",
        env=env,
    )
    assert json.loads(answered) == {}
    assert time.monotonic() - started < 5

    from agentscaffold.hooks.worker import INDEX_LAST_SUCCESS, project_state, read_last_run

    state_dir, _ = project_state(project)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and not (state_dir / INDEX_LAST_SUCCESS).is_file():
        time.sleep(0.5)
    assert (state_dir / INDEX_LAST_SUCCESS).is_file(), "the detached worker never indexed"
    assert read_last_run(state_dir)["event"] == "cursor-after-edit"

    doctor = _scaffold("doctor", "--project-root", str(project), cwd=project, env=env)
    assert "covers project api" in doctor.stdout, doctor.stdout

    removed = _scaffold("agents", "install", "--scope", "user", "--uninstall", cwd=project, env=env)
    assert removed.returncode == 0, removed.stderr
    assert not (home / ".cursor" / "hooks.json").exists()


def test_mcp_install_dry_run_registers_claude_without_writing(tmp_path: Path, monkeypatch) -> None:
    """A fake claude on PATH is probed and not asked to mutate."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'No MCP server named \"agentscaffold\".'\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    env = dict(os.environ)

    result = _scaffold("mcp", "install", "--client", "claude", "--dry-run", cwd=tmp_path, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "claude mcp add --scope user" in result.stdout
    assert not (home / ".claude.json").exists()
