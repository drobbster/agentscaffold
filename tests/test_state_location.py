"""Plan 249 Step B3: platform state location, precedence, and migration integrity.

The graph database has lived at ``.scaffold/graph.duckdb`` inside the repo. Phase
B moves it under the platform state directory keyed by workspace id, so a working
tree stays clean and several projects in a workspace share one cache without any
of them owning it.

Three things this suite is careful about, because each is a way to lose data
rather than merely to be wrong:

* **Precedence must not shift.** ``AGENTSCAFFOLD_DB_PATH`` still beats an explicit
  ``graph.db_path``, which still beats the platform default. A config that pins
  ``.scaffold/graph.duckdb`` keeps its database exactly where it is.
* **Upgrading must not abandon a populated database.** Flipping a default is not
  a migration. An existing in-tree database keeps being used until the user
  actually migrates.
* **Migration is copy, verify, then remove.** Never move-in-place, never remove
  something that was not verified to have arrived.

Relocation is scoped to *registered* workspaces and repos (approved 2026-08-05).
An unregistered repo has no stable id to key state by and keeps the in-tree
default, so ``scaffold project register`` is the opt-in.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig, load_config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_scaffold(root: Path, graph: dict | None = None) -> Path:
    """Write a minimal scaffold.yaml, optionally with a graph block."""
    root.mkdir(parents=True, exist_ok=True)
    lines = ["framework:", f"  project_name: {root.name}"]
    if graph:
        lines.append("graph:")
        for key, value in graph.items():
            lines.append(f"  {key}: {value}")
    path = root / "scaffold.yaml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _register(root: Path, name: str | None = None) -> str:
    """Register *root* as a workspace and return its assigned id."""
    from agentscaffold.workspace_registry import load_registry, register_workspace

    register_workspace(root, projects=[(name or root.name, ".")])
    workspace = load_registry().find_workspace_by_root(root)
    assert workspace is not None
    return workspace.id


@pytest.fixture
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point XDG_STATE_HOME at a scratch directory for the whole test."""
    home = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    monkeypatch.delenv("AGENTSCAFFOLD_DB_PATH", raising=False)
    return home


# ---------------------------------------------------------------------------
# The platform state directory
# ---------------------------------------------------------------------------


def test_state_dir_honours_xdg_state_home(state_home: Path):
    from agentscaffold.paths import resolve_user_state_dir

    assert resolve_user_state_dir() == (state_home / "agentscaffold").resolve()


def test_state_dir_defaults_under_local_state(monkeypatch: pytest.MonkeyPatch):
    from agentscaffold.paths import resolve_user_state_dir

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(os, "name", "posix")

    assert (
        resolve_user_state_dir() == (Path.home() / ".local" / "state" / "agentscaffold").resolve()
    )


