"""Plan 251 C1: intent map is derived from the registry."""

from __future__ import annotations

import pytest

from agentscaffold.mcp.intents import (
    INTENT_PHRASES,
    MissingIntentMetadataError,
    assert_intent_coverage,
    intent_phrases,
)
from agentscaffold.mcp.registry import tool_names, tool_specs


def test_registry_names_match_intent_rows() -> None:
    names = set(tool_names())
    assert names == set(INTENT_PHRASES)
    assert_intent_coverage(list(tool_names()))


def test_empty_list_is_an_explicit_waiver() -> None:
    assert INTENT_PHRASES["scaffold_validate"] == []
    assert INTENT_PHRASES["scaffold_context"] == []
    specs = {spec.name: spec for spec in tool_specs()}
    assert specs["scaffold_validate"].intents == ()


def test_generation_fails_on_a_missing_row() -> None:
    with pytest.raises(MissingIntentMetadataError, match="no INTENT_PHRASES row"):
        assert_intent_coverage([*tool_names(), "scaffold_not_a_real_tool"])


def test_generated_intent_map_covers_every_registered_tool() -> None:
    from agentscaffold.agents.rule_policy import _intent_map_lines

    lines = "\n".join(_intent_map_lines(quote_intents=True))
    for name in tool_names():
        assert f"### {name}" in lines
    assert "empty list is an explicit waiver" in lines
    assert "High-Value" not in lines


def test_intent_phrases_snapshot_is_a_copy() -> None:
    snapshot = intent_phrases()
    snapshot["scaffold_orient"].append("not stored")
    assert "not stored" not in INTENT_PHRASES["scaffold_orient"]
