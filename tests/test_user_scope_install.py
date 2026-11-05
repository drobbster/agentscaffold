"""``scaffold agents install --scope user``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agentscaffold.agents import user_scope
from agentscaffold.agents.user_scope import (
    Locations,
    UserScopeError,
    install_user_scope,
    is_agentscaffold_hook_command,
    plugin_slug,
    uninstall_user_scope,
)
from agentscaffold.hooks.generators.cursor import INDEX_HOOK_REL_PATH, render_index_hook_script
from agentscaffold.workspace_registry import register_workspace

HOOK = "/opt/venv/bin/scaffold-hook"


def _project(root: Path, *, manual: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text("agents:\n  agents_md: true\n")
    if manual:
        (root / "AGENTS.md").write_text("# Agent Operating Rules\n")
    return root.resolve()


@pytest.fixture()
def loc(tmp_path: Path, isolate_agentscaffold_home: Path) -> Locations:
    locations = Locations(
        home=isolate_agentscaffold_home,
        cursor_home=tmp_path / "dot-cursor",
        claude_home=tmp_path / "dot-claude",
    )
    locations.cursor_home.mkdir()
    locations.claude_home.mkdir()
    return locations


@pytest.fixture()
def projects(tmp_path: Path) -> dict[str, Path]:
    alpha = _project(tmp_path / "repos" / "alpha")
    beta = _project(tmp_path / "repos" / "beta", manual=False)
    register_workspace(alpha, name="alpha")
    register_workspace(beta, name="beta")
    return {"alpha": alpha, "beta": beta}


def _install(loc: Locations, **kwargs: Any) -> user_scope.InstallReport:
    return install_user_scope(hook_command=HOOK, locations=loc, **kwargs)


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _commands(document: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for bucket in (document.get("hooks") or {}).values():
        for entry in bucket:
            if "command" in entry:
                found.append(entry["command"])
            for inner in entry.get("hooks", []):
                found.append(inner["command"])
    return found


def test_install_writes_plugins_context_hooks_and_manifest(
    loc: Locations, projects: dict[str, Path]
) -> None:
    report = _install(loc)
    assert report.notes == []

    shared = loc.plugins_dir / user_scope.SHARED_PLUGIN_NAME
    assert _json(shared / ".cursor-plugin" / "plugin.json")["name"] == "agentscaffold-routing"
    shared_rule = (shared / "rules" / user_scope.SHARED_RULE_NAME).read_text()
    assert "alwaysApply: true" in shared_rule
    assert "scaffold_session_start" in shared_rule

    pointer = (
        loc.plugins_dir / plugin_slug("alpha") / "rules" / user_scope.POINTER_RULE_NAME
    ).read_text()
    assert str(projects["alpha"]) in pointer
    assert "working_path" in pointer
    assert str(projects["alpha"] / "AGENTS.md") in pointer
    beta_context = (loc.claude_context_dir / f"{plugin_slug('beta')}.md").read_text()
    assert "No governance manual was found" in beta_context

    cursor = _json(loc.client_settings("cursor"))
    assert cursor["version"] == 1
    assert cursor["hooks"]["workspaceOpen"] == [{"command": f"{HOOK} cursor-workspace-open"}]
    assert cursor["hooks"]["afterFileEdit"] == [{"command": f"{HOOK} cursor-after-edit"}]
    assert cursor["hooks"]["preToolUse"] == [
        {"command": f"{HOOK} cursor-pre-edit", "matcher": "Write"}
    ]
    claude = _json(loc.client_settings("claude"))
    assert set(claude["hooks"]) == {"SessionStart", "PostToolUse", "PreToolUse"}
    assert claude["hooks"]["PreToolUse"][0]["matcher"] == user_scope.CLAUDE_EDIT_MATCHER

    manifest = _json(loc.manifest)
    assert manifest["cursor_plugins"]["shared"] == str(shared)
    assert set(manifest["cursor_plugins"]["projects"]) == {"alpha", "beta"}
    assert set(manifest["claude_context"]) == {"alpha", "beta"}
    assert all(len(sha) == 64 for sha in manifest["files"].values())


def test_plugins_ship_no_mcp_server(loc: Locations, projects: dict[str, Path]) -> None:
    _install(loc)
    assert not list(loc.plugins_dir.rglob("mcp.json"))


def test_install_is_idempotent(loc: Locations, projects: dict[str, Path]) -> None:
    _install(loc)
    again = _install(loc)
    assert again.written == [] and again.merged == [] and again.backups == []
    assert len(_commands(_json(loc.client_settings("cursor")))) == 3


def test_dry_run_writes_nothing(loc: Locations, projects: dict[str, Path]) -> None:
    report = _install(loc, dry_run=True)
    assert report.written and report.merged
    assert not loc.plugins_dir.exists()
    assert not loc.client_settings("cursor").exists()
    assert not loc.manifest.exists()


def test_merge_keeps_other_tools_entries_and_backs_up(
    loc: Locations, projects: dict[str, Path]
) -> None:
    foreign = {
        "version": 1,
        "hooks": {
            "afterFileEdit": [{"command": "./other-tool.sh"}],
            "stop": [{"command": "notify-send done"}],
        },
    }
    loc.client_settings("cursor").write_text(json.dumps(foreign))
    claude_foreign = {
        "model": "x",
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh"}]}
            ]
        },
    }
    loc.client_settings("claude").write_text(json.dumps(claude_foreign))

    report = _install(loc)

    cursor = _json(loc.client_settings("cursor"))
    assert {"command": "./other-tool.sh"} in cursor["hooks"]["afterFileEdit"]
    assert cursor["hooks"]["stop"] == [{"command": "notify-send done"}]
    claude = _json(loc.client_settings("claude"))
    assert claude["model"] == "x"
    assert "guard.sh" in _commands(claude)
    assert len(report.backups) == 2
    assert _json(report.backups[0]) in (foreign, claude_foreign)


def test_reinstall_from_another_interpreter_replaces_old_entries(
    loc: Locations, projects: dict[str, Path]
) -> None:
    _install(loc)
    install_user_scope(hook_command="/new/venv/bin/scaffold hook", locations=loc)
    commands = _commands(_json(loc.client_settings("cursor")))
    assert len(commands) == 3
    assert all(c.startswith("/new/venv/bin/scaffold hook ") for c in commands)


@pytest.mark.parametrize(
    ("command", "owned"),
    [
        (f"{HOOK} cursor-after-edit", True),
        ("'/path with space/scaffold' hook cursor-pre-edit", True),
        ("scaffold-hook cursor-after-edit --extra", False),
        ("other-tool cursor-after-edit", False),
        ("scaffold index --incremental", False),
        (None, False),
    ],
)
def test_ownership_of_hook_commands(command: Any, owned: bool) -> None:
    assert is_agentscaffold_hook_command(command) is owned


def test_unparseable_settings_are_refused_before_any_write(
    loc: Locations, projects: dict[str, Path]
) -> None:
    loc.client_settings("claude").write_text("{ not json")
    with pytest.raises(UserScopeError, match="not valid JSON"):
        _install(loc)
    assert not loc.plugins_dir.exists()
    assert not loc.client_settings("cursor").exists()
    assert loc.client_settings("claude").read_text() == "{ not json"


def test_client_and_component_selection(loc: Locations, projects: dict[str, Path]) -> None:
    _install(loc, clients=["cursor"], components=["hooks"])
    assert not loc.plugins_dir.exists()
    assert not loc.client_settings("claude").exists()
    assert set(_json(loc.client_settings("cursor"))["hooks"]) == {"afterFileEdit", "preToolUse"}


def test_detects_clients_from_their_home_directories(
    loc: Locations, projects: dict[str, Path]
) -> None:
    loc.claude_home.rmdir()
    _install(loc)
    assert loc.client_settings("cursor").exists()
    assert not loc.claude_home.exists()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"components": ["bogus"]}, "Unknown component"),
        ({"clients": ["vim"]}, "Unknown client"),
        ({"projects": ["gamma"]}, "Not registered: gamma"),
    ],
)
def test_bad_arguments_are_refused(
    loc: Locations, projects: dict[str, Path], kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(UserScopeError, match=message):
        _install(loc, **kwargs)


def test_no_registered_projects_is_an_error(loc: Locations) -> None:
    with pytest.raises(UserScopeError, match="No registered projects"):
        _install(loc)


def test_uninstall_everything_restores_shared_files(
    loc: Locations, projects: dict[str, Path]
) -> None:
    loc.client_settings("claude").write_text(json.dumps({"model": "x"}))
    _install(loc)

    report = uninstall_user_scope(locations=loc)

    assert not loc.plugins_dir.exists()
    assert not loc.claude_context_dir.exists()
    assert not loc.manifest.exists()
    # Created by the install and now empty: removed. Pre-existing: restored.
    assert not loc.client_settings("cursor").exists()
    assert _json(loc.client_settings("claude")) == {"model": "x"}
    assert loc.client_settings("cursor") in report.removed


def test_uninstall_keeps_a_created_file_that_others_have_since_used(
    loc: Locations, projects: dict[str, Path]
) -> None:
    _install(loc, clients=["cursor"])
    settings = loc.client_settings("cursor")
    document = _json(settings)
    document["hooks"]["stop"] = [{"command": "notify-send done"}]
    settings.write_text(json.dumps(document))

    uninstall_user_scope(locations=loc)

    assert _json(settings) == {"version": 1, "hooks": {"stop": [{"command": "notify-send done"}]}}


def test_uninstall_one_project_keeps_the_rest(loc: Locations, projects: dict[str, Path]) -> None:
    _install(loc)
    uninstall_user_scope(projects=["beta"], locations=loc)

    assert not (loc.plugins_dir / plugin_slug("beta")).exists()
    assert (loc.plugins_dir / plugin_slug("alpha")).is_dir()
    assert (loc.plugins_dir / user_scope.SHARED_PLUGIN_NAME).is_dir()
    manifest = _json(loc.manifest)
    assert set(manifest["cursor_plugins"]["projects"]) == {"alpha"}
    assert len(_commands(_json(loc.client_settings("cursor")))) == 3


def test_uninstall_without_manifest_is_a_no_op(loc: Locations) -> None:
    report = uninstall_user_scope(locations=loc)
    assert report.removed == [] and "Nothing to remove" in report.notes[0]


def test_legacy_project_hook_is_reported(loc: Locations, projects: dict[str, Path]) -> None:
    legacy = projects["alpha"] / INDEX_HOOK_REL_PATH
    legacy.parent.mkdir(parents=True)
    legacy.write_text('#!/usr/bin/env bash\nscaffold_bin="scaffold"\n')
    shim = projects["beta"] / INDEX_HOOK_REL_PATH
    shim.parent.mkdir(parents=True)
    shim.write_text(render_index_hook_script(HOOK))

    notes = _install(loc).notes

    assert len(notes) == 1 and str(legacy) in notes[0]


def test_plugin_slugs_are_kebab_case_and_distinct() -> None:
    assert plugin_slug("alpha") == "agentscaffold-alpha"
    folded = {plugin_slug(n) for n in ("My_App", "my-app", "my.app")}
    assert len(folded) == 3
    assert all(s == s.lower() and "_" not in s and "." not in s for s in folded)


@pytest.mark.skipif(os.name == "nt", reason="HOME override is POSIX-only")
def test_cli_user_scope_install_and_uninstall(
    tmp_path: Path,
    projects: dict[str, Path],
    cli_runner: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentscaffold.cli import app

    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    dry = cli_runner.invoke(app, ["agents", "install", "--scope", "user", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "Would write" in dry.output
    assert not (home / ".cursor" / "hooks.json").exists()

    done = cli_runner.invoke(app, ["agents", "install", "--scope", "user"])
    assert done.exit_code == 0, done.output
    assert (home / ".cursor" / "hooks.json").is_file()
    assert not (home / ".claude").exists()

    gone = cli_runner.invoke(app, ["agents", "install", "--scope", "user", "--uninstall"])
    assert gone.exit_code == 0, gone.output
    assert not (home / ".cursor" / "hooks.json").exists()

    bad = cli_runner.invoke(app, ["agents", "install", "--uninstall"])
    assert bad.exit_code == 2
