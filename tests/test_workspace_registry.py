"""Tests for the user-level workspace registry and path resolution (Plan 249, Step A3).

Written before ``workspace_registry.py`` exists (Step A4 implements it), so these
tests define the surface described by
``docs/ai/contracts/workspace_registry_interface.md`` v1.0.

Scope here is registry CRUD and longest-prefix resolution only. The full
precedence chain (explicit argument, then working_path, then startup anchor, then
sole project) is Step A5, and Windows/UNC/WSL path flavours are Step A9b in
``test_cross_platform_paths.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentscaffold.config import ConfigError
from agentscaffold.workspace_ids import generate_workspace_id, is_valid_workspace_id
from agentscaffold.workspace_registry import (
    REGISTRY_FILENAME,
    REGISTRY_VERSION,
    RegistryError,
    load_registry,
    register_workspace,
    registry_path,
    resolve_project_for_path,
    save_registry,
    unregister_project,
)


@pytest.fixture()
def registry_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point AGENTSCAFFOLD_HOME at a temp dir and return the registry path.

    Exercises the real home-resolution mechanism rather than stubbing it, since
    the contract commits to reusing ``config_home.resolve_home_dir`` unchanged.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(home))
    return home / REGISTRY_FILENAME


def _make_workspace(root: Path, *projects: str) -> Path:
    """Create a workspace root with the given project subdirectories."""
    root.mkdir(parents=True, exist_ok=True)
    for project in projects:
        (root / project).mkdir(parents=True, exist_ok=True)
    return root


# --------------------------------------------------------------------------
# Registry location and CRUD
# --------------------------------------------------------------------------


def test_registry_path_follows_agentscaffold_home(registry_file: Path) -> None:
    """The registry lives at <home>/registry.yaml, honouring AGENTSCAFFOLD_HOME."""
    assert registry_path() == registry_file


def test_absent_registry_loads_as_empty(registry_file: Path) -> None:
    """A missing registry means 'nothing registered yet', not an error.

    Fresh installs and lone repos never create one, so loading must not raise.
    """
    assert not registry_file.exists()

    registry = load_registry()

    assert registry.version == REGISTRY_VERSION
    assert registry.workspaces == []


def test_register_creates_versioned_file_with_generated_id(
    registry_file: Path, tmp_path: Path
) -> None:
    """Registering a root writes a v1 file and assigns a stable workspace id."""
    root = _make_workspace(tmp_path / "solo")

    entry = register_workspace(root)

    assert is_valid_workspace_id(entry.id)
    raw = yaml.safe_load(registry_file.read_text())
    assert raw["version"] == REGISTRY_VERSION
    assert len(raw["workspaces"]) == 1
    assert raw["workspaces"][0]["root"] == str(root)


def test_register_defaults_project_name_to_root_basename(
    tmp_path: Path, registry_file: Path
) -> None:
    """Without --name, the project takes the root's basename."""
    root = _make_workspace(tmp_path / "capacity-eng")

    entry = register_workspace(root)

    assert [p.name for p in entry.projects] == ["capacity-eng"]
    assert [p.path for p in entry.projects] == ["."]


def test_register_honours_explicit_name(tmp_path: Path, registry_file: Path) -> None:
    """An explicit name overrides the derived basename."""
    root = _make_workspace(tmp_path / "capacity-eng")

    entry = register_workspace(root, name="capacity")

    assert [p.name for p in entry.projects] == ["capacity"]


def test_register_is_idempotent_for_same_root(tmp_path: Path, registry_file: Path) -> None:
    """Re-registering the same root updates in place rather than duplicating.

    ``scaffold project register`` is expected to be safe to re-run, and a
    duplicated root would make longest-prefix resolution ambiguous.
    """
    root = _make_workspace(tmp_path / "solo")

    first = register_workspace(root)
    second = register_workspace(root)

    registry = load_registry()
    assert len(registry.workspaces) == 1
    assert first.id == second.id, "workspace id must be stable across re-registration"


def test_register_rejects_invalid_project_name(tmp_path: Path, registry_file: Path) -> None:
    """Registry names reuse validate_project_name, so '::' and whitespace are out."""
    root = _make_workspace(tmp_path / "solo")

    with pytest.raises(ConfigError):
        register_workspace(root, name="bad::name")


def test_register_rejects_duplicate_project_name_across_workspaces(
    tmp_path: Path, registry_file: Path
) -> None:
    """Names qualify node IDs, so a collision across workspaces is unresolvable."""
    register_workspace(_make_workspace(tmp_path / "a"), name="shared")

    with pytest.raises(RegistryError):
        register_workspace(_make_workspace(tmp_path / "b"), name="shared")


def test_unregister_removes_project_and_reports_success(
    tmp_path: Path, registry_file: Path
) -> None:
    """Unregistering a known name removes it and returns True."""
    register_workspace(_make_workspace(tmp_path / "solo"), name="solo")

    assert unregister_project("solo") is True
    assert load_registry().workspaces == []


def test_unregister_unknown_name_is_false_not_an_error(registry_file: Path) -> None:
    """Unregistering something absent is a no-op, so cleanup scripts stay simple."""
    assert unregister_project("never-registered") is False


def test_round_trip_preserves_all_fields(tmp_path: Path, registry_file: Path) -> None:
    """save -> load returns an equivalent registry, so nothing is silently dropped."""
    root = _make_workspace(tmp_path / "mono", "svc-a", "svc-b")
    register_workspace(root / "svc-a", name="svc-a")
    register_workspace(root / "svc-b", name="svc-b")

    before = load_registry()
    save_registry(before)
    after = load_registry()

    assert after == before


