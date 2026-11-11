"""Trigger-phrase matching for the Claude prompt hook."""

from __future__ import annotations

from agentscaffold.mcp.intents import match_intent


def test_longest_phrase_wins() -> None:
    table = {
        "scaffold_prepare_review": ["review plan X"],
        "scaffold_prepare_implementation": ["review plan X before we implement plan Y"],
    }
    assert (
        match_intent("please review plan 12 before we implement plan 9", table)
        == "scaffold_prepare_implementation"
    )


def test_equal_length_keeps_the_first_phrase() -> None:
    table = {
        "first": ["review plan X"],
        "second": ["review plan Y"],
    }
    assert match_intent("review plan 4", table) == "first"


def test_placeholders_match_one_or_more_words() -> None:
    table = {"scaffold_find_adrs": ["which ADR governs X"]}
    assert match_intent("which ADR governs the storage layout", table) == "scaffold_find_adrs"


def test_a_phrase_with_one_fixed_word_does_not_match() -> None:
    table = {"too_short": ["update X"]}
    assert match_intent("update the plan", table) is None


def test_no_match_returns_nothing() -> None:
    assert match_intent("hello there", {"scaffold_orient": ["where did we leave off"]}) is None