def test_state_dir_uses_localappdata_on_native_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Native Windows has no XDG convention; %LOCALAPPDATA% is the equivalent.

    Exercised from a POSIX host by patching the platform predicate rather than
    ``os.name``: the latter changes which concrete class ``Path`` instantiates
    process-wide, and a Windows-flavoured Path cannot operate on this host's
    paths. What is under test is the policy -- consult %LOCALAPPDATA%, and keep
    state under its own subdirectory -- not Windows path syntax, which
    ``tests/test_cross_platform_paths.py`` covers.
    """
    from agentscaffold import paths as paths_mod

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(paths_mod, "_running_on_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    resolved = paths_mod.resolve_user_state_dir()

    assert resolved.parts[-2:] == ("agentscaffold", "State")
    assert str(tmp_path) in str(resolved)


def test_localappdata_state_is_separate_from_localappdata_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The two must not collide on Windows either."""
    from agentscaffold import paths as paths_mod

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(paths_mod, "_running_on_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    assert paths_mod.resolve_user_state_dir() != paths_mod.resolve_user_cache_dir()


def test_state_and_cache_are_different_roots(state_home: Path, monkeypatch: pytest.MonkeyPatch):
    """State is per-workspace and worth keeping; cache is global and rebuildable.

    Collapsing them would either key the model weights by workspace (the
    duplication Step A7c removed) or make graph state look disposable.
    """
    from agentscaffold.paths import resolve_user_cache_dir, resolve_user_state_dir

    monkeypatch.setenv("XDG_CACHE_HOME", str(state_home.parent / "xdg-cache"))

    assert resolve_user_state_dir() != resolve_user_cache_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_state_dir_is_created_user_only(state_home: Path, tmp_path: Path):
    """Threat model Vector 4.

    The relocation aggregates indexed content from every registered workspace
    into one directory -- a concentration the per-repo layout never had. It is
    created 0o700 rather than inheriting whatever the ambient umask allows.
    """
    from agentscaffold.paths import ensure_user_state_dir

    created = ensure_user_state_dir()

    assert stat.S_IMODE(created.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_per_workspace_state_subdir_is_user_only(state_home: Path, tmp_path: Path):
    from agentscaffold.paths import ensure_workspace_state_dir

    created = ensure_workspace_state_dir("ws-0123456789ab")

    assert stat.S_IMODE(created.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_migration_leaves_the_state_tree_user_only(state_home: Path, tmp_path: Path):
    """Asserted after a real migration, not on the helper that sets the mode.

    The first version of this suite only tested ``ensure_workspace_state_dir``
    directly. It passed while the migration created its destination with a plain
    ``mkdir``, so every directory shipped 0o755 and Vector 4 was unmet on the one
    path that actually runs.
    """
    from agentscaffold.paths import resolve_user_state_dir
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    _seed_in_tree_db(root)

    result = migrate_state(root, apply=True)

    assert stat.S_IMODE(resolve_user_state_dir().stat().st_mode) == 0o700
    assert stat.S_IMODE(result.destination.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_opening_a_graph_creates_state_dirs_user_only(state_home: Path, tmp_path: Path):
    """The graph backend creates the directory too, and must be as careful."""
    pytest.importorskip("duckdb")

    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.paths import resolve_db_path, resolve_user_state_dir

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    db = resolve_db_path(load_config(root / "scaffold.yaml"), root)

    with DuckPGQBackend(str(db)):
        pass

    assert stat.S_IMODE(resolve_user_state_dir().stat().st_mode) == 0o700
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_in_tree_directories_are_left_to_the_umask(tmp_path: Path, monkeypatch):
    """Only the state root is ours to tighten; the user's own tree is not."""
    from agentscaffold.paths import ensure_parent_dir

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    target = tmp_path / "repo" / ".scaffold" / "graph.duckdb"

    created = ensure_parent_dir(target)

    assert created.is_dir()
    assert stat.S_IMODE(created.stat().st_mode) != 0o700


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_env_var_still_overrides_everything(
    state_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from agentscaffold.paths import resolve_db_path

    root = tmp_path / "repo"
    _write_scaffold(root, {"db_path": "var/graph.duckdb"})
    _register(root)
    override = tmp_path / "elsewhere" / "graph.duckdb"
    monkeypatch.setenv("AGENTSCAFFOLD_DB_PATH", str(override))

    assert resolve_db_path(load_config(root / "scaffold.yaml"), root) == override


def test_explicit_db_path_beats_the_platform_default(state_home: Path, tmp_path: Path):
    """A config pinning the old location keeps working untouched."""
    from agentscaffold.paths import resolve_db_path

    root = tmp_path / "repo"
    _write_scaffold(root, {"db_path": ".scaffold/graph.duckdb"})
    _register(root)

    resolved = resolve_db_path(load_config(root / "scaffold.yaml"), root)

    assert resolved == root / ".scaffold" / "graph.duckdb"


def test_a_registered_workspace_defaults_into_the_state_dir(state_home: Path, tmp_path: Path):
    from agentscaffold.paths import resolve_db_path, resolve_user_state_dir

    root = tmp_path / "repo"
    _write_scaffold(root)
    workspace_id = _register(root)

    resolved = resolve_db_path(load_config(root / "scaffold.yaml"), root)

    assert resolved == resolve_user_state_dir() / workspace_id / "graph.duckdb"
    assert root not in resolved.parents, "the database is still inside the working tree"


def test_an_unregistered_repo_keeps_the_in_tree_default(state_home: Path, tmp_path: Path):
    """Relocation is opt-in via registration (approved scope, 2026-08-05).

    An unregistered repo has no stable id to key state by, and a path-derived
    key was rejected in ADR-025 because moving the root would orphan the state.
    """
    from agentscaffold.paths import resolve_db_path

    root = tmp_path / "repo"
    _write_scaffold(root)

    assert resolve_db_path(load_config(root / "scaffold.yaml"), root) == (
        root / ".scaffold" / "graph.duckdb"
    )


def test_workspace_yaml_id_is_preferred_over_the_registry_id(state_home: Path, tmp_path: Path):
    """One source of truth: a committed id in the manifest wins.

    Otherwise the same workspace could key state two ways depending on whether
    resolution happened to consult the registry first.
    """
    from agentscaffold.paths import resolve_db_path, resolve_user_state_dir

    ws = tmp_path / "ws"
    (ws / "alpha").mkdir(parents=True)
    _write_scaffold(ws / "alpha")
    (ws / "workspace.yaml").write_text(
        "id: ws-aaaaaaaaaaaa\nprojects:\n  - name: alpha\n    path: alpha\n"
    )
    _register(ws, name="alpha")

    resolved = resolve_db_path(load_config(ws / "alpha" / "scaffold.yaml"), ws / "alpha")

    assert resolved == resolve_user_state_dir() / "ws-aaaaaaaaaaaa" / "graph.duckdb"


def test_state_location_survives_moving_the_workspace(state_home: Path, tmp_path: Path):
    """The id is stable, so renaming or moving a root does not orphan state."""
    from agentscaffold.paths import resolve_db_path

    ws = tmp_path / "before"
    (ws / "alpha").mkdir(parents=True)
    _write_scaffold(ws / "alpha")
    (ws / "workspace.yaml").write_text(
        "id: ws-bbbbbbbbbbbb\nprojects:\n  - name: alpha\n    path: alpha\n"
    )
    before = resolve_db_path(load_config(ws / "alpha" / "scaffold.yaml"), ws / "alpha")

    moved = tmp_path / "after"
    ws.rename(moved)
    after = resolve_db_path(load_config(moved / "alpha" / "scaffold.yaml"), moved / "alpha")

    assert before == after


def test_projects_in_one_workspace_share_a_database(state_home: Path, tmp_path: Path):
    from agentscaffold.paths import resolve_db_path

    ws = tmp_path / "ws"
    for name in ("alpha", "beta"):
        _write_scaffold(ws / name)
    (ws / "workspace.yaml").write_text(
        "id: ws-cccccccccccc\n"
        "projects:\n  - name: alpha\n    path: alpha\n  - name: beta\n    path: beta\n"
    )

    alpha = resolve_db_path(load_config(ws / "alpha" / "scaffold.yaml"), ws / "alpha")
    beta = resolve_db_path(load_config(ws / "beta" / "scaffold.yaml"), ws / "beta")

    assert alpha == beta


# ---------------------------------------------------------------------------
# Upgrade safety: flipping a default is not a migration
# ---------------------------------------------------------------------------


def test_an_existing_in_tree_database_is_not_abandoned(state_home: Path, tmp_path: Path):
    """The failure this guards against is silent and total.

    A user upgrades, resolution points at an empty state directory, and the
    populated in-tree database is silently re-indexed from scratch while the
    original sits orphaned -- the two-divergent-databases outcome the plan's
    data-integrity constraint forbids, arriving with no migration having run.
    """
    from agentscaffold.paths import resolve_db_path

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    in_tree = root / ".scaffold" / "graph.duckdb"
    in_tree.parent.mkdir(parents=True)
    in_tree.write_bytes(b"existing graph")

    assert resolve_db_path(load_config(root / "scaffold.yaml"), root) == in_tree


def test_the_state_dir_wins_once_it_holds_a_database(state_home: Path, tmp_path: Path):
    """After migration the in-tree leftover must not pull resolution back."""
    from agentscaffold.paths import resolve_db_path, resolve_user_state_dir

    root = tmp_path / "repo"
    _write_scaffold(root)
    workspace_id = _register(root)

    in_tree = root / ".scaffold" / "graph.duckdb"
    in_tree.parent.mkdir(parents=True)
    in_tree.write_bytes(b"stale leftover")
    migrated = resolve_user_state_dir() / workspace_id / "graph.duckdb"
    migrated.parent.mkdir(parents=True)
    migrated.write_bytes(b"migrated graph")

    assert resolve_db_path(load_config(root / "scaffold.yaml"), root) == migrated


def test_freshness_agrees_with_graph_about_where_the_database_is(state_home: Path, tmp_path: Path):
    """Two resolvers disagreeing is how a graph gets indexed in one place and read in another."""
    from agentscaffold.mcp.freshness import _db_path
    from agentscaffold.paths import resolve_db_path

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    config = load_config(root / "scaffold.yaml")

    assert _db_path(root, config) == resolve_db_path(config, root)


# ---------------------------------------------------------------------------
# Migration: copy, verify, remove
# ---------------------------------------------------------------------------


def _seed_in_tree_db(root: Path, marker: str = "seeded") -> Path:
    """Create a real DuckDB database in the tree, carrying a readable marker.

    Deliberately a real database rather than arbitrary bytes: the migration
    refuses to touch a file it cannot open as one, and asserting the marker
    survives proves the copy is *usable* afterwards, which a byte comparison of
    a fake payload never would.
    """
    duckdb = pytest.importorskip("duckdb")

    db = root / ".scaffold" / "graph.duckdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db))
    try:
        conn.execute("CREATE TABLE marker (value VARCHAR)")
        conn.execute("INSERT INTO marker VALUES (?)", [marker])
    finally:
        conn.close()
    return db


def _hold_in_subprocess(db: Path, tmp_path: Path):
    """Start a subprocess holding *db* open, returning once it confirms it has it."""
    import subprocess

    script = tmp_path / "holder.py"
    script.write_text(
        "import sys, time, duckdb\n"
        "conn = duckdb.connect(sys.argv[1])\n"
        "print('HELD', flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, str(script), str(db)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    if line != "HELD":
        proc.terminate()
        pytest.fail(f"holder subprocess did not start: {line}")
    return proc


def _read_marker(db: Path) -> str:
    duckdb = pytest.importorskip("duckdb")

    conn = duckdb.connect(str(db), read_only=True)
    try:
        return conn.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        conn.close()


def test_dry_run_is_the_default_and_moves_nothing(state_home: Path, tmp_path: Path):
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    source = _seed_in_tree_db(root)

    result = migrate_state(root)

    assert result.applied is False
    assert result.source == source
    assert source.is_file()
    assert not result.destination.exists()


def test_apply_copies_then_removes_the_source(state_home: Path, tmp_path: Path):
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    source = _seed_in_tree_db(root, "payload")

    result = migrate_state(root, apply=True)

    assert result.applied is True
    assert _read_marker(result.destination) == "payload"
    assert not source.exists()


def test_migration_verifies_before_removing_the_source(
    state_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A copy that silently truncates must not be followed by a delete."""
    import shutil

    from agentscaffold.workspace_migrate_state import StateMigrationError, migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    source = _seed_in_tree_db(root, "the whole database")

    def _bad_copy(src, dst, *args, **kwargs):
        Path(dst).write_bytes(Path(src).read_bytes()[:64])
        return dst

    monkeypatch.setattr(shutil, "copy2", _bad_copy)

    with pytest.raises(StateMigrationError):
        migrate_state(root, apply=True)

    assert _read_marker(source) == "the whole database"


def test_a_failed_copy_leaves_no_partial_destination(
    state_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import shutil

    from agentscaffold.workspace_migrate_state import StateMigrationError, migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    _seed_in_tree_db(root)

    def _boom(src, dst, *args, **kwargs):
        Path(dst).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", _boom)

    with pytest.raises(StateMigrationError):
        migrate_state(root, apply=True)

    destination = migrate_state(root).destination
    assert not destination.exists()


def test_migration_refuses_while_the_source_is_in_use(state_home: Path, tmp_path: Path):
    """Reuses the Step A9 liveness probe.

    Copying a database another process is writing captures a torn page set, and
    removing it afterwards destroys the only good copy.

    The holder is a real subprocess because that is the real scenario -- the
    migration runs in the CLI while an MCP server holds the graph in a separate
    process. A9 measured the probe's one blind spot: its file lock is
    cross-process, so a handle opened inside *this* process would not trip it,
    and holding the database here would test nothing.
    """
    pytest.importorskip("duckdb")

    from agentscaffold.workspace_migrate_state import StateMigrationError, migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    source = _seed_in_tree_db(root)

    holder = _hold_in_subprocess(source, tmp_path)
    try:
        with pytest.raises(StateMigrationError, match="in use"):
            migrate_state(root, apply=True)
    finally:
        holder.terminate()
        holder.wait(timeout=10)

    assert source.is_file()
    assert _read_marker(source) == "seeded"


def test_migrating_twice_is_a_no_op(state_home: Path, tmp_path: Path):
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    _seed_in_tree_db(root, "payload")

    migrate_state(root, apply=True)
    second = migrate_state(root, apply=True)

    assert second.needed is False
    assert _read_marker(second.destination) == "payload"


def test_nothing_to_migrate_is_reported_not_raised(state_home: Path, tmp_path: Path):
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)

    result = migrate_state(root)

    assert result.needed is False


def test_an_unregistered_repo_has_nothing_to_migrate(state_home: Path, tmp_path: Path):
    """Its in-tree database is still the live one, so moving it would break it."""
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _seed_in_tree_db(root)

    result = migrate_state(root)

    assert result.needed is False


def test_restore_copies_the_database_back_in_tree(state_home: Path, tmp_path: Path):
    """The Section 12 rollback path."""
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    _seed_in_tree_db(root, "payload")
    migrate_state(root, apply=True)

    result = migrate_state(root, apply=True, restore=True)

    assert result.applied is True
    assert _read_marker(root / ".scaffold" / "graph.duckdb") == "payload"
    assert not result.source.exists()


def test_migration_plan_names_both_ends(state_home: Path, tmp_path: Path):
    """The dry run has to be readable enough to act on."""
    from agentscaffold.paths import resolve_user_state_dir
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    workspace_id = _register(root)
    _seed_in_tree_db(root)

    result = migrate_state(root)

    assert result.needed is True
    assert result.source == root / ".scaffold" / "graph.duckdb"
    assert result.destination == resolve_user_state_dir() / workspace_id / "graph.duckdb"


def test_sidecar_files_migrate_with_the_database(state_home: Path, tmp_path: Path):
    """Everything the graph writes beside its database travels with it.

    Leaving the freshness watermark behind would make a migrated graph look
    stale and trigger a full re-index on first use.

    The names come from the shared constant rather than being spelled out here.
    An earlier version of this test wrote ``freshness.json`` and asserted it
    arrived -- which it did, because the migration was carrying a list of two
    filenames nothing in the codebase has ever written. The test and the code
    agreed with each other and both were wrong about the disk.
    """
    from agentscaffold.paths import GRAPH_SIDECAR_FILENAMES
    from agentscaffold.workspace_migrate_state import migrate_state

    root = tmp_path / "repo"
    _write_scaffold(root)
    _register(root)
    _seed_in_tree_db(root, "payload")
    for name in GRAPH_SIDECAR_FILENAMES:
        (root / ".scaffold" / name).write_text(f"contents of {name}")

    result = migrate_state(root, apply=True)

    for name in GRAPH_SIDECAR_FILENAMES:
        assert (result.destination.parent / name).read_text() == f"contents of {name}"
        assert not (root / ".scaffold" / name).exists()


def test_the_sidecar_list_names_files_something_actually_writes(
    state_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The migration's list and the writers' paths must be the same strings.

    This is the assertion whose absence let two fictional filenames sit in the
    migration for two steps. It passes trivially now *because* both sides import
    one constant -- which is the point: the guarantee is structural, and this
    test fails the moment someone reintroduces a local copy that drifts.
    """
    from agentscaffold.graph.pipeline import _governance_fp_path
    from agentscaffold.mcp.freshness import _watermark_path
    from agentscaffold.paths import GRAPH_SIDECAR_FILENAMES
    from agentscaffold.workspace_migrate_state import _SIDECAR_NAMES

    root = tmp_path / "repo"
    _write_scaffold(root)
    config = load_config(root / "scaffold.yaml")

    class _FakeStore:
        _db_path = str(root / ".scaffold" / "graph.duckdb")

    written = {
        _watermark_path(root, config).name,
        _governance_fp_path(_FakeStore()).name,
    }

    assert written <= set(_SIDECAR_NAMES), (
        f"the graph writes {written - set(_SIDECAR_NAMES)} beside the database, "
        "and the migration would leave them behind"
    )
    assert set(GRAPH_SIDECAR_FILENAMES) == written


def test_config_default_no_longer_pins_the_in_tree_path():
    """``None`` means "use the platform default"; a string means the user chose.

    Pydantic's ``model_fields_set`` cannot carry that distinction here: the rigor
    preset round-trips the config through ``model_dump`` and re-validation, which
    marks every field as explicitly set under ``minimal`` and ``strict``.
    """
    assert ScaffoldConfig().graph.db_path is None