def test_save_is_atomic_and_leaves_no_partial_file(tmp_path: Path, registry_file: Path) -> None:
    """Writes go through a temp file and rename, so readers never see a partial doc.

    A concurrent reader must observe either the old document or the new one.
    """
    register_workspace(_make_workspace(tmp_path / "solo"), name="solo")

    stray = [p.name for p in registry_file.parent.iterdir() if p.name != REGISTRY_FILENAME]
    assert stray == [], f"atomic write left temp files behind: {stray}"
    assert yaml.safe_load(registry_file.read_text())["version"] == REGISTRY_VERSION


def test_unknown_future_schema_version_is_rejected(registry_file: Path) -> None:
    """A newer registry must fail loudly rather than be silently misread."""
    registry_file.write_text(yaml.safe_dump({"version": REGISTRY_VERSION + 1, "workspaces": []}))

    with pytest.raises(RegistryError):
        load_registry()


def test_malformed_registry_raises_rather_than_resetting(registry_file: Path) -> None:
    """A corrupt registry must not be silently treated as empty.

    Treating it as empty would quietly unregister every project.
    """
    registry_file.write_text("{ this is not: valid: yaml")

    with pytest.raises(RegistryError):
        load_registry()


# --------------------------------------------------------------------------
# Longest-prefix resolution
# --------------------------------------------------------------------------


def test_path_inside_project_resolves_to_that_project(tmp_path: Path, registry_file: Path) -> None:
    """A file deep inside a registered project resolves to it."""
    root = _make_workspace(tmp_path / "solo", "src")
    register_workspace(root, name="solo")

    resolved = resolve_project_for_path(root / "src" / "module.py", load_registry())

    assert resolved is not None
    assert resolved.name == "solo"
    assert resolved.project_root == root


def test_exact_project_root_resolves(tmp_path: Path, registry_file: Path) -> None:
    """The root itself resolves, not just paths beneath it."""
    root = _make_workspace(tmp_path / "solo")
    register_workspace(root, name="solo")

    resolved = resolve_project_for_path(root, load_registry())

    assert resolved is not None and resolved.name == "solo"


def test_nested_registrations_resolve_to_longest_prefix(
    tmp_path: Path, registry_file: Path
) -> None:
    """The most specific registered root wins when registrations nest.

    This is the whole point of longest-prefix matching: an inner project must
    not be answered from its enclosing workspace.
    """
    outer = _make_workspace(tmp_path / "mono", "inner")
    register_workspace(outer, name="outer")
    register_workspace(outer / "inner", name="inner")

    resolved = resolve_project_for_path(outer / "inner" / "src" / "app.py", load_registry())

    assert resolved is not None
    assert resolved.name == "inner", "enclosing workspace must not win over the inner project"


def test_sibling_with_shared_string_prefix_does_not_match(
    tmp_path: Path, registry_file: Path
) -> None:
    """Matching is on path components, not raw string prefixes.

    ``/repo`` must not swallow ``/repo-two``, which plain ``startswith`` would.
    """
    register_workspace(_make_workspace(tmp_path / "repo"), name="repo")
    sibling = _make_workspace(tmp_path / "repo-two")

    resolved = resolve_project_for_path(sibling / "file.py", load_registry())

    assert resolved is None, "string-prefix match leaked across sibling directories"


def test_path_outside_every_registered_root_is_unresolved(
    tmp_path: Path, registry_file: Path
) -> None:
    """No match returns None so the caller can raise ambiguous_project.

    Falling back to a default project is the failure mode this design prevents:
    answering plausibly from the wrong project is worse than refusing.
    """
    register_workspace(_make_workspace(tmp_path / "solo"), name="solo")

    assert resolve_project_for_path(tmp_path / "elsewhere" / "x.py", load_registry()) is None


def test_multi_project_workspace_resolves_to_the_specific_project(
    tmp_path: Path, registry_file: Path
) -> None:
    """Sibling projects under one root resolve independently."""
    root = _make_workspace(tmp_path / "mono", "svc-a", "svc-b")
    register_workspace(root / "svc-a", name="svc-a")
    register_workspace(root / "svc-b", name="svc-b")

    registry = load_registry()

    assert resolve_project_for_path(root / "svc-a" / "x.py", registry).name == "svc-a"
    assert resolve_project_for_path(root / "svc-b" / "y.py", registry).name == "svc-b"


def test_resolution_normalises_relative_and_dotted_paths(
    tmp_path: Path, registry_file: Path
) -> None:
    """Paths are resolved before matching, so '..' segments cannot escape a root."""
    root = _make_workspace(tmp_path / "solo", "src")
    register_workspace(root, name="solo")

    resolved = resolve_project_for_path(root / "src" / ".." / "src" / "m.py", load_registry())

    assert resolved is not None and resolved.name == "solo"


def test_resolution_on_empty_registry_is_none(registry_file: Path, tmp_path: Path) -> None:
    """An empty registry resolves nothing rather than raising."""
    assert resolve_project_for_path(tmp_path / "anywhere", load_registry()) is None


# --------------------------------------------------------------------------
# Workspace ids
# --------------------------------------------------------------------------


def test_generated_ids_are_valid_and_unique() -> None:
    """Ids are opaque and non-colliding.

    Deliberately not a hash of the path: moving or renaming a workspace root
    must not orphan its state.
    """
    ids = {generate_workspace_id() for _ in range(50)}

    assert len(ids) == 50
    assert all(is_valid_workspace_id(value) for value in ids)


def test_workspace_id_rejects_malformed_values() -> None:
    """Validation is strict enough to catch a hand-edited registry."""
    assert not is_valid_workspace_id("")
    assert not is_valid_workspace_id("7f3a9c")
    assert not is_valid_workspace_id("ws-")
    assert not is_valid_workspace_id("ws-not hex")
