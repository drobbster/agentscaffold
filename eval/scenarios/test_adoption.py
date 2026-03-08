"""Behavioral adoption scenarios for MCP-first routing policy.

These tests do not call an LLM. They provide a conservative proxy for
rule adherence by measuring whether user prompts map to TOOL_INTENTS.
"""

from __future__ import annotations

from eval.runner import AdoptionResult, EvalResult, collect_adoption, collect_result


def _route_prompt(prompt: str) -> str | None:
    """Route prompt using production intent matching helper."""
    from agentscaffold.mcp.server import route_tool_from_prompt

    return route_tool_from_prompt(prompt)


def _measure_suite(
    suite_name: str,
    cases: list[tuple[str, str | None]],
    min_adherence_pct: float,
) -> None:
    matched = 0
    notes: list[str] = []

    for prompt, expected_tool in cases:
        got = _route_prompt(prompt)
        ok = got == expected_tool
        if ok:
            matched += 1
        else:
            notes.append(f"Miss: '{prompt}' expected {expected_tool}, got {got}")

    total = len(cases)
    adherence = (matched / total) * 100 if total else 0.0

    collect_adoption(
        AdoptionResult(
            suite=suite_name,
            total_prompts=total,
            matched_prompts=matched,
            adherence_pct=round(adherence, 1),
            notes=notes[:10],
        )
    )

    collect_result(
        EvalResult(
            scenario=f"adoption_{suite_name}",
            passed=adherence >= min_adherence_pct,
            score=adherence / 100,
            expected=f"Adherence >= {min_adherence_pct:.1f}%",
            actual=f"{adherence:.1f}% ({matched}/{total})",
            observations=notes[:10],
            category="adoption",
        )
    )


class TestIntentAdoption:
    """Tool-first adoption proxy from intent phrase routing coverage."""

    def test_exact_phrase_adherence(self):
        """Exact or near-exact phrasing should route reliably."""
        cases = [
            ("review plan X", "scaffold_prepare_review"),
            ("implement plan X", "scaffold_prepare_implementation"),
            ("where did we leave off", "scaffold_orient"),
            ("compare plans X and Y", "scaffold_compare_plans"),
            ("is plan X stale", "scaffold_staleness_check"),
            ("show me studies about X", "scaffold_find_studies"),
            ("any ADRs about X", "scaffold_find_adrs"),
            ("what's the decision history for plan X", "scaffold_decision_context"),
            ("retro on plan X", "scaffold_prepare_retro"),
        ]
        _measure_suite("exact", cases, min_adherence_pct=95.0)

    def test_paraphrase_adherence(self):
        """Paraphrased user language approximates real conversational variance."""
        cases = [
            ("Can we pressure-test plan X before coding?", "scaffold_prepare_review"),
            ("Let's start building plan X now", "scaffold_prepare_implementation"),
            ("Give me the latest blockers and what's next", "scaffold_orient"),
            ("Do these two plans step on each other?", "scaffold_compare_plans"),
            ("Has this plan gone out of date?", "scaffold_staleness_check"),
            ("Any prior experiments about cache invalidation?", "scaffold_find_studies"),
            ("Which architecture decision governs this area?", "scaffold_find_adrs"),
            ("Trace the rationale chain behind plan X", "scaffold_decision_context"),
            ("Let's do the post-implementation retrospective", "scaffold_prepare_retro"),
            ("Stress-test plan X assumptions before implementation", "scaffold_prepare_review"),
            ("Ready to build plan X, what do I need first?", "scaffold_prepare_implementation"),
            ("Compare plan X against plan Y for collisions", "scaffold_compare_plans"),
            ("Has plan X changed enough to require a refresh?", "scaffold_staleness_check"),
            ("Show decision lineage for plan X from ADR to spike", "scaffold_decision_context"),
            ("Any experiments or studies on this approach already?", "scaffold_find_studies"),
        ]
        _measure_suite("paraphrase", cases, min_adherence_pct=80.0)

    def test_negative_control_precision(self):
        """Unrelated prompts should avoid false positive routing."""
        cases = [
            ("what time is it right now", None),
            ("summarize this JSON file format quickly", None),
            ("create a python function to parse csv rows", None),
            ("explain what recursion means", None),
            ("draft release notes for version 1.2.3", None),
            ("what is the weather in san francisco", None),
            ("help me reword this paragraph", None),
            ("generate a regex for UUIDs", None),
        ]
        _measure_suite("negative_control", cases, min_adherence_pct=95.0)
