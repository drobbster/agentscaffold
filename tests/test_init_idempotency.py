"""Plan 249 Step B5: idempotent, monorepo-aware init.

Three properties, in rising order of how easy they are to get wrong.

* **Re-running init changes nothing.** Not "does not clobber my edits", which is
  the weaker property the existing suite covers, but writes zero bytes: no file
  rewritten with identical content, no directory touched. The check is a
  content-and-mtime snapshot, because a rewrite that happens to produce the same
  bytes is still a rewrite, and it is what makes a re-run unsafe to suggest.
* **Init inside a workspace joins it rather than cloning it.** The project gets
  registered and receives its own system-of-record; the reusable process assets
  stay at the workspace root, which is the whole point of the shared layout.
* **The workspace id is never regenerated.** It keys the state directory since
  Step B4, so minting a second one orphans the graph. That makes the id the one
  piece of init's output where "write it again" is actively destructive.

``--dry-run`` is tested as a hard guarantee: it must be indistinguishable from
not running the command at all.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """Map every file under *root* to its (mtime_ns, content hash).

    Both halves matter. The hash catches a changed file; the mtime catches a file
    rewritten with identical bytes, which is invisible to a content diff and is
    still a write.
    """
    out: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[str(path.relative_to(root))] = (stat.st_mtime_ns, digest)
    return out


def _init(runner: CliRunner, directory: Path, *extra: str):
    return runner.invoke(app, ["init", str(directory), "-y", *extra])


def _make_workspace(root: Path, *, projects: list[str], shared: bool = True) -> Path:
    """Write a workspace manifest with an id, as onboarding would."""
    manifest: dict = {
        "id": "ws-aaaaaaaaaaaa",
        "projects": [{"name": name, "path": name} for name in projects],
    }
    if shared:
        manifest["asset_layout"] = {"layout": "shared_workspace"}
    for name in projects:
        (root / name).mkdir(parents=True, exist_ok=True)
    path = root / "workspace.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def _manifest(root: Path) -> dict:
    return yaml.safe_load((root / "workspace.yaml").read_text())


def _registry_workspaces() -> list:
    from agentscaffold.workspace_registry import load_registry

    return load_registry().workspaces


# ---------------------------------------------------------------------------
# Zero-byte re-run
# ---------------------------------------------------------------------------


def test_second_init_writes_nothing_at_all(tmp_path: Path, cli_runner: CliRunner):
    _init(cli_runner, tmp_path)
    before = _snapshot(tmp_path)

    result = _init(cli_runner, tmp_path)

    assert result.exit_code == 0
    assert _snapshot(tmp_path) == before


def test_second_init_says_there_was_nothing_to_do(tmp_path: Path, cli_runner: CliRunner):
    """A re-run that reports "Initialization complete" reads as if it did work."""
    _init(cli_runner, tmp_path)

    result = _init(cli_runner, tmp_path)

    assert "no changes" in result.output.lower()


def test_second_init_in_a_workspace_writes_nothing(tmp_path: Path, cli_runner: CliRunner):
    _make_workspace(tmp_path, projects=["alpha"])
    _init(cli_runner, tmp_path / "alpha")
    before = _snapshot(tmp_path)

    result = _init(cli_runner, tmp_path / "alpha")

    assert result.exit_code == 0
    assert _snapshot(tmp_path) == before


def test_second_init_does_not_duplicate_the_project_entry(tmp_path: Path, cli_runner: CliRunner):
    _make_workspace(tmp_path, projects=["alpha"])
    _init(cli_runner, tmp_path / "alpha")

    _init(cli_runner, tmp_path / "alpha")

    names = [p["name"] for p in _manifest(tmp_path)["projects"]]
    assert names.count("alpha") == 1


# ---------------------------------------------------------------------------
# Monorepo awareness
# ---------------------------------------------------------------------------


def test_init_inside_a_workspace_registers_the_project(tmp_path: Path, cli_runner: CliRunner):
    _make_workspace(tmp_path, projects=["alpha"])
    (tmp_path / "beta").mkdir()

    _init(cli_runner, tmp_path / "beta")

    names = [p["name"] for p in _manifest(tmp_path)["projects"]]
    assert "beta" in names

    registered = {p.name for ws in _registry_workspaces() for p in ws.projects}
    assert "beta" in registered


def test_init_inside_a_workspace_leaves_shared_assets_at_the_root(
    tmp_path: Path, cli_runner: CliRunner
):
    """Cloning the reusable assets into each project is the duplication the
    shared layout exists to remove."""
    _make_workspace(tmp_path, projects=["alpha"])
    (tmp_path / "beta").mkdir()

    _init(cli_runner, tmp_path / "beta")

    assert not (tmp_path / "beta" / "docs" / "ai" / "prompts").exists()
    assert (tmp_path / "docs" / "ai" / "prompts").is_dir()


def test_init_inside_a_workspace_still_writes_project_system_of_record(
    tmp_path: Path, cli_runner: CliRunner
):
    """Plans, ADRs and state are per project and must never be shared."""
    _make_workspace(tmp_path, projects=["alpha"])
    (tmp_path / "beta").mkdir()

    _init(cli_runner, tmp_path / "beta")

    beta = tmp_path / "beta"
    assert (beta / "scaffold.yaml").is_file()
    assert (beta / "docs" / "ai" / "plans").is_dir()
    assert (beta / "docs" / "ai" / "state" / "workflow_state.md").is_file()


def test_a_lone_repo_is_not_registered_by_init(tmp_path: Path, cli_runner: CliRunner):
    """Registration stays explicit (threat model Vector 1), and after Step B4 it
    is also what moves the graph out of the tree."""
    _init(cli_runner, tmp_path)

    assert _registry_workspaces() == []


# ---------------------------------------------------------------------------
# The workspace id must never be regenerated
# ---------------------------------------------------------------------------


def test_init_does_not_regenerate_the_workspace_id(tmp_path: Path, cli_runner: CliRunner):
    _make_workspace(tmp_path, projects=["alpha"])
    (tmp_path / "beta").mkdir()

    _init(cli_runner, tmp_path / "beta")

    assert _manifest(tmp_path)["id"] == "ws-aaaaaaaaaaaa"


def test_registering_a_manifested_workspace_adopts_the_manifest_id(tmp_path: Path):
    """The manifest is the source of truth, so the registry must follow it.

    Found while probing Step B5: `workspace onboard` wrote a generated id into
    the manifest and `register_workspace` minted a second, unrelated one, so a
    freshly onboarded workspace carried two ids. Resolution prefers the manifest,
    so `scaffold project list` was reporting an id that keyed nothing.
    """
    from agentscaffold.workspace_registry import register_workspace

    _make_workspace(tmp_path, projects=["alpha"])

    entry = register_workspace(tmp_path, projects=[("alpha", "alpha")])

    assert entry.id == "ws-aaaaaaaaaaaa"


def test_writing_a_manifest_adopts_an_existing_registry_id(
    tmp_path: Path, cli_runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """The dangerous direction: state may already be keyed to the registry id.

    A registered lone repo that later gains a manifest must keep its id, or the
    graph it already built becomes unreachable.

    ``workspace onboard`` resolves against the working directory, so the chdir is
    load-bearing, not tidiness: without it the first draft of this test onboarded
    the checkout it was running in and wrote a manifest into a real repository.
    """
    from agentscaffold.workspace_registry import load_registry, register_workspace

    project = tmp_path / "solo"
    project.mkdir()
    _init(cli_runner, project)
    register_workspace(project)
    original = load_registry().find_workspace_by_root(project)
    assert original is not None

    monkeypatch.chdir(project)
    result = cli_runner.invoke(app, ["workspace", "onboard", "."], catch_exceptions=False)
    assert result.exit_code == 0

    assert _manifest(project).get("id") == original.id


def test_the_state_location_survives_registration(tmp_path: Path, cli_runner: CliRunner):
    """The end the id rules exist to protect: the graph stays findable."""
    from agentscaffold.config import load_config
    from agentscaffold.paths import resolve_db_path
    from agentscaffold.workspace_registry import register_workspace

    _make_workspace(tmp_path, projects=["alpha"])
    _init(cli_runner, tmp_path / "alpha")
    config = load_config(tmp_path / "alpha" / "scaffold.yaml")
    before = resolve_db_path(config, tmp_path / "alpha")

    register_workspace(tmp_path, projects=[("alpha", "alpha")])

    assert resolve_db_path(config, tmp_path / "alpha") == before


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def test_dry_run_creates_nothing(tmp_path: Path, cli_runner: CliRunner):
    target = tmp_path / "fresh"
    target.mkdir()

    result = _init(cli_runner, target, "--dry-run")

    assert result.exit_code == 0
    assert list(target.iterdir()) == []


def test_dry_run_does_not_create_a_missing_directory(tmp_path: Path, cli_runner: CliRunner):
    """Init creates its target when absent, which a dry run must not do."""
    target = tmp_path / "not-there"

    result = _init(cli_runner, target, "--dry-run")

    assert result.exit_code == 0
    assert not target.exists()


def test_dry_run_reports_what_it_would_create(tmp_path: Path, cli_runner: CliRunner):
    result = _init(cli_runner, tmp_path, "--dry-run")

    assert "scaffold.yaml" in result.output
    assert "dry run" in result.output.lower()


def test_dry_run_does_not_register(tmp_path: Path, cli_runner: CliRunner):
    _make_workspace(tmp_path, projects=["alpha"])
    (tmp_path / "beta").mkdir()

    _init(cli_runner, tmp_path / "beta", "--dry-run")

    names = [p["name"] for p in _manifest(tmp_path)["projects"]]
    assert "beta" not in names


def test_dry_run_on_an_initialized_project_reports_no_changes(
    tmp_path: Path, cli_runner: CliRunner
):
    _init(cli_runner, tmp_path)
    before = _snapshot(tmp_path)

    result = _init(cli_runner, tmp_path, "--dry-run")

    assert "no changes" in result.output.lower()
    assert _snapshot(tmp_path) == before


def test_dry_run_and_apply_agree_on_what_gets_written(tmp_path: Path, cli_runner: CliRunner):
    """A plan nobody checks against the outcome is decoration."""
    planned = _init(cli_runner, tmp_path, "--dry-run")

    _init(cli_runner, tmp_path)

    written = set(_snapshot(tmp_path))
    named = {line.strip() for line in planned.output.splitlines()}
    for expected in ("scaffold.yaml", "AGENTS.md"):
        assert expected in written
        assert any(expected in line for line in named)


@pytest.mark.parametrize("flag", ["--dry-run"])
def test_dry_run_leaves_no_registry_behind(tmp_path: Path, cli_runner: CliRunner, flag: str):
    _init(cli_runner, tmp_path, flag)

    assert _registry_workspaces() == []
