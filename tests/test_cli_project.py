"""CLI tests for ``scaffold project`` (Plan 249, Step A8).

Written before the commands exist. They pin the surface in
``docs/ai/contracts/workspace_registry_interface.md`` v1.3 and two properties the
threat model depends on:

- Registration is *only* explicit (Vector 1). `register` writes the registry and
  nothing else -- in particular it does not touch any client `mcp.json`, so
  widening what a server can read stays a separate, deliberate act.
- Failures are actionable. A name collision makes reads unresolvable, so it has
  to be refused with a message that says what to do, not a traceback.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentscaffold.cli import app
from agentscaffold.workspace_registry import REGISTRY_FILENAME, load_registry


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target))
    return target


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".git").mkdir(exist_ok=True)
    return root


# --------------------------------------------------------------------------
# register
# --------------------------------------------------------------------------


def test_register_records_the_root_and_reports_the_name(tmp_path, home, cli_runner):
    root = _repo(tmp_path / "alpha")
    result = cli_runner.invoke(app, ["project", "register", str(root)])

    assert result.exit_code == 0, result.output
    assert "alpha" in result.output

    registry = load_registry()
    assert registry.project_names() == ["alpha"]
    assert registry.workspaces[0].root == str(root.resolve())


def test_register_honours_an_explicit_name(tmp_path, home, cli_runner):
    root = _repo(tmp_path / "alpha")
    result = cli_runner.invoke(app, ["project", "register", str(root), "--name", "custom"])

    assert result.exit_code == 0, result.output
    assert load_registry().project_names() == ["custom"]


def test_register_is_idempotent(tmp_path, home, cli_runner):
    """Re-running must not duplicate the root or churn its id.

    The workspace id keys pooled graph state, so a re-register that minted a new
    id would orphan it.
    """
    root = _repo(tmp_path / "alpha")
    assert cli_runner.invoke(app, ["project", "register", str(root)]).exit_code == 0
    first_id = load_registry().workspaces[0].id

    again = cli_runner.invoke(app, ["project", "register", str(root)])
    assert again.exit_code == 0, again.output

    registry = load_registry()
    assert len(registry.workspaces) == 1
    assert registry.workspaces[0].id == first_id


def test_register_rejects_a_missing_directory(tmp_path, home, cli_runner):
    result = cli_runner.invoke(app, ["project", "register", str(tmp_path / "nope")])

    assert result.exit_code == 1
    assert "not" in result.output.lower()
    assert not (home / REGISTRY_FILENAME).exists()


def test_register_rejects_a_file_masquerading_as_a_root(tmp_path, home, cli_runner):
    target = tmp_path / "a-file"
    target.write_text("not a directory")
    result = cli_runner.invoke(app, ["project", "register", str(target)])

    assert result.exit_code == 1
    assert not (home / REGISTRY_FILENAME).exists()


def test_register_refuses_a_duplicate_name_with_an_actionable_message(tmp_path, home, cli_runner):
    """A name collision must name the remedy, since names qualify node IDs."""
    first = _repo(tmp_path / "one" / "shared")
    second = _repo(tmp_path / "two" / "shared")

    assert cli_runner.invoke(app, ["project", "register", str(first)]).exit_code == 0
    clash = cli_runner.invoke(app, ["project", "register", str(second)])

    assert clash.exit_code == 1
    assert "--name" in clash.output
    assert load_registry().project_names() == ["shared"]


def test_register_does_not_touch_mcp_json(tmp_path, home, cli_runner, monkeypatch):
    """Registration must not widen what any server reads (threat model, Vector 1).

    Registering and installing the server entry are separate commands precisely
    so that extending the read surface is never a side effect of onboarding.
    """
    client = home / ".cursor"
    client.mkdir()
    mcp = client / "mcp.json"
    mcp.write_text('{"mcpServers": {}}')
    before = mcp.read_bytes()

    root = _repo(tmp_path / "alpha")
    assert cli_runner.invoke(app, ["project", "register", str(root)]).exit_code == 0

    assert mcp.read_bytes() == before


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


def test_list_shows_registered_projects_with_their_roots(tmp_path, home, cli_runner):
    alpha = _repo(tmp_path / "alpha")
    beta = _repo(tmp_path / "beta")
    cli_runner.invoke(app, ["project", "register", str(alpha)])
    cli_runner.invoke(app, ["project", "register", str(beta)])

    result = cli_runner.invoke(app, ["project", "list"])

    assert result.exit_code == 0, result.output
    assert "alpha" in result.output
    assert "beta" in result.output


def test_list_on_an_empty_registry_explains_rather_than_showing_nothing(home, cli_runner):
    """An empty list is the normal state for a lone repo, not an error.

    It is also the state a confused user lands in, so it has to say what to do.
    """
    result = cli_runner.invoke(app, ["project", "list"])

    assert result.exit_code == 0, result.output
    assert "register" in result.output.lower()


# --------------------------------------------------------------------------
# unregister
# --------------------------------------------------------------------------


def test_unregister_removes_the_project(tmp_path, home, cli_runner):
    root = _repo(tmp_path / "alpha")
    cli_runner.invoke(app, ["project", "register", str(root)])

    result = cli_runner.invoke(app, ["project", "unregister", "alpha"])

    assert result.exit_code == 0, result.output
    assert load_registry().project_names() == []


def test_unregistering_something_absent_is_a_no_op_not_a_failure(home, cli_runner):
    """Teardown scripts run this blind; failing would make them fragile.

    It still says so, so an interactive typo is not silently swallowed.
    """
    result = cli_runner.invoke(app, ["project", "unregister", "ghost"])

    assert result.exit_code == 0, result.output
    assert "ghost" in result.output


def test_unregister_leaves_the_project_directory_alone(tmp_path, home, cli_runner):
    """Unregistering forgets a project; it must never delete one."""
    root = _repo(tmp_path / "alpha")
    marker = root / "keepme.txt"
    marker.write_text("content")
    cli_runner.invoke(app, ["project", "register", str(root)])

    cli_runner.invoke(app, ["project", "unregister", "alpha"])

    assert marker.read_text() == "content"
    assert root.is_dir()


# --------------------------------------------------------------------------
# The registry file itself
# --------------------------------------------------------------------------


def test_registry_is_written_user_private(tmp_path, home, cli_runner):
    """The registry enumerates every path the user has registered.

    It also defines the server's entire read surface, so it is 0600 rather than
    world-readable.
    """
    root = _repo(tmp_path / "alpha")
    cli_runner.invoke(app, ["project", "register", str(root)])

    registry_file = home / REGISTRY_FILENAME
    assert registry_file.exists()
    assert registry_file.stat().st_mode & 0o077 == 0

    parsed = yaml.safe_load(registry_file.read_text())
    assert parsed["version"] == 1


# --------------------------------------------------------------------------
# workspace onboard mirrors into the registry (Plan 249, Step A8)
# --------------------------------------------------------------------------


def test_workspace_onboard_registers_the_workspace(tmp_path, home, cli_runner, monkeypatch):
    """Onboarding is an explicit user action, so it may register (Vector 1).

    One workspace entry covers every project in the manifest rather than one
    entry per project, because pooled graph state is keyed per workspace.
    """
    ws = tmp_path / "ws"
    _repo(ws)
    (ws / "alpha").mkdir()
    (ws / "beta").mkdir()
    monkeypatch.chdir(ws)

    assert cli_runner.invoke(app, ["workspace", "onboard", "alpha"]).exit_code == 0
    assert cli_runner.invoke(app, ["workspace", "onboard", "beta"]).exit_code == 0

    registry = load_registry()
    assert len(registry.workspaces) == 1, "expected one workspace entry, not one per project"
    assert sorted(registry.project_names()) == ["alpha", "beta"]
    assert registry.workspaces[0].root == str(ws.resolve())


def test_onboard_still_writes_the_manifest_if_the_registry_fails(
    tmp_path, home, cli_runner, monkeypatch
):
    """A registry problem must not cost the user the manifest.

    The manifest is the durable artifact and is already written by this point;
    registration is a convenience on top, so it degrades to a warning.
    """
    ws = tmp_path / "ws"
    _repo(ws)
    (ws / "alpha").mkdir()
    monkeypatch.chdir(ws)

    import agentscaffold.workspace_registry as wr

    def boom(*args, **kwargs):
        raise OSError("registry unavailable")

    monkeypatch.setattr(wr, "register_workspace", boom)

    result = cli_runner.invoke(app, ["workspace", "onboard", "alpha"])

    assert result.exit_code == 0, result.output
    assert (ws / "workspace.yaml").exists()
    assert "registry update failed" in result.output.lower()
