"""Integration tests for project resolution inside tool dispatch (Plan 249, A6b).

Steps A5 and A6 built the resolution chain and proved it in isolation. These
tests cover the part that actually changes behaviour for a user: that
``_dispatch_tool`` routes through it, and that an unresolvable call returns a
structured refusal instead of quietly answering from somewhere plausible.

The behaviour being replaced federated across every registered project whenever
the root was not a recognised project, which meant a question about one project
could be answered with another project's data and nothing in the response said
so.

Resolution deliberately runs *before* the graph is opened, so a call that cannot
be scoped costs nothing and cannot touch a database it had no business reading.
Several tests assert that ordering by failing if ``open_graph`` is reached.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


@pytest.fixture(autouse=True)
def restore_cwd():
    """Put the working directory back after every test in this module.

    ``_dispatch_tool`` chdirs into the resolved project, and these tests point it
    at ``tmp_path`` directories that pytest later deletes. Without this the
    process is left sitting in a removed directory and unrelated suites that
    resolve anything from the cwd fail in confusing ways.
    """
    original = os.getcwd()
    try:
        yield
    finally:
        os.chdir(original)


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the user-level registry."""
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target))
    return target


@pytest.fixture()
def stub_graph(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stub the graph layer and record the cwd each open happens under."""
    import agentscaffold.config as config_mod
    import agentscaffold.graph as graph_mod
    from agentscaffold.config import ScaffoldConfig

    calls: dict = {"opens": [], "cwd": []}

    def _open(*args, **kwargs):
        # Records where resolution landed, then bails. Dispatch turns the failure
        # into an error dict, which is fine: these tests are about routing, and
        # reaching this point at all already proves the call was not refused.
        calls["opens"].append(kwargs)
        calls["cwd"].append(os.getcwd())
        raise RuntimeError("stub: graph open not supported in this test")

    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: ScaffoldConfig())
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)
    monkeypatch.setattr(graph_mod, "open_graph", _open)
    return calls


def _project(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(f"project:\n  name: {name}\n")
    return root


def _two_project_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text(
        "projects:\n  - name: alpha\n    path: alpha\n  - name: beta\n    path: beta\n"
    )
    for name in ("alpha", "beta"):
        (_project(ws / name, name) / "src").mkdir()
    return ws


def test_unresolvable_call_returns_ambiguous_project_not_federation(
    home: Path, tmp_path: Path, stub_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The core behaviour change: refuse rather than answer from everywhere.

    Previously this path set ``all_projects=True`` and returned a federated
    answer with no indication that the question had not been understood.

    Ambiguity has to be genuine to be worth refusing, so this registers two
    competing projects and then anchors the server at neither. With nothing
    registered the anchor would be the only candidate and answering is correct.
    """
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    bare = tmp_path / "not-a-project"
    bare.mkdir()
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: bare)

    result = _dispatch_tool("scaffold_orient", {})

    assert result["error_code"] == "ambiguous_project"
    assert sorted(result["candidates"]) == ["alpha", "beta"]
    assert result["remediation"]
    assert stub_graph["opens"] == [], "refused calls must not open the graph"


def test_working_path_routes_dispatch_to_the_owning_project(
    home: Path, tmp_path: Path, stub_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A call carrying working_path is scoped to that path's project."""
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool

    ws = _two_project_workspace(tmp_path)
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: ws / "alpha")

    _dispatch_tool("scaffold_orient", {"working_path": str(ws / "beta" / "src")})

    assert Path(stub_graph["cwd"][0]).resolve() == (ws / "beta").resolve()


def test_anchor_is_used_when_no_working_path_is_given(
    home: Path, tmp_path: Path, stub_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a working_path the launch anchor still decides, as before."""
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool

    ws = _two_project_workspace(tmp_path)
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: ws / "alpha")

    _dispatch_tool("scaffold_orient", {})

    assert Path(stub_graph["cwd"][0]).resolve() == (ws / "alpha").resolve()


def test_lone_repo_dispatch_is_unaffected(
    home: Path, tmp_path: Path, stub_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard for the single-project user with no registry at all."""
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool

    solo = _project(tmp_path / "solo", "solo")
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: solo)

    _dispatch_tool("scaffold_orient", {})

    assert Path(stub_graph["cwd"][0]).resolve() == solo.resolve()


def test_restrict_to_denies_a_call_outside_the_allowlist(
    home: Path, tmp_path: Path, stub_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--restrict-to is enforced at dispatch, not merely advertised.

    Section 11 of Plan 249 counts this as a mitigation for the widened
    in-process read surface, so it has to deny before the graph is opened.
    """
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool, configure_restrict_to

    ws = _two_project_workspace(tmp_path)
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: ws / "alpha")
    configure_restrict_to(["alpha"])
    try:
        result = _dispatch_tool("scaffold_orient", {"working_path": str(ws / "beta")})
    finally:
        configure_restrict_to(None)

    assert result["error_code"] == "restricted_project"
    assert result["candidates"] == ["alpha"]
    assert stub_graph["opens"] == [], "denied calls must not open the graph"


def test_restrict_to_permits_a_call_inside_the_allowlist(
    home: Path, tmp_path: Path, stub_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allowlist must not deny the projects it names."""
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool, configure_restrict_to

    ws = _two_project_workspace(tmp_path)
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: ws / "alpha")
    configure_restrict_to(["alpha"])
    try:
        _dispatch_tool("scaffold_orient", {"working_path": str(ws / "alpha" / "src")})
    finally:
        configure_restrict_to(None)

    assert Path(stub_graph["cwd"][0]).resolve() == (ws / "alpha").resolve()


def test_missing_required_argument_still_short_circuits_resolution(
    home: Path, tmp_path: Path, stub_graph: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan 246's arg validation keeps precedence over project resolution.

    An agent that omitted a required argument should be told that, not sent
    away to think about project scoping first.
    """
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool

    bare = tmp_path / "not-a-project"
    bare.mkdir()
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: bare)

    result = _dispatch_tool("scaffold_impact", {})

    assert result["missing_argument"] == "file_or_symbol"
    assert "error_code" not in result
