"""Health checks for every failure mode of the shared-workspace layout.

`scaffold doctor` exists because the move to a shared workspace changed several
things that used to be obvious: the MCP server is now one entry instead of one per
project, the graph lives outside the tree, and the routing guidance is generated
from a canonical source. Each of those is fine when it works and invisible when it does not,
which is the definition of a thing that needs a diagnostic.

Every check gets a seeded fault here, because a health check that has never been
seen to fail is not known to work -- it is only known to be silent, and silence
is exactly what it would produce if it were broken.

Two properties hold across all of them. Doctor is **read-only**: running it must
not change a byte, including the state directory it reports on. And the exit code
is **opt-in**: the default always exits 0 so it is safe in a shell profile or a
git hook, while `--strict` is the CI gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_client_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real ``~/.cursor/mcp.json`` out of these results.

    Several tests assert a clean run, and the machine running them very likely
    has legacy per-project entries -- that is the situation this plan exists to
    fix. Reading them would make the suite report on the developer's laptop
    instead of on the fixture.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("agentscaffold.doctor.path_scaffold", lambda: None)


@pytest.fixture
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    monkeypatch.delenv("AGENTSCAFFOLD_DB_PATH", raising=False)
    return home


def _snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _project(root: Path, name: str = "proj", *, manual: bool = True) -> Path:
    """A project as ``scaffold init`` leaves it: config plus the shipped manual."""
    from agentscaffold.agents.manual_diff import render_governance_manual
    from agentscaffold.config import ScaffoldConfig

    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scaffold.yaml").write_text(f"framework:\n  project_name: {name}\n")
    if manual:
        (directory / "AGENTS.md").write_text(render_governance_manual(ScaffoldConfig()))
    return directory


def _register(root: Path, projects: list[tuple[str, str]] | None = None) -> str:
    from agentscaffold.workspace_registry import load_registry, register_workspace

    register_workspace(root, projects=projects)
    entry = load_registry().find_workspace_by_root(root)
    assert entry is not None
    return entry.id


def _run(cli_runner: CliRunner, *args: str):
    return cli_runner.invoke(app, ["doctor", *args])


def _mcp_config(path: Path, servers: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}, indent=2))
    return path


# ---------------------------------------------------------------------------
# The framework itself
# ---------------------------------------------------------------------------


def test_a_healthy_workspace_reports_no_problems(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    _register(project)

    result = _run(cli_runner, "--project-root", str(project))

    assert result.exit_code == 0
    assert "fail" not in result.output.lower()


def test_doctor_writes_nothing(state_home: Path, tmp_path: Path, cli_runner: CliRunner):
    """Read-only is a property users rely on to run it when things are broken."""
    project = _project(tmp_path)
    _register(project)
    before = _snapshot(tmp_path)

    _run(cli_runner, "--project-root", str(project))

    assert _snapshot(tmp_path) == before


def test_checks_are_registered_rather_than_hardcoded(state_home: Path):
    """New checks are added by registration, without reworking this."""
    from agentscaffold.doctor import CHECKS

    names = [check.name for check in CHECKS]
    assert len(names) == len(set(names)), "check names must be unique"
    assert {
        "registry",
        "guidance",
        "guidance_ignored",
        "mcp_registration",
        "version_skew",
        "state_location",
    } <= set(names)


def test_strict_exits_non_zero_when_something_is_wrong(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    _register(project)
    (tmp_path / "gone").mkdir()
    _register(tmp_path / "gone")
    (tmp_path / "gone").rmdir()

    result = _run(cli_runner, "--project-root", str(project), "--strict")

    assert result.exit_code != 0


def test_the_default_exit_code_is_always_zero(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """Safe to put in a shell profile or a hook; --strict is the CI gate."""
    project = _project(tmp_path)
    _register(project)
    (tmp_path / "gone").mkdir()
    _register(tmp_path / "gone")
    (tmp_path / "gone").rmdir()

    result = _run(cli_runner, "--project-root", str(project))

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Registry health
# ---------------------------------------------------------------------------


def test_registry_check_flags_a_root_that_no_longer_exists(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    _register(project)
    vanished = tmp_path / "vanished"
    vanished.mkdir()
    _register(vanished)
    vanished.rmdir()

    result = _run(cli_runner, "--project-root", str(project))

    assert "vanished" in result.output


def test_registry_check_passes_when_every_root_is_present(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    _register(project)

    result = _run(cli_runner, "--project-root", str(project), "--strict")

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Guidance drift
# ---------------------------------------------------------------------------


def _shared_workspace(root: Path) -> Path:
    """A two-project shared workspace, which is what has canonical guidance."""
    for name in ("alpha", "beta"):
        _project(root, name)
    (root / "workspace.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "ws-aaaaaaaaaaaa",
                "projects": [
                    {"name": "alpha", "path": "alpha"},
                    {"name": "beta", "path": "beta"},
                ],
                "asset_layout": {"layout": "shared_workspace"},
            },
            sort_keys=False,
        )
    )
    return root


def test_guidance_check_flags_copies_left_behind_by_an_edited_canonical(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    from agentscaffold.agents.generate import run_agents_generate_all_platforms
    from agentscaffold.config import load_config
    from agentscaffold.rendering import canonical_guidance_path

    workspace = _shared_workspace(tmp_path)
    alpha = workspace / "alpha"
    run_agents_generate_all_platforms(load_config(alpha / "scaffold.yaml"), alpha)

    canonical = canonical_guidance_path(alpha)
    assert canonical is not None
    canonical.write_text(canonical.read_text() + "\nAn edit nobody regenerated.\n")

    result = _run(cli_runner, "--project-root", str(alpha))

    assert "stale" in result.output.lower()


def test_guidance_check_is_quiet_for_a_lone_repo(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """A lone repo has no canonical file by design, which is not a fault."""
    project = _project(tmp_path)
    _register(project)

    result = _run(cli_runner, "--project-root", str(project), "--strict")

    assert result.exit_code == 0
    assert "single-project" not in result.output.lower()


def test_a_legacy_multi_project_workspace_is_not_called_a_lone_repo(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """Observed on a real workspace: no canonical file has two causes, not one.

    A workspace predating shared assets also has no canonical guidance, and
    reporting it as a single-project repo tells the user something false about
    the shape of their workspace while it is being diagnosed.
    """
    workspace = _shared_workspace(tmp_path)
    manifest = yaml.safe_load((workspace / "workspace.yaml").read_text())
    del manifest["asset_layout"]
    (workspace / "workspace.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    _register(workspace, projects=[("alpha", "alpha"), ("beta", "beta")])

    result = _run(cli_runner, "--project-root", str(workspace / "alpha"))

    assert "single-project" not in result.output.lower()


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def test_mcp_check_flags_legacy_per_project_entries(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json",
        {
            "agentscaffold": {"command": "scaffold", "args": ["mcp"]},
            "agentscaffold-legacy": {"command": "scaffold", "args": ["mcp"]},
        },
    )

    result = _run(cli_runner, "--project-root", str(project), "--mcp-config", str(config))

    assert "agentscaffold-legacy" in result.output


def test_mcp_check_flags_a_cd_bound_entry(state_home: Path, tmp_path: Path, cli_runner: CliRunner):
    """A `cd` binding is what forced one server per project."""
    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json",
        {
            "agentscaffold": {
                "command": "sh",
                "args": ["-c", "cd /some/project && scaffold mcp"],
            }
        },
    )

    result = _run(cli_runner, "--project-root", str(project), "--mcp-config", str(config))

    assert "cd" in result.output.lower()


def test_mcp_check_flags_a_hardcoded_interpreter_path(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """The mechanism that let the recorded version skew persist unnoticed."""
    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json",
        {"agentscaffold": {"command": "/Users/someone/venv/bin/python", "args": ["-m", "x"]}},
    )

    result = _run(cli_runner, "--project-root", str(project), "--mcp-config", str(config))

    assert "interpreter" in result.output.lower() or "hardcoded" in result.output.lower()


def test_cursor_ok_does_not_hide_a_missing_claude_server(
    tmp_path: Path, isolate_agentscaffold_home: Path, monkeypatch: pytest.MonkeyPatch
):
    from agentscaffold.doctor import DoctorContext, check_mcp_registration
    from agentscaffold.mcp import claude_register

    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json",
        {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}},
    )
    (isolate_agentscaffold_home / "user-install.json").write_text(
        '{"clients": ["claude", "cursor"]}\n', encoding="utf-8"
    )
    monkeypatch.setattr(claude_register, "claude_binary", lambda: (tmp_path / "claude", ""))

    def runner(argv, cwd):
        return 0, 'No MCP server named "agentscaffold".\n'

    monkeypatch.setattr(claude_register, "_default_runner", runner)

    result = check_mcp_registration(DoctorContext(project, config))

    assert result.status == "fail"
    assert "One canonical entry" in result.summary
    assert "no server is registered" in result.summary
    assert result.remediation is not None and "--client claude" in result.remediation


def test_higher_precedence_claude_scope_is_a_warning(
    tmp_path: Path, isolate_agentscaffold_home: Path, monkeypatch: pytest.MonkeyPatch
):
    from agentscaffold.doctor import DoctorContext, check_mcp_registration
    from agentscaffold.mcp import claude_register

    project = _project(tmp_path).resolve()
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json",
        {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}},
    )
    (isolate_agentscaffold_home / "user-install.json").write_text(
        '{"clients": ["claude"]}\n', encoding="utf-8"
    )
    monkeypatch.setattr(claude_register, "claude_binary", lambda: (tmp_path / "claude", ""))

    def runner(argv, cwd):
        if Path(cwd).resolve() == project:
            return 0, "Scope: Local config\nStatus: Connected\nCommand: node\nArgs: other.js\n"
        return 0, "Scope: User config\nStatus: Connected\nCommand: scaffold\nArgs: mcp\n"

    monkeypatch.setattr(claude_register, "_default_runner", runner)
    result = check_mcp_registration(DoctorContext(project, config))

    assert result.status == "warn"
    assert any(str(project) in line for line in result.details)


def test_claude_permission_drift_warns(isolate_agentscaffold_home: Path, tmp_path: Path):
    from agentscaffold.doctor import DoctorContext, check_claude_permission_rules

    (isolate_agentscaffold_home / "user-install.json").write_text(
        '{"claude_permission_rules": ["mcp__agentscaffold__gone"]}\n', encoding="utf-8"
    )

    result = check_claude_permission_rules(DoctorContext(tmp_path, tmp_path / "mcp.json"))

    assert result.status == "warn"
    assert result.remediation is not None
    assert "scaffold agents install --scope user" in result.remediation


def test_project_claude_hooks_beside_user_scope_warn(
    tmp_path: Path, isolate_agentscaffold_home: Path
):
    from agentscaffold.doctor import DoctorContext, check_claude_hook_overlap

    project = _project(tmp_path)
    _register(project)
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        '{"hooks": {"SessionStart": [{"hooks": [{"command": "scaffold orient"}]}]}}\n',
        encoding="utf-8",
    )
    (isolate_agentscaffold_home / "user-install.json").write_text(
        '{"clients": ["claude"]}\n', encoding="utf-8"
    )

    result = check_claude_hook_overlap(DoctorContext(project, tmp_path / "mcp.json"))

    assert result.status == "warn"
    assert "both" in result.summary
    assert str(settings) in result.details


def test_mcp_check_skips_when_there_is_no_config(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """Not having Cursor installed is not a fault in the user's setup."""
    project = _project(tmp_path)
    _register(project)

    result = _run(
        cli_runner,
        "--project-root",
        str(project),
        "--mcp-config",
        str(tmp_path / "absent.json"),
        "--strict",
    )

    assert result.exit_code == 0


