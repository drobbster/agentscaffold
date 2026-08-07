"""Tests for the enumerable MCP tool registry.

The registry exists so the conformance suite, the agent-file generator, and
``scaffold doctor --tools`` can all enumerate the tool surface from one place
instead of each parsing a list literal buried in the server.

The guarantee these tests protect is narrow and important: **the registry and
what the server advertises are the same surface.** An extraction that silently
dropped a tool would leave every consumer verifying a smaller surface than
clients actually see, and every one of them would pass.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from agentscaffold.mcp.registry import (
    ToolSpec,
    get_tool_spec,
    tool_names,
    tool_specs,
)

# Every tool advertised at the time of the extraction. Pinned deliberately: the
# point of the registry is that this list is enumerable, so a change to it
# should be a change someone made on purpose rather than a side effect.
EXPECTED_TOOLS = (
    "scaffold_context",
    "scaffold_impact",
    "scaffold_search",
    "scaffold_recall_governance",
    "scaffold_validate",
    "scaffold_query",
    "scaffold_stats",
    "scaffold_review_context",
    "scaffold_prepare_review",
    "scaffold_prepare_implementation",
    "scaffold_compare_plans",
    "scaffold_staleness_check",
    "scaffold_prepare_rewrite",
    "scaffold_prepare_retro",
    "scaffold_orient",
    "scaffold_find_studies",
    "scaffold_prior_experiments",
    "scaffold_find_adrs",
    "scaffold_decision_context",
    "scaffold_projects",
    "scaffold_record_finding",
    "scaffold_resolve_finding",
    "scaffold_record_findings_batch",
    "scaffold_record_backlog_item",
    "scaffold_resolve_backlog_item",
    "scaffold_diff_plan_vs_code",
    "scaffold_grep_graph",
    "scaffold_why_empty",
    "scaffold_next_action",
    "scaffold_begin_plan",
    "scaffold_complete_plan",
)


def test_the_registry_enumerates_exactly_what_the_server_advertises():
    """The property the extraction had to preserve, asserted directly.

    Not "the registry has 31 entries" -- that would pass just as happily if the
    server had stopped rendering one of them.
    """
    from agentscaffold.mcp.server import _get_tool_definitions

    advertised = _get_tool_definitions()
    assert [t.name for t in advertised] == list(tool_names())

    by_name = {spec.name: spec for spec in tool_specs()}
    for tool in advertised:
        spec = by_name[tool.name]
        assert tool.description == spec.description
        assert tool.inputSchema == spec.input_schema


def test_the_advertised_tool_set_is_the_expected_one():
    assert tool_names() == EXPECTED_TOOLS


def test_every_tool_accepts_working_path():
    """Per-call project scoping is the mechanism the whole multi-project model
    rests on. A tool that does not advertise ``working_path`` cannot be scoped,
    and would silently answer from the server's default project.
    """
    for spec in tool_specs():
        if spec.input_schema.get("type") != "object":
            continue
        props = spec.input_schema["properties"]
        assert "working_path" in props, f"{spec.name} cannot be scoped per call"
        assert props["working_path"]["type"] == "string"


def test_specs_are_well_formed():
    for spec in tool_specs():
        assert isinstance(spec, ToolSpec)
        assert spec.name.startswith("scaffold_")
        assert spec.description.strip()
        assert spec.input_schema.get("type") == "object"
        required = spec.input_schema.get("required", [])
        props = spec.input_schema.get("properties", {})
        missing = set(required) - set(props)
        assert not missing, f"{spec.name} requires undeclared {missing}"


def test_mutating_a_returned_schema_does_not_affect_the_next_caller():
    """Schemas are handed out, and the server used to mutate them in place to
    inject arguments. If specs were shared module state, one consumer poking at
    a schema would change what every later consumer sees.
    """
    first = tool_specs()[0]
    first.input_schema["properties"]["injected_by_a_test"] = {"type": "string"}

    fresh = tool_specs()[0]
    assert "injected_by_a_test" not in fresh.input_schema["properties"]


def test_get_tool_spec_finds_by_name_and_reports_absence():
    assert get_tool_spec("scaffold_orient").name == "scaffold_orient"
    assert get_tool_spec("scaffold_not_a_real_tool") is None


def test_the_registry_imports_without_the_mcp_sdk():
    """The generator has to enumerate tools whether or not the optional SDK is
    installed, so the registry must not import ``mcp``.

    Asserted by importing it in a subprocess with ``mcp`` blocked, rather than
    by reading the import lines -- a transitive import would satisfy the reading
    and fail the reality.
    """
    code = (
        "import sys\n"
        "class Blocker:\n"
        # find_spec, not find_module: the latter was removed in 3.12 and is
        # simply never called, so a blocker written against it blocks nothing
        # and this test would pass while proving nothing.
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'mcp' or name.startswith('mcp.'):\n"
        "            raise ImportError('mcp is not installed')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "from agentscaffold.mcp.registry import tool_names\n"
        "import json; print(json.dumps(list(tool_names())))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip()) == list(EXPECTED_TOOLS)


@pytest.mark.parametrize("spec", tool_specs(), ids=lambda s: s.name)
def test_each_tool_is_individually_addressable(spec: ToolSpec):
    """Proves the registry is parametrisable, which is what Phase F needs it for."""
    assert get_tool_spec(spec.name) is not None
