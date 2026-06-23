"""Tests for dynamic per-call project scoping in the MCP server.

The Cursor MCP server runs from a single fixed working directory and therefore
cannot infer which project the agent is editing. These tests cover the two new
mechanisms that let a caller drive scoping per call:

* ``_with_working_path_arg`` advertises a uniform ``working_path`` argument on
  every object-schema tool.
* ``_route_root_for_working_path`` resolves the owning project root for a given
  path (absolute or workspace-relative), so ``_dispatch_tool`` can chdir into it.
"""

from __future__ import annotations

import pytest

from agentscaffold.mcp import server

# ---------------------------------------------------------------------------
# Schema advertisement
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal stand-in matching the attribute the helper touches."""

    def __init__(self, schema):
        self.inputSchema = schema


def test_with_working_path_arg_injects_into_object_schemas():
    tools = [_FakeTool({"type": "object", "properties": {"query": {"type": "string"}}})]
    server._with_working_path_arg(tools)
    props = tools[0].inputSchema["properties"]
    assert "working_path" in props
    assert props["working_path"]["type"] == "string"
    # original properties are preserved
    assert "query" in props


def test_with_working_path_arg_creates_properties_when_missing():
    tools = [_FakeTool({"type": "object"})]
    server._with_working_path_arg(tools)
    assert "working_path" in tools[0].inputSchema["properties"]


def test_with_working_path_arg_does_not_overwrite_existing():
    sentinel = {"type": "string", "description": "caller-defined"}
    tools = [_FakeTool({"type": "object", "properties": {"working_path": sentinel}})]
    server._with_working_path_arg(tools)
    assert tools[0].inputSchema["properties"]["working_path"] is sentinel


def test_with_working_path_arg_ignores_non_object_schema():
    tools = [_FakeTool({"type": "string"}), _FakeTool(None)]
    server._with_working_path_arg(tools)  # must not raise
    assert "properties" not in (tools[0].inputSchema or {})


def test_real_tool_definitions_all_advertise_working_path():
    tools = server._with_working_path_arg(server._get_tool_definitions())
    missing = [
        t.name
        for t in tools
        if isinstance(t.inputSchema, dict)
        and t.inputSchema.get("type") == "object"
        and "working_path" not in t.inputSchema.get("properties", {})
    ]
    assert missing == []


# ---------------------------------------------------------------------------
# Path -> project routing
# ---------------------------------------------------------------------------


@pytest.fixture()
def multi_project_ws(tmp_path, monkeypatch):
    """A two-project workspace; cwd is set to the first project (like the MCP)."""
    (tmp_path / "workspace.yaml").write_text(
        "projects:\n" "  - name: alpha\n    path: alpha\n" "  - name: beta\n    path: beta\n"
    )
    for name in ("alpha", "beta"):
        proj = tmp_path / name
        (proj / "src").mkdir(parents=True)
        (proj / "scaffold.yaml").write_text(f"project:\n  name: {name}\n")
        (proj / "src" / "mod.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path / "alpha")
    return tmp_path


def test_route_none_and_empty_return_none(multi_project_ws):
    assert server._route_root_for_working_path(None) is None
    assert server._route_root_for_working_path("") is None


def test_route_absolute_file_resolves_owning_project(multi_project_ws):
    target = multi_project_ws / "beta" / "src" / "mod.py"
    root = server._route_root_for_working_path(str(target))
    assert root == (multi_project_ws / "beta").resolve()


def test_route_workspace_relative_path_resolves(multi_project_ws):
    root = server._route_root_for_working_path("beta/src/mod.py")
    assert root == (multi_project_ws / "beta").resolve()


def test_route_bogus_path_returns_none(multi_project_ws):
    assert server._route_root_for_working_path("/no/such/path/here.py") is None


def test_route_directory_resolves_owning_project(multi_project_ws):
    root = server._route_root_for_working_path(str(multi_project_ws / "alpha"))
    assert root == (multi_project_ws / "alpha").resolve()
