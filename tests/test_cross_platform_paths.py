"""Path-flavour correctness for registry resolution (Plan 249, Step A9b).

The package has no CI of any kind, so there is no Windows job to lean on. Rather
than pretend otherwise, these tests parametrise over path *flavour* -- exercising
the Windows branches of the resolution logic on any host by constructing
``PureWindowsPath`` inputs directly. That genuinely covers where the bugs live
(case folding, drive letters, UNC shares, separator handling), while being honest
that end-to-end Windows integration remains unverified. See Plan 249 Appendix D,
Decision 2, and the manual WSL check in Section 9.

Three distinct path spaces have to behave differently, which is the whole point:

- **Native Windows** (``C:\\repo``, ``\\\\server\\share\\repo``): case-insensitive,
  separator-agnostic, drive- and share-aware.
- **WSL** (``/mnt/c/repo``): genuinely POSIX and therefore case-**sensitive**, even
  though it names the same bytes on disk as ``C:\\repo``. WSL runs Linux; treating
  these as Windows paths because they mention a drive letter would be wrong.
- **Plain POSIX** (``/repo``): case-sensitive.

They must not cross-match. ``C:\\repo`` and ``/mnt/c/repo`` may be the same
directory on one machine, but WSL and Windows have separate home directories and
therefore separate registries, and nothing can tell us how ``/mnt`` is mounted
without reading WSL configuration we do not own.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from agentscaffold.path_flavour import (
    parse_recorded_path,
    path_contains,
    paths_equal,
)
from agentscaffold.workspace_registry import (
    RegisteredProject,
    RegisteredWorkspace,
    Registry,
    resolve_project_for_path,
)


def _registry(*roots: tuple[str, str, str]) -> Registry:
    """Build a registry from (workspace_id, root, project_name) triples."""
    return Registry(
        workspaces=[
            RegisteredWorkspace(
                id=wid,
                root=root,
                projects=[RegisteredProject(name=name, path=".")],
            )
            for wid, root, name in roots
        ]
    )


# ==========================================================================
# Flavour detection
# ==========================================================================


@pytest.mark.parametrize(
    "recorded",
    [
        r"C:\repo",
        "C:/repo",
        r"c:\repo",
        r"\\server\share\repo",
        r"\\SERVER\share",
    ],
)
def test_windows_shaped_paths_parse_as_windows(recorded):
    assert isinstance(parse_recorded_path(recorded), PureWindowsPath)


@pytest.mark.parametrize(
    "recorded",
    [
        "/repo",
        "/mnt/c/repo",
        "/Users/dave/repo",
        "/mnt/c",
    ],
)
def test_posix_shaped_paths_parse_as_posix(recorded):
    """``/mnt/c/...`` is a POSIX path that happens to mention a drive.

    Detecting "windowsness" from the presence of a drive letter anywhere would
    misclassify every WSL path, and WSL is the motivating environment for this
    plan.
    """
    assert isinstance(parse_recorded_path(recorded), PurePosixPath)


# ==========================================================================
# Windows: case-insensitivity
# ==========================================================================


@pytest.mark.parametrize(
    ("root", "target"),
    [
        (r"C:\repo", r"C:\repo\src"),
        (r"C:\Repo", r"c:\repo\src"),
        (r"c:\repo", r"C:\REPO\SRC"),
        (r"C:\repo", "C:/repo/src"),
        ("C:/repo", r"C:\repo\src"),
        (r"C:\repo", r"C:\repo"),
    ],
)
def test_windows_containment_ignores_case_and_separator(root, target):
    assert path_contains(parse_recorded_path(root), parse_recorded_path(target))


@pytest.mark.parametrize(
    ("root", "target"),
    [
        # The sibling trap: a string prefix check reports this as a match.
        (r"C:\repo", r"C:\repo-two\src"),
        (r"C:\repo", r"C:\repository\src"),
        # A different drive is a different filesystem.
        (r"C:\repo", r"D:\repo\src"),
        # Parent is not contained by child.
        (r"C:\repo\src", r"C:\repo"),
    ],
)
def test_windows_containment_rejects_non_children(root, target):
    assert not path_contains(parse_recorded_path(root), parse_recorded_path(target))


def test_windows_root_equality_is_case_insensitive():
    """Registering the same directory twice under different casing is one entry.

    On Windows ``C:\\Repo`` and ``c:\\repo`` are the same directory. Comparing the
    recorded roots as raw strings would let the same workspace be registered
    twice, which then makes every read of it ambiguous.
    """
    assert paths_equal(r"C:\Repo", r"c:\repo")
    assert paths_equal("C:/Repo/", r"c:\repo")
    assert not paths_equal(r"C:\repo", r"C:\repo-two")


# ==========================================================================
# Windows: UNC roots
# ==========================================================================


def test_unc_share_contains_its_children():
    root = parse_recorded_path(r"\\server\share\repo")

    assert path_contains(root, parse_recorded_path(r"\\server\share\repo\src"))


def test_unc_matching_is_case_insensitive_including_server_and_share():
    root = parse_recorded_path(r"\\server\share\repo")

    assert path_contains(root, parse_recorded_path(r"\\SERVER\SHARE\repo\src"))


def test_a_different_unc_share_does_not_match():
    root = parse_recorded_path(r"\\server\share\repo")

    assert not path_contains(root, parse_recorded_path(r"\\server\other\repo\src"))
    assert not path_contains(root, parse_recorded_path(r"\\elsewhere\share\repo\src"))


def test_a_unc_path_does_not_match_a_drive_letter_root():
    assert not path_contains(
        parse_recorded_path(r"C:\repo"),
        parse_recorded_path(r"\\server\share\repo\src"),
    )


# ==========================================================================
# WSL and POSIX: case sensitivity is required, not incidental
# ==========================================================================


def test_wsl_paths_contain_their_children():
    root = parse_recorded_path("/mnt/c/repo")

    assert path_contains(root, parse_recorded_path("/mnt/c/repo/src"))


def test_wsl_matching_is_case_sensitive():
    """WSL is Linux. ``/mnt/c/Repo`` and ``/mnt/c/repo`` are distinct there.

    Folding case for anything mentioning a drive letter would silently merge two
    genuinely different directories.
    """
    root = parse_recorded_path("/mnt/c/repo")

    assert not path_contains(root, parse_recorded_path("/mnt/c/Repo/src"))


def test_wsl_sibling_guard():
    root = parse_recorded_path("/mnt/c/repo")

    assert not path_contains(root, parse_recorded_path("/mnt/c/repo-two/src"))


def test_posix_matching_is_case_sensitive():
    assert not path_contains(parse_recorded_path("/repo"), parse_recorded_path("/Repo/src"))


# ==========================================================================
# The two path spaces must not cross-match
# ==========================================================================


def test_a_windows_root_does_not_capture_a_wsl_path():
    assert not path_contains(
        parse_recorded_path(r"C:\repo"),
        parse_recorded_path("/mnt/c/repo/src"),
    )


def test_a_wsl_root_does_not_capture_a_windows_path():
    assert not path_contains(
        parse_recorded_path("/mnt/c/repo"),
        parse_recorded_path(r"C:\repo\src"),
    )


# ==========================================================================
# Longest-prefix resolution, per flavour
# ==========================================================================


def test_windows_nested_projects_resolve_to_the_innermost():
    registry = _registry(
        ("ws-outer", r"C:\work", "outer"),
        ("ws-inner", r"C:\work\inner", "inner"),
    )

    resolved = resolve_project_for_path(r"C:\work\inner\src\main.py", registry)

    assert resolved is not None
    assert resolved.name == "inner"


def test_windows_nesting_resolves_correctly_despite_mixed_casing():
    """The case that a case-sensitive depth comparison gets wrong.

    If the inner root fails to match because the query is cased differently, the
    call silently resolves to the *outer* project -- a wrong answer rather than a
    refusal, and the hardest kind to notice.
    """
    registry = _registry(
        ("ws-outer", r"C:\Work", "outer"),
        ("ws-inner", r"C:\Work\Inner", "inner"),
    )

    resolved = resolve_project_for_path(r"c:\work\inner\src", registry)

    assert resolved is not None
    assert resolved.name == "inner"


def test_a_windows_sibling_is_not_resolved_from_its_neighbour():
    registry = _registry(("ws", r"C:\repo", "repo"))

    assert resolve_project_for_path(r"C:\repo-two\src", registry) is None


def test_unc_projects_resolve():
    registry = _registry(("ws", r"\\server\share\repo", "repo"))

    resolved = resolve_project_for_path(r"\\server\share\repo\docs", registry)

    assert resolved is not None
    assert resolved.name == "repo"


def test_wsl_projects_resolve():
    registry = _registry(("ws", "/mnt/c/work/repo", "repo"))

    resolved = resolve_project_for_path("/mnt/c/work/repo/src", registry)

    assert resolved is not None
    assert resolved.name == "repo"


def test_an_unmatched_flavour_resolves_to_none_rather_than_guessing():
    """Refusing is the contract. Resolution never falls back to a default."""
    registry = _registry(("ws", r"C:\repo", "repo"))

    assert resolve_project_for_path("/mnt/c/repo/src", registry) is None


def test_resolution_does_not_touch_the_filesystem_for_foreign_paths(tmp_path):
    """A Windows path cannot be stat-ed from a POSIX host, and need not be.

    Resolution has to work on paths that do not exist on this machine -- that is
    what makes the Windows branches testable here at all. A ``.resolve()`` on the
    host flavour would quietly mangle them into relative junk.
    """
    registry = _registry(("ws", r"C:\definitely\not\here", "ghost"))

    resolved = resolve_project_for_path(r"C:\definitely\not\here\src", registry)

    assert resolved is not None
    assert resolved.name == "ghost"


# ==========================================================================
# The mcp.json entry has to be resolvable on Windows
# ==========================================================================


def test_the_canonical_entry_command_resolves_via_path_on_windows():
    """``scaffold`` must be a bare name so Windows finds ``scaffold.exe``.

    Windows appends the extensions in ``PATHEXT`` when resolving a bare command
    name, so ``scaffold`` finds ``scaffold.exe`` without us naming it. Hardcoding
    either the ``.exe`` or an absolute interpreter path is what made the previous
    per-project entries break on a venv rebuild, and it is what pins a user to a
    stale interpreter (the version-skew blocker in workflow_state.md).
    """
    from agentscaffold.mcp.install import canonical_entry

    command = canonical_entry()["command"]

    assert command == "scaffold"
    assert not command.endswith(".exe")
    assert "/" not in command and "\\" not in command
    assert not PureWindowsPath(command).is_absolute()


# ==========================================================================
# Round-trip: the runnable half of Section 9's manual WSL check
#
# The full check needs a WSL host and stays on the Section 9 checklist. The
# first assertion it makes -- "root must round-trip, not be mangled" -- does not
# need Windows, only a WSL-shaped path, so it is pinned here rather than left
# entirely to a manual step someone has to remember.
# ==========================================================================


def test_a_wsl_shaped_root_round_trips_through_the_registry(tmp_path, monkeypatch):
    from agentscaffold.workspace_registry import load_registry, register_workspace

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    root = tmp_path / "mnt" / "c" / "Users" / "dave" / "repo"
    root.mkdir(parents=True)

    register_workspace(root, projects=[("repo", ".")])
    registry = load_registry()

    assert len(registry.workspaces) == 1
    assert registry.workspaces[0].root == str(root)
    assert registry.project_names() == ["repo"]


def test_re_registering_the_same_root_does_not_duplicate_it(tmp_path, monkeypatch):
    """Idempotence has to survive path comparison, not just string equality."""
    from agentscaffold.workspace_registry import load_registry, register_workspace

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    root = tmp_path / "mnt" / "c" / "repo"
    root.mkdir(parents=True)

    register_workspace(root, projects=[("repo", ".")])
    register_workspace(root, projects=[("repo", ".")])

    assert len(load_registry().workspaces) == 1


def test_a_wsl_root_resolves_a_working_path_beneath_it(tmp_path, monkeypatch):
    from agentscaffold.workspace_registry import load_registry, register_workspace

    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    root = tmp_path / "mnt" / "c" / "Users" / "dave" / "repo"
    (root / "src").mkdir(parents=True)

    register_workspace(root, projects=[("repo", ".")])
    resolved = resolve_project_for_path(root / "src", load_registry())

    assert resolved is not None
    assert resolved.name == "repo"
