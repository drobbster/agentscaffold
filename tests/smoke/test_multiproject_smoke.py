"""End-to-end smoke: one MCP server answering for two projects in a workspace.

These are deliberately not unit tests and deliberately not the conformance
suite. Conformance asks "does each tool honour each guarantee?" against
in-process dispatch. This asks the cruder question that a user would:
**does the whole path work when driven through the real entry points?**

So these go through the CLI as a subprocess -- ``scaffold index``,
``scaffold doctor``, ``scaffold workspace`` -- rather than importing the
functions behind them. That is the point: the failures this catches are the ones
that live between the pieces, in argument wiring, console-script packaging,
stdout discipline and exit codes, none of which an in-process call exercises.
A tool can be perfectly scoped and still be unreachable because its command
never registered.

Marked ``smoke`` so they can be run alone (``pytest -m smoke``) at milestone
boundaries, and skipped when iterating on units.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

#: The installed console script, which is what users and MCP clients actually
#: invoke -- ``scaffold mcp`` is the canonical entry ``scaffold mcp install``
#: writes into a client config. Not ``python -m agentscaffold.cli``: that has no
#: ``__main__`` guard, so it exits silently with status 0, which would have made
#: every assertion here fail against an empty result rather than a real run.
SCAFFOLD = Path(sys.executable).parent / "scaffold"

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        not SCAFFOLD.exists(),
        reason=f"console script not installed at {SCAFFOLD}; smoke needs the packaged entry point",
    ),
]


def _run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI the way a user does: the console script, from a directory."""
    environment = {**os.environ, **(env or {})}
    return subprocess.run(
        [str(SCAFFOLD), *args],
        cwd=str(cwd),
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """A two-project workspace with an isolated user-level home."""
    from tests.fixtures.multiproject import build_two_project_workspace

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(home))
    return build_two_project_workspace(tmp_path / "ws"), {"AGENTSCAFFOLD_HOME": str(home)}


@pytest.mark.smoke
def test_indexing_each_project_populates_one_shared_graph(workspace):
    """The core multi-project promise, driven end to end.

    Two projects, two index runs, one database -- with each project's rows
    attributable to it. Asserted on the database rather than on the console
    summary, because a summary can report success over an empty write.
    """
    ws, env = workspace

    for project in (ws.alpha, ws.beta):
        result = _run("index", cwd=project, env=env)
        assert result.returncode == 0, f"index failed in {project.name}: {result.stderr[-800:]}"

    assert ws.db_path.exists(), "indexing produced no database at the configured path"

    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    store = DuckPGQBackend(ws.db_path)
    try:
        rows = store.query("SELECT DISTINCT project FROM Function ORDER BY project")
    finally:
        store.close()

    assert {r["project"] for r in rows} == set(ws.names), (
        f"expected both projects namespaced in one graph, got {rows}"
    )


@pytest.mark.smoke
def test_a_tool_called_from_each_project_answers_about_that_project(workspace):
    """The user-visible symptom the whole phase exists to prevent.

    A symbol both projects define, asked from each, must come back with that
    project's answer -- not a plausible answer about the other one.
    """
    from tests.fixtures.multiproject import (
        ALPHA_ONLY_SYMBOL,
        BETA_ONLY_SYMBOL,
        SHARED_SYMBOL,
    )

    ws, env = workspace
    for project in (ws.alpha, ws.beta):
        assert _run("index", cwd=project, env=env).returncode == 0

    from agentscaffold.mcp.server import _dispatch_tool
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(ws.alpha, name=ws.alpha_name)
    register_workspace(ws.beta, name=ws.beta_name)

    expected = {ws.alpha_name: ALPHA_ONLY_SYMBOL, ws.beta_name: BETA_ONLY_SYMBOL}
    for name, own_symbol in expected.items():
        payload = _dispatch_tool(
            "scaffold_context",
            {"symbol": SHARED_SYMBOL, "working_path": str(ws.source_file(name))},
        )
        callees = [c.get("name") for c in (payload.get("callees") or [])]
        assert own_symbol in callees, f"asked from {name}, got {callees}"


@pytest.mark.smoke
def test_doctor_reports_a_healthy_two_project_workspace(workspace):
    """``doctor`` is the command a user runs when something looks wrong.

    Its job at a milestone is to be *quiet* on a healthy setup: a diagnostic
    that cries wolf on a correct installation trains people to ignore it.
    """
    ws, env = workspace
    for project in (ws.alpha, ws.beta):
        assert _run("index", cwd=project, env=env).returncode == 0

    from agentscaffold.workspace_registry import register_workspace

    register_workspace(ws.alpha, name=ws.alpha_name)
    register_workspace(ws.beta, name=ws.beta_name)

    result = _run("doctor", cwd=ws.alpha, env=env)
    assert result.returncode == 0, (
        f"doctor failed on a healthy workspace:\n{result.stdout[-1500:]}\n{result.stderr[-800:]}"
    )


@pytest.mark.smoke
def test_the_workspace_lists_both_projects_from_either_directory(workspace):
    """ "Which project am I in?" has to be answerable from inside either one."""
    ws, env = workspace
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(ws.alpha, name=ws.alpha_name)
    register_workspace(ws.beta, name=ws.beta_name)

    for project in (ws.alpha, ws.beta):
        result = _run("workspace", "list", cwd=project, env=env)
        assert result.returncode == 0, f"workspace list failed: {result.stderr[-500:]}"
        for name in ws.names:
            assert name in result.stdout, (
                f"{name} missing from workspace list run in {project.name}:\n{result.stdout}"
            )


@pytest.mark.smoke
def test_the_mcp_server_advertises_its_whole_tool_surface_over_stdio(workspace):
    """The tools have to be reachable, not merely correct.

    Exercises the packaged server the way a client does -- spawn it, speak MCP
    over stdio, read the advertised list -- because every conformance guarantee
    is worthless if the server cannot start or never lists the tool.
    """
    ws, env = workspace
    from agentscaffold.mcp.registry import tool_names

    request = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )

    proc = subprocess.run(
        [str(SCAFFOLD), "mcp"],
        cwd=str(ws.alpha),
        env={**os.environ, **env},
        input=request,
        capture_output=True,
        text=True,
        timeout=300,
    )

    advertised: set[str] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == 2:
            advertised = {t["name"] for t in message.get("result", {}).get("tools", [])}

    assert advertised, (
        "server advertised no tools over stdio; "
        f"stdout={proc.stdout[-1200:]!r} stderr={proc.stderr[-1200:]!r}"
    )
    assert advertised == set(tool_names()), (
        f"stdio surface differs from the registry; "
        f"missing={set(tool_names()) - advertised} extra={advertised - set(tool_names())}"
    )
