"""Tests for the call-time project resolution chain (Plan 249, Step A5).

Written before ``mcp/projects.py`` and ``mcp/errors.py`` exist (Step A6 implements
them), so these define the surface described by
``docs/ai/contracts/workspace_registry_interface.md`` v1.0.

The precedence is: explicit ``project`` argument, then ``working_path`` matched
against registered roots, then the startup anchor retained from Plan 234, then
the sole registered project. Anything else is a structured ``ambiguous_project``
error.

The single most important property under test is that there is **no silent
fallback**. Before this plan, an unresolvable call quietly federated across every
project or answered from the server's launch directory. A plausible answer scoped
to the wrong project is much harder to notice than a refusal, which is why
refusing is the specified behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.mcp.errors import AmbiguousProjectError, UnknownProjectError
from agentscaffold.mcp.project_resolution import ResolutionSource, resolve_project
from agentscaffold.workspace_registry import Registry, load_registry, register_workspace


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point AGENTSCAFFOLD_HOME at a temp dir so the registry is isolated."""
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target))
    return target


def _project(root: Path, name: str) -> Path:
    """Create a project root that looks like a real scaffolded repo."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text("framework:\n  project_name: " + name + "\n")
    return root


# --------------------------------------------------------------------------
# Tier 1 -- explicit project argument
# --------------------------------------------------------------------------


def test_explicit_project_wins_over_working_path(home: Path, tmp_path: Path) -> None:
    """An explicit project beats a working_path pointing somewhere else.

    The explicit argument is the caller stating intent, so it must not be
    second-guessed by path inference.
    """
    a = _project(tmp_path / "alpha", "alpha")
    b = _project(tmp_path / "beta", "beta")
    register_workspace(a, name="alpha")
    register_workspace(b, name="beta")

    resolved = resolve_project(
        project="alpha",
        working_path=b / "src" / "x.py",
        registry=load_registry(),
    )

    assert resolved.project.name == "alpha"
    assert resolved.source is ResolutionSource.EXPLICIT


def test_unknown_explicit_project_errors_rather_than_falling_through(
    home: Path, tmp_path: Path
) -> None:
    """A wrong explicit name must fail, not silently degrade to the next tier.

    Falling through would answer from a different project than the one the
    caller named, which is the exact confusion this design prevents.
    """
    a = _project(tmp_path / "alpha", "alpha")
    register_workspace(a, name="alpha")

    with pytest.raises(UnknownProjectError) as excinfo:
        resolve_project(project="typo", working_path=a, registry=load_registry())

    assert "typo" in str(excinfo.value)
    assert excinfo.value.candidates == ["alpha"]


# --------------------------------------------------------------------------
# Tier 2 -- working_path
# --------------------------------------------------------------------------


def test_working_path_resolves_to_owning_project(home: Path, tmp_path: Path) -> None:
    """A path inside a registered project resolves to it."""
    a = _project(tmp_path / "alpha", "alpha")
    register_workspace(a, name="alpha")

    resolved = resolve_project(working_path=a / "src" / "x.py", registry=load_registry())

    assert resolved.project.name == "alpha"
    assert resolved.source is ResolutionSource.WORKING_PATH


def test_working_path_beats_startup_anchor(home: Path, tmp_path: Path) -> None:
    """The path the agent is editing beats where the server was launched.

    This is the whole point of per-call routing: one server, launched once,
    serving whichever project the agent is actually in.
    """
    a = _project(tmp_path / "alpha", "alpha")
    b = _project(tmp_path / "beta", "beta")
    register_workspace(a, name="alpha")
    register_workspace(b, name="beta")

    resolved = resolve_project(
        working_path=b / "src" / "x.py",
        anchor=a,
        registry=load_registry(),
    )

    assert resolved.project.name == "beta"


def test_working_path_prefers_the_longest_registered_prefix(home: Path, tmp_path: Path) -> None:
    """Nested registrations resolve to the inner project, not the outer one."""
    outer = _project(tmp_path / "mono", "outer")
    inner = _project(tmp_path / "mono" / "inner", "inner")
    register_workspace(outer, name="outer")
    register_workspace(inner, name="inner")

    resolved = resolve_project(working_path=inner / "src" / "x.py", registry=load_registry())

    assert resolved.project.name == "inner"


def test_unmatched_working_path_falls_through_to_the_next_tier(home: Path, tmp_path: Path) -> None:
    """A working_path outside every registered root is not fatal on its own.

    The contract specifies the first tier that *matches* wins, so an unmatched
    path defers rather than failing -- the anchor may still resolve it.
    """
    a = _project(tmp_path / "alpha", "alpha")
    register_workspace(a, name="alpha")

    resolved = resolve_project(
        working_path=tmp_path / "unregistered" / "x.py",
        anchor=a,
        registry=load_registry(),
    )

    assert resolved.project.name == "alpha"
    assert resolved.source is ResolutionSource.STARTUP_ANCHOR


# --------------------------------------------------------------------------
# Tier 3 -- startup anchor
# --------------------------------------------------------------------------


def test_startup_anchor_used_when_nothing_more_specific(home: Path, tmp_path: Path) -> None:
    """With no project and no working_path, the launch anchor decides."""
    a = _project(tmp_path / "alpha", "alpha")
    b = _project(tmp_path / "beta", "beta")
    register_workspace(a, name="alpha")
    register_workspace(b, name="beta")

    resolved = resolve_project(anchor=b, registry=load_registry())

    assert resolved.project.name == "beta"
    assert resolved.source is ResolutionSource.STARTUP_ANCHOR


def test_unregistered_anchor_still_resolves_for_a_lone_repo(home: Path, tmp_path: Path) -> None:
    """A single repo with no registry at all keeps working unchanged.

    Requiring registration for the lone-repo case would be a regression for
    every existing single-project user, so an anchor that is a real project root
    resolves directly.
    """
    solo = _project(tmp_path / "solo", "solo")

    resolved = resolve_project(anchor=solo, registry=Registry())

    assert resolved.project.name == "solo"
    assert resolved.project.project_root == solo
    assert resolved.source is ResolutionSource.STARTUP_ANCHOR


# --------------------------------------------------------------------------
# Tier 4 -- sole registered project
# --------------------------------------------------------------------------


def test_sole_registered_project_is_used_when_unambiguous(home: Path, tmp_path: Path) -> None:
    """One registered project and no other signal is not ambiguous."""
    a = _project(tmp_path / "alpha", "alpha")
    register_workspace(a, name="alpha")

    resolved = resolve_project(registry=load_registry())

    assert resolved.project.name == "alpha"
    assert resolved.source is ResolutionSource.SOLE_PROJECT


def test_sole_project_tier_does_not_apply_with_two_registered(home: Path, tmp_path: Path) -> None:
    """Two registered projects and no other signal must not pick one."""
    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    with pytest.raises(AmbiguousProjectError):
        resolve_project(registry=load_registry())


# --------------------------------------------------------------------------
# The ambiguity error
# --------------------------------------------------------------------------


def test_ambiguous_error_lists_candidates_and_remediation(home: Path, tmp_path: Path) -> None:
    """The error is actionable: it names the choices and how to see them."""
    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    with pytest.raises(AmbiguousProjectError) as excinfo:
        resolve_project(registry=load_registry())

    payload = excinfo.value.to_response()
    assert payload["error_code"] == "ambiguous_project"
    assert sorted(payload["candidates"]) == ["alpha", "beta"]
    assert payload["remediation"]
    assert "project" in payload["message"]


def test_empty_registry_with_no_anchor_is_ambiguous(home: Path, tmp_path: Path) -> None:
    """Nothing registered and nothing to infer from is a refusal, not a guess."""
    with pytest.raises(AmbiguousProjectError) as excinfo:
        resolve_project(registry=Registry())

    assert excinfo.value.candidates == []


def test_resolution_never_falls_back_to_a_default_project(home: Path, tmp_path: Path) -> None:
    """The core invariant: no silent default, ever.

    An unmatched working_path with no anchor and several registered projects
    must raise rather than pick the first, the newest, or the server's launch
    directory.
    """
    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    with pytest.raises(AmbiguousProjectError):
        resolve_project(
            working_path=tmp_path / "elsewhere" / "x.py",
            registry=load_registry(),
        )


def test_error_payload_is_json_serialisable(home: Path, tmp_path: Path) -> None:
    """Errors cross the MCP boundary, so the payload must serialise cleanly."""
    import json

    with pytest.raises(AmbiguousProjectError) as excinfo:
        resolve_project(registry=Registry())

    assert json.loads(json.dumps(excinfo.value.to_response()))