def test_mcp_check_accepts_the_canonical_entry(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    import agentscaffold.doctor as doctor
    from agentscaffold import __version__

    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json", {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}}
    )
    # A config with an entry also gives the skew check something to probe, and
    # `scaffold` need not be on the PATH of whoever runs the suite. Pinned so
    # this test fails only for the reason it is named after.
    monkeypatch.setattr(doctor, "probe_launched_version", lambda command: __version__)

    result = _run(
        cli_runner, "--project-root", str(project), "--mcp-config", str(config), "--strict"
    )

    assert result.exit_code == 0


def test_doctor_warns_when_path_scaffold_is_an_older_pin(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """`uv tool upgrade` does not move an install pinned with ==."""
    import agentscaffold.doctor as doctor

    project = _project(tmp_path)
    _register(project)
    monkeypatch.setattr(doctor, "path_scaffold", lambda: "/opt/old/scaffold")
    monkeypatch.setattr(doctor, "probe_launched_version", lambda command: "0.12.0")

    result = _run(cli_runner, "--project-root", str(project), "--strict")

    assert result.exit_code != 0
    assert "0.12.0" in result.output
    assert "uv tool install -U" in result.output


def test_doctor_warns_when_the_edit_hook_is_the_old_shell_script(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """A generated shell hook keeps the scaffold path from the day it was written."""
    project = _project(tmp_path)
    _register(project)
    script = project / ".cursor" / "hooks" / "scaffold-index.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nscaffold_bin=/opt/old/bin/scaffold\n")

    result = _run(cli_runner, "--project-root", str(project), "--strict")

    assert result.exit_code != 0
    assert "pre-router" in result.output
    assert "scaffold agents hooks" in result.output


def test_mcp_check_flags_a_stray_per_project_config(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """A clean shared config says nothing about per-project files.

    Clients load both. A `.cursor/mcp.json` in a registered root is a second,
    project-scoped server -- exactly what the 0.10 migration collapses. Reporting
    the migration as clean while one sits on disk made the regression invisible
    to the command whose job is to verify it.
    """
    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json", {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}}
    )
    _mcp_config(
        project / ".cursor" / "mcp.json",
        {"agentscaffold": {"command": "scaffold", "args": ["mcp", "--project", "proj"]}},
    )

    result = _run(cli_runner, "--project-root", str(project), "--mcp-config", str(config))

    assert ".cursor/mcp.json" in result.output.replace("\\", "/")
    assert "warn" in result.output.lower()


def test_mcp_check_does_not_flag_a_per_project_config_without_a_shared_server(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """Redundant only if there is a shared server to be redundant with.

    A lone repo whose per-project config is its *only* registration is not
    misconfigured. Flagging it would be crying wolf, and the missing shared entry
    is already reported on its own.
    """
    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(tmp_path / "mcp.json", {"unrelated": {"command": "other"}})
    _mcp_config(
        project / ".cursor" / "mcp.json",
        {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}},
    )

    result = _run(cli_runner, "--project-root", str(project), "--mcp-config", str(config))

    assert ".cursor/mcp.json" not in result.output.replace("\\", "/")


def test_mcp_check_ignores_a_per_project_config_without_an_agentscaffold_entry(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """Only *our* entries are ours to complain about.

    Plenty of repos keep a `.cursor/mcp.json` for unrelated servers. Flagging
    those would make the check noise, and noise is what stops it being read.
    """
    import agentscaffold.doctor as doctor
    from agentscaffold import __version__

    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json", {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}}
    )
    _mcp_config(project / ".cursor" / "mcp.json", {"some-other-server": {"command": "other"}})
    monkeypatch.setattr(doctor, "probe_launched_version", lambda command: __version__)

    result = _run(
        cli_runner, "--project-root", str(project), "--mcp-config", str(config), "--strict"
    )

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Version skew -- the failure this command was specified to catch
# ---------------------------------------------------------------------------


def test_version_skew_is_reported_when_the_server_runs_an_older_install(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """The blocker in workflow_state.md, in miniature.

    An MCP entry launching an interpreter with an older agentscaffold answers
    tool calls with a surface the current CLI does not have, and nothing in the
    normal flow says so.
    """
    import agentscaffold.doctor as doctor

    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json", {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}}
    )
    monkeypatch.setattr(doctor, "probe_launched_version", lambda command: "0.8.1")

    result = _run(cli_runner, "--project-root", str(project), "--mcp-config", str(config))

    assert "0.8.1" in result.output


def test_no_skew_reported_when_the_versions_agree(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    import agentscaffold.doctor as doctor
    from agentscaffold import __version__

    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json", {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}}
    )
    monkeypatch.setattr(doctor, "probe_launched_version", lambda command: __version__)

    result = _run(
        cli_runner, "--project-root", str(project), "--mcp-config", str(config), "--strict"
    )

    assert result.exit_code == 0


def test_an_unprobeable_command_warns_instead_of_crashing(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """A diagnostic that dies on a broken system is useless exactly when needed."""
    import agentscaffold.doctor as doctor

    project = _project(tmp_path)
    _register(project)
    config = _mcp_config(
        tmp_path / "mcp.json", {"agentscaffold": {"command": "scaffold", "args": ["mcp"]}}
    )
    monkeypatch.setattr(doctor, "probe_launched_version", lambda command: None)

    result = _run(cli_runner, "--project-root", str(project), "--mcp-config", str(config))

    assert result.exit_code == 0
    assert "could not" in result.output.lower() or "unknown" in result.output.lower()


# ---------------------------------------------------------------------------
# The probe itself, unmocked
# ---------------------------------------------------------------------------
#
# Every check above replaces the probe, so without these it would never have run
# at all -- and when it was first run against a real install it returned None for
# `scaffold`, the one entry the whole plan is about.


def test_the_probe_reads_a_console_script_shebang(tmp_path: Path):
    """How this works against an install too old to have `--version`.

    The versions worth catching predate the flag, so asking the script is
    circular. Its shebang names the interpreter, and the interpreter can always
    be asked what it has installed.
    """
    import sys

    from agentscaffold import __version__
    from agentscaffold.doctor import probe_launched_version

    script = tmp_path / "scaffold"
    script.write_text(f"#!{sys.executable}\nraise SystemExit('never runs')\n")
    script.chmod(0o755)

    assert probe_launched_version(str(script)) == __version__


def test_the_probe_reads_an_env_style_shebang(tmp_path: Path):
    import sys

    from agentscaffold import __version__
    from agentscaffold.doctor import probe_launched_version

    script = tmp_path / "scaffold"
    script.write_text(f"#!/usr/bin/env {sys.executable}\n")
    script.chmod(0o755)

    assert probe_launched_version(str(script)) == __version__


def test_the_probe_asks_an_interpreter_directly(tmp_path: Path):
    import sys

    from agentscaffold import __version__
    from agentscaffold.doctor import probe_launched_version

    assert probe_launched_version(sys.executable) == __version__


def test_the_cli_answers_version(cli_runner: CliRunner):
    """The fallback for a native launcher with no shebang to read."""
    from agentscaffold import __version__

    result = cli_runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_the_probe_returns_none_for_things_that_are_not_ours(tmp_path: Path):
    from agentscaffold.doctor import probe_launched_version

    assert probe_launched_version(str(tmp_path / "absent")) is None
    assert probe_launched_version("/bin/echo") is None


# ---------------------------------------------------------------------------
# State location
# ---------------------------------------------------------------------------


def test_state_check_reports_where_the_graph_actually_resolves(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    workspace_id = _register(project)

    result = _run(cli_runner, "--project-root", str(project))

    assert workspace_id in result.output


def test_a_long_path_is_printed_whole(state_home: Path, tmp_path: Path, cli_runner: CliRunner):
    """A path broken across lines cannot be pasted, which is its only use here."""
    from agentscaffold.paths import resolve_db_path

    project = _project(tmp_path, "a-project-with-a-deliberately-long-name-for-wrapping")
    _register(project)

    result = _run(cli_runner, "--project-root", str(project))

    assert str(resolve_db_path(None, project)) in result.output


def test_state_check_flags_an_orphaned_in_tree_directory(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """A leftover .scaffold/ after migration is a graph nobody reads any more."""
    from agentscaffold.paths import ensure_workspace_state_dir

    project = _project(tmp_path)
    workspace_id = _register(project)
    ensure_workspace_state_dir(workspace_id).joinpath("graph.duckdb").write_bytes(b"live")
    (project / ".scaffold").mkdir()
    (project / ".scaffold" / "graph.duckdb").write_bytes(b"orphan")

    result = _run(cli_runner, "--project-root", str(project))

    assert ".scaffold" in result.output


def test_state_check_flags_an_orphan_inside_a_project_folder(state_home: Path, tmp_path: Path):
    """A team folder's old .scaffold/ outlives the move to the state dir."""
    from agentscaffold.doctor import DoctorContext, check_state_location
    from agentscaffold.paths import ensure_workspace_state_dir

    workspace = _shared_workspace(tmp_path)
    workspace_id = _register(workspace, projects=[("alpha", "alpha"), ("beta", "beta")])
    ensure_workspace_state_dir(workspace_id).joinpath("graph.duckdb").write_bytes(b"live")
    (workspace / "beta" / ".scaffold").mkdir()
    (workspace / "beta" / ".scaffold" / "graph.duckdb").write_bytes(b"orphan")

    result = check_state_location(
        DoctorContext(project_root=workspace / "alpha", mcp_config_path=tmp_path / "mcp.json")
    )

    assert result.status == "warn"
    assert any(str(workspace / "beta" / ".scaffold") in detail for detail in result.details)


def test_state_check_quiet_when_the_in_tree_graph_is_the_live_one(state_home: Path, tmp_path: Path):
    """An unregistered repo keeps its graph in-tree; that is not an orphan."""
    from agentscaffold.doctor import DoctorContext, check_state_location

    project = _project(tmp_path)
    (project / ".scaffold").mkdir()
    (project / ".scaffold" / "graph.duckdb").write_bytes(b"live")

    result = check_state_location(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )

    assert result.status == "ok"


def _graph_with_session_rows(db: Path, projects: list[str]) -> None:
    import duckdb

    db.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE Session (id VARCHAR PRIMARY KEY, project VARCHAR DEFAULT '')")
    for number, project in enumerate(projects):
        conn.execute("INSERT INTO Session VALUES (?, ?)", [f"session::{number}", project])
    conn.close()


def test_unstamped_rows_counted_in_a_multi_project_workspace(state_home: Path, tmp_path: Path):
    from agentscaffold.doctor import DoctorContext, check_unstamped_rows
    from agentscaffold.paths import resolve_db_path

    workspace = _shared_workspace(tmp_path)
    _register(workspace, projects=[("alpha", "alpha"), ("beta", "beta")])
    _graph_with_session_rows(resolve_db_path(None, workspace / "alpha"), ["", "", "alpha"])

    result = check_unstamped_rows(
        DoctorContext(project_root=workspace / "alpha", mcp_config_path=tmp_path / "mcp.json")
    )

    assert result.status == "warn"
    assert any("Session: 2" in detail for detail in result.details)


def test_unstamped_rows_silent_in_a_single_project_repo(state_home: Path, tmp_path: Path):
    """An empty project is the designed value in a single-project repo."""
    from agentscaffold.doctor import DoctorContext, check_unstamped_rows
    from agentscaffold.paths import resolve_db_path

    project = _project(tmp_path)
    _register(project)
    _graph_with_session_rows(resolve_db_path(None, project), ["", ""])

    result = check_unstamped_rows(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )

    assert result.status == "skip"


# ---------------------------------------------------------------------------
# Workspace id agreement (from the onboard double-id defect)
# ---------------------------------------------------------------------------


def test_a_workspace_carrying_two_ids_is_reported(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """The onboard double-id defect, promoted to a check.

    Resolution prefers the manifest, so divergence is silent until the manifest
    is removed and the graph re-keys to an id nothing points at.
    """
    from agentscaffold.workspace_registry import load_registry, save_registry

    workspace = _shared_workspace(tmp_path)
    _register(workspace, projects=[("alpha", "alpha"), ("beta", "beta")])

    registry = load_registry()
    entry = registry.find_workspace_by_root(workspace)
    assert entry is not None
    entry.id = "ws-bbbbbbbbbbbb"
    save_registry(registry)

    result = _run(cli_runner, "--project-root", str(workspace / "alpha"))

    assert "ws-aaaaaaaaaaaa" in result.output
    assert "ws-bbbbbbbbbbbb" in result.output


def test_matching_ids_are_not_reported(state_home: Path, tmp_path: Path, cli_runner: CliRunner):
    workspace = _shared_workspace(tmp_path)
    _register(workspace, projects=[("alpha", "alpha"), ("beta", "beta")])

    result = _run(cli_runner, "--project-root", str(workspace / "alpha"), "--strict")

    assert result.exit_code == 0


def test_graph_schema_check_flags_a_missing_additive_column(state_home: Path, tmp_path: Path):
    import duckdb

    from agentscaffold.doctor import DoctorContext, check_graph_schema
    from agentscaffold.paths import resolve_db_path

    project = _project(tmp_path)
    _register(project)
    db = resolve_db_path(None, project)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE BacklogItem (id VARCHAR PRIMARY KEY, title VARCHAR, status VARCHAR)")
    conn.close()

    result = check_graph_schema(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )
    assert result.status == "fail"
    assert any("resolution" in detail for detail in result.details)
    assert result.remediation


def test_agent_docs_quiet_when_clean(tmp_path: Path) -> None:
    from agentscaffold.doctor import DoctorContext, check_agent_docs
    from agentscaffold.rendering import render_managed_block

    project = _project(tmp_path)
    (project / "AGENTS.md").write_text(
        "## Planning Rules\n\nmanual\n\n"
        + render_managed_block("## Session Working Rhythm\n\nroute\n")
    )
    result = check_agent_docs(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )
    assert result.status == "ok"


def test_agent_docs_reports_overlap(tmp_path: Path) -> None:
    from agentscaffold.doctor import DoctorContext, check_agent_docs
    from agentscaffold.rendering import render_managed_block

    project = _project(tmp_path)
    (project / "AGENTS.md").write_text(
        "## Planning Rules\n\none\n\n" + render_managed_block("## Planning Rules\n\ntwo\n")
    )
    result = check_agent_docs(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )
    assert result.status == "warn"
    assert "Planning Rules" in " ".join(result.details)


def _governance_check(project: Path, tmp_path: Path):
    from agentscaffold.doctor import DoctorContext, check_governance_mapping

    return check_governance_mapping(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )


def test_governance_mapping_ok_with_the_shipped_manual(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = _governance_check(project, tmp_path)
    assert result.status == "ok", result.details


def test_governance_mapping_names_each_missing_section(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "scaffold.yaml").write_text(
        "framework:\n  project_name: proj\n"
        "agents:\n  governance:\n    orient: [Hard Prohibitions, Release Train]\n"
        "    steps:\n      review: [Spike Requirements]\n"
        "      implementation: []\n      completion: []\n      backlog: []\n"
    )
    (project / "AGENTS.md").write_text("## Hard Prohibitions\n\nNo.\n")
    result = _governance_check(project, tmp_path)
    assert result.status == "warn"
    assert result.details == ["orient: Release Train", "review: Spike Requirements"]
    assert "agents.governance.optional" in (result.remediation or "")


def test_governance_mapping_ignores_optional_sections(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "scaffold.yaml").write_text(
        "framework:\n  project_name: proj\n"
        "agents:\n  governance:\n    orient: [Hard Prohibitions, Release Train]\n"
        "    optional: [Release Train]\n"
        "    steps:\n      review: []\n      implementation: []\n"
        "      completion: []\n      backlog: []\n"
    )
    (project / "AGENTS.md").write_text("## Hard Prohibitions\n\nNo.\n")
    assert _governance_check(project, tmp_path).status == "ok"


def test_governance_mapping_warns_when_the_manual_is_missing(tmp_path: Path) -> None:
    project = _project(tmp_path, manual=False)
    result = _governance_check(project, tmp_path)
    assert result.status == "warn"
    assert "AGENTS.md" in result.summary


def test_governance_mapping_quiet_when_no_manual_is_configured(tmp_path: Path) -> None:
    project = _project(tmp_path, manual=False)
    (project / "scaffold.yaml").write_text(
        "framework:\n  project_name: proj\nagents:\n  agents_md: false\n"
    )
    assert _governance_check(project, tmp_path).status == "ok"


def test_graph_schema_check_skips_when_there_is_no_graph(state_home: Path, tmp_path: Path):
    from agentscaffold.doctor import DoctorContext, check_graph_schema

    project = _project(tmp_path)
    _register(project)
    result = check_graph_schema(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )
    assert result.status == "skip"


def test_graph_schema_check_skips_when_the_graph_is_locked(
    state_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import duckdb

    from agentscaffold.doctor import DoctorContext, check_graph_schema
    from agentscaffold.paths import resolve_db_path

    project = _project(tmp_path)
    _register(project)
    db = resolve_db_path(None, project)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not a real duckdb, just needs to exist")

    def _locked(*_args, **_kwargs):
        raise OSError("Could not set lock on file: conflicting lock")

    monkeypatch.setattr(duckdb, "connect", _locked)
    result = check_graph_schema(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )
    assert result.status == "skip"
    assert "locked" in result.summary.lower()


def _inventory_check(project: Path, tmp_path: Path):
    from agentscaffold.doctor import DoctorContext, check_inventory

    return check_inventory(
        DoctorContext(project_root=project, mcp_config_path=tmp_path / "mcp.json")
    )


def _enabled(project: Path, extra: str = "") -> None:
    (project / "scaffold.yaml").write_text(
        "framework:\n  project_name: proj\ninventory:\n  enabled: true\n" + extra
    )


def _inventory_file(project: Path, last_review: str = "null") -> None:
    import datetime as dt

    path = project / "docs" / "ai" / "system_inventory.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if last_review == "today":
        last_review = dt.date.today().isoformat()
    path.write_text(
        f"schema_version: 1\nlast_architecture_review: {last_review}\n"
        "review_cadence_days: 30\ncomponents: []\n"
    )


def test_inventory_check_is_skipped_when_disabled(tmp_path: Path) -> None:
    result = _inventory_check(_project(tmp_path), tmp_path)
    assert result.status == "skip"
    assert "scaffold inventory enable" in (result.remediation or "")


def test_inventory_check_warns_when_the_file_is_missing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _enabled(project)
    result = _inventory_check(project, tmp_path)
    assert result.status == "warn"
    assert result.summary == "No inventory at docs/ai/system_inventory.yaml."


def test_inventory_check_reports_overdue_review_glob_and_workflow(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _enabled(project, "  collectors:\n    - name: compose\n      sources: [ops/*.yaml]\n")
    _inventory_file(project, "2020-01-01")
    (project / ".github" / "workflows").mkdir(parents=True)
    result = _inventory_check(project, tmp_path)
    assert result.status == "warn"
    assert result.details == [
        "architecture review: last 2020-01-01, cadence 30 days",
        "collector compose: sources match no files (ops/*.yaml)",
        "no scheduled review workflow at .github/workflows/inventory-review.yml",
    ]


def test_inventory_check_is_ok_when_current(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _enabled(project)
    _inventory_file(project, "today")
    result = _inventory_check(project, tmp_path)
    assert result.status == "ok", result.details
    assert result.summary.startswith("0 components; review recorded ")


def test_inventory_check_reports_an_unrecorded_review(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _enabled(project)
    _inventory_file(project)
    result = _inventory_check(project, tmp_path)
    assert result.details == ["architecture review: last_architecture_review is not recorded"]
