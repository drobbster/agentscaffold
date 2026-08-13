"""The startup anchor itself (Plan 257, ADR-026).

Every other resolution test substitutes ``_effective_mcp_root`` with a lambda, so
the one function that decides what the anchor *is* had no coverage at all. That
is why a field report against 0.10.5 could show a no-argument call being answered
from an unregistered project synthesised from a directory basename.

These tests call it for real, with the process cwd pointed at a fake ``$HOME``.
The fake home must live under ``tmp_path`` and not inside a repository: root
resolution walks up to the nearest ``scaffold.yaml`` or ``.git``, so a fixture
nested inside a real checkout escapes its own sandbox and resolves to the
enclosing project.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.mcp.errors import AmbiguousProjectError
from agentscaffold.mcp.project_resolution import ProjectResolution, resolve_project


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake ``$HOME`` with an isolated registry, and the cwd pointed at it.

    This is the launch condition the defect needs: IDEs start user-level MCP
    servers from the home directory rather than from the open workspace, so the
    anchor is a directory that *contains* projects instead of being one.
    """
    target = tmp_path / "me"
    (target / ".agentscaffold").mkdir(parents=True)
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target / ".agentscaffold"))
    monkeypatch.delenv("AGENTSCAFFOLD_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("AGENTSCAFFOLD_PROJECT", raising=False)
    monkeypatch.chdir(target)
    return target


def _project(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(f"project:\n  name: {name}\n")
    return root


def _workspace(root: Path, projects: list[tuple[str, str]]) -> Path:
    """Write a ``workspace.yaml`` declaring *projects* as (name, relative path)."""
    root.mkdir(parents=True, exist_ok=True)
    body = "version: 1\nprojects:\n" + "".join(
        f"  - name: {name}\n    path: {path}\n" for name, path in projects
    )
    (root / "workspace.yaml").write_text(body)
    return root


def _resolve_from_anchor(**kwargs) -> ProjectResolution:
    """Resolve exactly as dispatch does: the real anchor, then the real chain."""
    from agentscaffold.mcp.server import _effective_mcp_root

    return resolve_project(anchor=_effective_mcp_root(), **kwargs)


def test_shallow_child_workspace_is_not_evidence_of_intent(home: Path) -> None:
    """The field report against 0.10.5.

    Two workspaces are registered: one whose root is a direct child of the fake
    home, one nested four levels deeper. The child-workspace glob is one level
    deep, so only the shallow one can ever match it -- and "exactly one match" is
    then a property of directory layout rather than a statement about which
    project the caller meant. Worse, the condition is most likely to hold
    precisely when the other candidates are too deep to be seen.
    """
    from agentscaffold.workspace_registry import register_workspace

    alpha = _workspace(
        home / "alpha",
        [("alpha_underscore", "."), ("one", "one"), ("two", "nested/two")],
    )
    _project(alpha, "alpha_underscore")
    _project(alpha / "one", "one")
    _project(alpha / "nested" / "two", "two")

    deep = _workspace(home / "src" / "big-monorepo" / "dept" / "team", [("beta", "beta")])
    _project(deep / "beta", "beta")

    register_workspace(deep, projects=[("beta", "beta")])
    register_workspace(alpha, projects=[("one", "one"), ("two", "nested/two")])

    with pytest.raises(AmbiguousProjectError) as excinfo:
        _resolve_from_anchor()

    assert sorted(excinfo.value.candidates) == ["beta", "one", "two"]


def test_a_container_that_looks_like_a_repo_is_still_not_a_project(home: Path) -> None:
    """A ``.git`` in the home directory must not make it answerable.

    Gating only the glob on registry size leaves this open: the anchor falls back
    to the home directory, which a dotfiles repo makes look like a project root,
    and tier 3 then synthesises a project named after the folder. The
    discriminating property is containment, not the marker -- a directory with
    registered project roots beneath it is a container.
    """
    from agentscaffold.workspace_registry import register_workspace

    (home / ".git").mkdir()
    register_workspace(_project(home / "alpha", "alpha"), name="alpha")
    register_workspace(_project(home / "beta", "beta"), name="beta")

    with pytest.raises(AmbiguousProjectError) as excinfo:
        _resolve_from_anchor()

    assert sorted(excinfo.value.candidates) == ["alpha", "beta"]


def test_an_enclosing_repo_is_not_inherited_as_the_anchor(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root resolution walks up, so a bare cwd can inherit an ancestor repo.

    Same defect as the case above, reached from below rather than at the top: the
    cwd holds no marker, the walk-up finds the container's ``.git``, and the
    container is not a project.
    """
    from agentscaffold.workspace_registry import register_workspace

    (home / ".git").mkdir()
    register_workspace(_project(home / "alpha", "alpha"), name="alpha")
    register_workspace(_project(home / "beta", "beta"), name="beta")

    scratch = home / "Downloads"
    scratch.mkdir()
    monkeypatch.chdir(scratch)

    with pytest.raises(AmbiguousProjectError):
        _resolve_from_anchor()


def test_single_registered_workspace_still_resolves_with_no_arguments(home: Path) -> None:
    """The convenience case, which must survive the narrowing.

    One workspace registered, one project in it: the child-workspace shortcut is
    exactly the heuristic that makes a no-argument call work here, and there is
    no competing candidate for it to be wrong about.
    """
    from agentscaffold.workspace_registry import register_workspace

    solo = _workspace(home / "solo", [("solo", ".")])
    _project(solo, "solo")
    register_workspace(solo, projects=[("solo", ".")])

    resolution = _resolve_from_anchor()

    assert resolution.project.name == "solo"
    assert resolution.project.project_root == solo.resolve()
    assert resolution.project.workspace_id is not None, "should match the registry, not synthesise"


def test_container_of_the_only_registered_project_answers_that_project(
    home: Path,
) -> None:
    """Declining the container must not refuse when there is one obvious answer.

    Home holds a dotfiles ``.git`` and one registered project beneath it. Tier 3
    declines the container, and tier 4 then answers the sole registered project --
    correctly, because nothing competes with it. This is why Plan 257's proposed
    tier-4 constraint ("the sole project may not answer for an anchor outside
    itself") is deliberately *not* implemented: it would refuse exactly here, and
    this is the single-workspace convenience the fix promised to preserve.
    """
    from agentscaffold.workspace_registry import register_workspace

    (home / ".git").mkdir()
    solo = _project(home / "solo", "solo")
    register_workspace(solo, projects=[("solo", ".")])

    resolution = _resolve_from_anchor()

    assert resolution.project.name == "solo"
    assert resolution.source.value == "sole_project"


def test_unregistered_lone_repo_still_answers_about_itself(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Narrowing tier 3 must not punish the repo the caller is actually in.

    A lone repo that contains no registered project roots is a project, not a
    container, so it keeps resolving with its directory name standing in for a
    registry name. Requiring registry membership here would have broken this.
    """
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(_project(home / "alpha", "alpha"), name="alpha")
    register_workspace(_project(home / "beta", "beta"), name="beta")

    lone = home / "some-other-repo"
    lone.mkdir()
    (lone / ".git").mkdir()
    monkeypatch.chdir(lone)

    resolution = _resolve_from_anchor()

    assert resolution.project.name == "some-other-repo"
    assert resolution.project.workspace_id is None


def test_sole_registered_project_does_not_answer_for_an_unrelated_anchor(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tier 4 must not become the new wrong answer.

    Measured during review: requiring registry membership in tier 3 made this
    call fall through to ``_sole_project`` and answer from ``registered-repo``
    while the caller was working in ``some-other-repo`` -- a different wrong
    answer, and a worse one, since the anchor was a perfectly good project.
    """
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(_project(home / "registered-repo", "registered-repo"))

    lone = home / "some-other-repo"
    lone.mkdir()
    (lone / ".git").mkdir()
    monkeypatch.chdir(lone)

    resolution = _resolve_from_anchor()

    assert resolution.project.name == "some-other-repo"
