"""The server delivers the working procedure in its initialize result."""

from __future__ import annotations

import inspect
import re

import pytest

from agentscaffold.agents.rule_policy import generate_server_instructions
from agentscaffold.mcp.registry import tool_specs
from agentscaffold.mcp.resources import GUIDANCE_ROUTING_URI


def test_instructions_are_bounded_and_deterministic() -> None:
    text = generate_server_instructions()
    assert text.strip()
    assert len(text) <= 1500
    assert generate_server_instructions() == text


def test_instructions_name_the_procedure_and_the_full_policy() -> None:
    text = generate_server_instructions()
    for required in (
        "working_path",
        "scaffold_session_start",
        "scaffold_orient",
        "scaffold_session_end",
        GUIDANCE_ROUTING_URI,
    ):
        assert required in text
    assert text.index("scaffold_session_start") < text.index("scaffold_orient")


def test_every_tool_named_in_the_instructions_is_registered() -> None:
    registered = {spec.name for spec in tool_specs()}
    named = set(re.findall(r"scaffold_\w+", generate_server_instructions()))
    assert named
    assert named <= registered, sorted(named - registered)


def test_generator_takes_no_project_input() -> None:
    assert not inspect.signature(generate_server_instructions).parameters


def _initialization_instructions() -> str | None:
    pytest.importorskip("mcp", reason="mcp extra not installed")
    from agentscaffold.mcp.server import _build_server

    return _build_server().create_initialization_options().instructions


def test_initialize_result_carries_the_instructions(monkeypatch) -> None:
    monkeypatch.delenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", raising=False)
    assert _initialization_instructions() == generate_server_instructions()


@pytest.mark.parametrize("value", ["0", "false", "off", "OFF", " False "])
def test_opt_out_removes_the_instructions(monkeypatch, value: str) -> None:
    monkeypatch.setenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", value)
    assert _initialization_instructions() is None


@pytest.mark.parametrize("value", ["1", "true", "on", ""])
def test_other_values_keep_the_instructions(monkeypatch, value: str) -> None:
    monkeypatch.setenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", value)
    assert _initialization_instructions() == generate_server_instructions()
