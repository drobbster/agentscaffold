"""Relative working paths, and names for projects the registry does not know.

Plan 257, Groups C and D. Both cases here fail quietly rather than loudly, which
is why they are worth pinning: a relative path resolved against the server's own
launch directory usually points at nothing and falls back to the anchor, and a
project synthesised under its directory basename resolves fine while every scoped
read filters on a name the graph never wrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.mcp.project_resolution import resolve_project


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "me"
    (target / ".agentscaffold").mkdir(parents=True)
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target / ".agentscaffold"))
    monkeypatch.chdir(target)
    return target


def _project(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(f"project:\n  name: {name}\n")
    return root


def test_a_relative_path_resolves_against_the_registered_roots(home: Path) -> None:
    """The form an agent naturally sends, which used to resolve to nothing.

    ``src/main.py`` is what the editor shows. Joined onto the server's launch
    directory it does not exist, so the path is dropped and the anchor answers --
    a different project, silently.
    """
    from agentscaffold.workspace_registry import register_workspace

    beta = _project(home / "deep" / "nest" / "beta", "beta")
    (beta / "src").mkdir()
    (beta / "src" / "main.py").write_text("x = 1\n")
    register_workspace(_project(home / "alpha", "alpha"), name="alpha")
    register_workspace(beta, name="beta")

    resolution = resolve_project(working_path="src/main.py", anchor=home / "alpha")

    assert resolution.project.name == "beta"
    assert resolution.source.value == "working_path"


def test_a_relative_path_matching_two_workspaces_is_not_guessed(home: Path) -> None:
    """Two candidates means the fragment does not identify a project.

    Both projects contain ``src/main.py``, so any choice is a coin toss. The path
    is left unmatched and the call refuses, which is the whole point of ADR-026.
    """
    from agentscaffold.mcp.errors import AmbiguousProjectError
    from agentscaffold.workspace_registry import register_workspace

    for name in ("alpha", "beta"):
        project = _project(home / name, name)
        (project / "src").mkdir()
        (project / "src" / "main.py").write_text("x = 1\n")
        register_workspace(project, name=name)

    with pytest.raises(AmbiguousProjectError):
        resolve_project(working_path="src/main.py", anchor=home)


def test_an_absolute_path_is_left_alone(home: Path) -> None:
    """The registered-root search must not reinterpret a path that needs no help."""
    from agentscaffold.workspace_registry import register_workspace

    alpha = _project(home / "alpha", "alpha")
    register_workspace(alpha, name="alpha")
    register_workspace(_project(home / "beta", "beta"), name="beta")

    resolution = resolve_project(working_path=str(alpha / "scaffold.yaml"))

    assert resolution.project.name == "alpha"


def test_a_synthesised_project_uses_the_name_its_manifest_declares(home: Path) -> None:
    """The graph scopes rows by the manifest name, so resolution must agree.

    An unregistered workspace whose manifest names the project at its root
    something other than the folder resolved under the basename, and then every
    scoped read filtered on a name nothing had been written under: a successful
    call with empty results and no indication why.
    """
    root = home / "code" / "app"
    _project(root, "my-app")
    (root / "workspace.yaml").write_text("version: 1\nprojects:\n  - name: my-app\n    path: .\n")

    resolution = resolve_project(anchor=root)

    assert resolution.project.name == "my-app"
    assert resolution.project.workspace_id is None


def test_a_basename_with_spaces_is_normalised(home: Path) -> None:
    """Synthesis went through the raw basename, which need not be a legal name."""
    root = home / "my repo"
    _project(root, "my-repo")

    resolution = resolve_project(anchor=root)

    assert resolution.project.name == "my-repo"


def test_doctor_reports_a_project_declared_but_never_registered(home: Path) -> None:
    """Manifest-versus-registry drift, which nothing surfaced before.

    Registration snapshots the manifest, so a project added afterwards cannot be
    named with ``project=``, never appears among the candidates in a refusal, and
    is not a registered root -- which is how its workspace ended up being answered
    as a synthesised project instead.
    """
    from agentscaffold.doctor import DoctorContext, check_registry
    from agentscaffold.workspace_registry import register_workspace

    ws = home / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text(
        "version: 1\nprojects:\n  - name: one\n    path: one\n  - name: two\n    path: two\n"
    )
    _project(ws / "one", "one")
    _project(ws / "two", "two")
    register_workspace(ws, projects=[("one", "one")])

    result = check_registry(
        DoctorContext(project_root=ws, mcp_config_path=home / "mcp.json"),
    )

    assert result.status == "warn"
    assert any("two" in detail for detail in result.details)
    assert "scaffold project register" in (result.remediation or "")
