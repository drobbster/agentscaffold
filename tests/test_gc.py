"""Plan 249 Step B7: pruning that cannot delete a live graph.

`scaffold gc` reclaims state directories left behind by workspaces that are gone
and registry entries pointing at roots that no longer exist. The graph is
expensive to rebuild and lives outside the tree since Step B4, so a wrong
deletion is not recoverable by `git checkout` -- which makes the interesting
tests here the ones about what gc *refuses* to touch.

The hazard is specific. A state directory is named for a workspace id, and an id
can legitimately belong to a workspace that was never registered (the manifest is
the source of truth, the registry is a convenience). "Not in the registry" is
therefore not evidence of orphanhood. So each state directory records the root it
was created for, and gc deletes only when it can *prove* orphanhood from that
record: the root is gone, or it now resolves to a different id. A directory with
no record is reported and left alone, which is the right way to be wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentscaffold.cli import app

#: Workspace ids are validated as ``ws-`` plus hex, so fixtures use hex that
#: still reads as a label in assertion output.
ORPHANED = "ws-0000000000aa"
PREVIOUS = "ws-0000000000bb"
NO_PROVENANCE = "ws-0000000000cc"
UNREGISTERED = "ws-0000000000dd"

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    monkeypatch.delenv("AGENTSCAFFOLD_DB_PATH", raising=False)
    return home


def _project(root: Path, name: str = "proj") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scaffold.yaml").write_text(f"framework:\n  project_name: {name}\n")
    return directory


def _register(root: Path) -> str:
    from agentscaffold.workspace_registry import load_registry, register_workspace

    register_workspace(root)
    entry = load_registry().find_workspace_by_root(root)
    assert entry is not None
    return entry.id


def _seed_state(workspace_id: str, root: Path | None) -> Path:
    """Create a state directory, with provenance when *root* is given."""
    from agentscaffold.paths import ensure_workspace_state_dir, write_state_provenance

    state = ensure_workspace_state_dir(workspace_id)
    (state / "graph.duckdb").write_bytes(b"graph")
    if root is not None:
        write_state_provenance(state, workspace_id, root)
    return state


def _run(cli_runner: CliRunner, *args: str):
    return cli_runner.invoke(app, ["gc", *args])


# ---------------------------------------------------------------------------
# Dry run is the default
# ---------------------------------------------------------------------------


def test_dry_run_is_the_default(state_home: Path, tmp_path: Path, cli_runner: CliRunner):
    gone = tmp_path / "gone"
    gone.mkdir()
    state = _seed_state(ORPHANED, gone)
    gone.rmdir()

    result = _run(cli_runner)

    assert result.exit_code == 0
    assert state.exists(), "gc must not delete without --apply"


def test_dry_run_says_what_it_would_remove(state_home: Path, tmp_path: Path, cli_runner: CliRunner):
    gone = tmp_path / "gone"
    gone.mkdir()
    _seed_state(ORPHANED, gone)
    gone.rmdir()

    result = _run(cli_runner)

    assert ORPHANED in result.output
    assert "--apply" in result.output


def test_a_clean_system_reports_nothing_to_do(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    workspace_id = _register(project)
    _seed_state(workspace_id, project)

    result = _run(cli_runner)

    assert result.exit_code == 0
    assert "nothing" in result.output.lower()


def test_apply_with_nothing_to_do_is_a_no_op(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    workspace_id = _register(project)
    state = _seed_state(workspace_id, project)

    result = _run(cli_runner, "--apply")

    assert result.exit_code == 0
    assert state.exists()


# ---------------------------------------------------------------------------
# What gc removes
# ---------------------------------------------------------------------------


def test_apply_removes_a_state_directory_whose_root_is_gone(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    gone = tmp_path / "gone"
    gone.mkdir()
    state = _seed_state(ORPHANED, gone)
    gone.rmdir()

    result = _run(cli_runner, "--apply")

    assert result.exit_code == 0
    assert not state.exists()


def test_apply_removes_a_state_directory_whose_root_now_has_a_different_id(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """A re-onboarded workspace strands its old state under the previous id."""
    project = _project(tmp_path)
    new_id = _register(project)
    stale = _seed_state(PREVIOUS, project)
    current = _seed_state(new_id, project)

    _run(cli_runner, "--apply")

    assert not stale.exists()
    assert current.exists()


def test_apply_removes_a_registry_entry_pointing_at_a_missing_root(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    from agentscaffold.workspace_registry import load_registry

    project = _project(tmp_path)
    _register(project)
    vanished = tmp_path / "vanished"
    vanished.mkdir()
    _register(vanished)
    vanished.rmdir()

    _run(cli_runner, "--apply")

    roots = [entry.root for entry in load_registry().workspaces]
    assert not any("vanished" in root for root in roots)
    assert any(str(project) == root for root in roots)


# ---------------------------------------------------------------------------
# What gc refuses to remove
# ---------------------------------------------------------------------------


def test_a_registered_workspace_keeps_its_state(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    project = _project(tmp_path)
    workspace_id = _register(project)
    state = _seed_state(workspace_id, project)

    _run(cli_runner, "--apply")

    assert state.exists()
    assert (state / "graph.duckdb").read_bytes() == b"graph"


def test_an_unregistered_workspace_with_a_live_root_keeps_its_state(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """The registry is a convenience; the manifest is the source of truth.

    A workspace that resolves to this id is live whether or not anything
    registered it, so absence from the registry is not grounds for deletion.
    """
    project = _project(tmp_path)
    (project / "workspace.yaml").write_text(f"id: {UNREGISTERED}\nprojects: []\n")
    state = _seed_state(UNREGISTERED, project)

    _run(cli_runner, "--apply")

    assert state.exists()


def test_a_state_directory_without_provenance_is_reported_not_deleted(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    """Directories predating the provenance marker cannot be proven orphaned."""
    state = _seed_state(NO_PROVENANCE, root=None)

    result = _run(cli_runner, "--apply")

    assert state.exists()
    assert NO_PROVENANCE in result.output


def test_gc_leaves_files_it_does_not_own_alone(
    state_home: Path, tmp_path: Path, cli_runner: CliRunner
):
    from agentscaffold.paths import resolve_user_state_dir

    project = _project(tmp_path)
    workspace_id = _register(project)
    _seed_state(workspace_id, project)
    stray = resolve_user_state_dir() / "notes.txt"
    stray.write_text("a human put this here")

    _run(cli_runner, "--apply")

    assert stray.exists()


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_opening_a_graph_records_the_root_its_state_belongs_to(
    state_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without this, gc has nothing to reason from for real workspaces."""
    from agentscaffold.paths import (
        STATE_PROVENANCE_FILENAME,
        ensure_parent_dir,
        resolve_db_path,
        resolve_user_state_dir,
    )

    project = _project(tmp_path)
    workspace_id = _register(project)
    monkeypatch.chdir(project)

    ensure_parent_dir(resolve_db_path(None, project))

    marker_path = resolve_user_state_dir() / workspace_id / STATE_PROVENANCE_FILENAME
    marker = json.loads(marker_path.read_text())
    assert marker["id"] == workspace_id
    assert Path(marker["root"]).resolve() == project.resolve()
