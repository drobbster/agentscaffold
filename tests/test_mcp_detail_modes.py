"""Plan 246: detail=summary vs full."""

from __future__ import annotations

from agentscaffold.mcp.detail import apply_detail


def test_summary_drops_markdown_and_truncates_lists() -> None:
    payload = {
        "challenges": [{"text": f"c{i}"} for i in range(10)],
        "challenges_markdown": "# big",
        "gaps": [{"text": f"g{i}"} for i in range(8)],
        "meta": {},
    }
    summary = apply_detail(payload, "summary")
    full = apply_detail(payload, "full")

    assert "challenges_markdown" not in summary
    assert len(summary["challenges"]) == 5
    assert summary.get("challenges_truncated") == 5
    assert "challenges_markdown" in full
    assert len(full["challenges"]) == 10
    assert len(str(summary)) < len(str(full))


def test_summary_tolerates_non_string_keys() -> None:
    """Regression (Plan 248): summary trim must not crash on int-keyed evidence.

    Review evidence generators (e.g. gaps.py SIMILAR_PATTERN) legitimately produce
    ``dict[int, int]`` values such as ``similar_plans`` (plan number -> shared-file
    count). Before the fix ``_trim`` called ``k.endswith(...)`` on every key and
    raised ``AttributeError: 'int' object has no attribute 'endswith'``.
    """
    payload = {
        "gaps": [
            {
                "category": "SIMILAR_PATTERN",
                "text": "overlap",
                "severity": "medium",
                "evidence": {
                    "similar_plans": {240: 3, 241: 2},
                    "note": "keep me",
                    "nested_markdown": "#drop-me",
                },
            }
        ],
        "gaps_markdown": "#drop",
        "similar_plans": {247: 1},
    }

    summary = apply_detail(payload, "summary")

    assert "gaps_markdown" not in summary
    evidence = summary["gaps"][0]["evidence"]
    assert evidence["similar_plans"] == {240: 3, 241: 2}
    assert evidence["note"] == "keep me"
    # String keys keep their conventions even alongside non-string keys.
    assert "nested_markdown" not in evidence
    assert summary["similar_plans"] == {247: 1}


def test_full_mode_unaffected_by_non_string_keys() -> None:
    payload = {"gaps": [{"evidence": {"similar_plans": {240: 3}}}], "gaps_markdown": "#x"}
    full = apply_detail(payload, "full")
    assert "gaps_markdown" in full
    assert full["gaps"][0]["evidence"]["similar_plans"] == {240: 3}
