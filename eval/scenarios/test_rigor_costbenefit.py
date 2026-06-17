"""Rigor cost-benefit proxy scenarios."""

from __future__ import annotations

from eval.runner import (
    EvalResult,
    RigorCostResult,
    collect_result,
    collect_rigor_cost,
    estimate_tokens,
)

PLAN_NUMBER = 42


def _render_bundle(store, rigor: str) -> RigorCostResult:
    from agentscaffold.config import ScaffoldConfig, apply_rigor_preset
    from agentscaffold.review.challenges import format_challenges_markdown, generate_challenges
    from agentscaffold.review.feedback import generate_retro_enrichment
    from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps
    from agentscaffold.review.verify import format_verification_markdown, verify_implementation

    config = apply_rigor_preset(ScaffoldConfig(rigor=rigor))
    sections: list[str] = [f"# Rigor Bundle: {rigor}"]
    review_calls = 0
    challenges = []
    gaps = []
    verification_items = []
    retro_items = []

    gates = config.gates
    if gates.review_to_ready.devils_advocate:
        challenges = generate_challenges(store, PLAN_NUMBER)
        sections.append(format_challenges_markdown(challenges))
        review_calls += 1

    if gates.review_to_ready.expansion_review:
        gaps = generate_gaps(store, PLAN_NUMBER)
        sections.append(format_gaps_markdown(gaps))
        review_calls += 1

    if gates.review_to_ready.security_review:
        sections.append(
            "## Security Review Gate\n\nSecurity review gate enabled for this preset.\n"
        )
        review_calls += 1

    if (
        gates.in_progress_to_complete.tests_pass
        or gates.in_progress_to_complete.validation_commands
    ):
        verification_items = verify_implementation(store, PLAN_NUMBER)
        sections.append(format_verification_markdown(verification_items))
        review_calls += 1

    if gates.in_progress_to_complete.retrospective:
        retro_items = generate_retro_enrichment(store, PLAN_NUMBER)
        sections.append(
            "## Retrospective Enrichment\n\n" + "\n".join(item.text for item in retro_items) + "\n"
        )
        review_calls += 1

    if gates.in_progress_to_complete.domain_implementation_review:
        sections.append("## Domain Implementation Review Gate\n\nDomain review gate enabled.\n")
        review_calls += 1

    findings = store.query(
        "SELECT id FROM ReviewFinding WHERE planNumber = ? AND status = 'open'",
        {"plan_number": PLAN_NUMBER},
    )
    artifact = "\n\n".join(sections)
    return RigorCostResult(
        rigor=rigor,
        artifact_tokens=estimate_tokens(artifact),
        review_calls=review_calls,
        challenges=len(challenges),
        gaps=len(gaps),
        verification_items=len(verification_items),
        findings=len(findings),
    )


class TestRigorCostBenefit:
    """Measure existing rigor presets without changing their semantics."""

    def test_rigor_cost_benefit_proxy_is_monotonic(self, indexed_sim):
        root, store, config = indexed_sim

        results = [_render_bundle(store, rigor) for rigor in ("minimal", "standard", "strict")]
        for result in results:
            collect_rigor_cost(result)

        token_costs = [r.artifact_tokens for r in results]
        review_calls = [r.review_calls for r in results]
        thoroughness = [r.thoroughness for r in results]
        passed = (
            token_costs == sorted(token_costs)
            and review_calls == sorted(review_calls)
            and thoroughness == sorted(thoroughness)
        )

        collect_result(
            EvalResult(
                scenario="rigor_cost_benefit_proxy",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Cost and thoroughness proxy are monotonic with rigor",
                actual=(f"tokens={token_costs}, calls={review_calls}, thoroughness={thoroughness}"),
                observations=[
                    f"{r.rigor}: tokens={r.artifact_tokens}, calls={r.review_calls}, "
                    f"thoroughness={r.thoroughness}"
                    for r in results
                ],
                category="rigor",
            )
        )

        assert passed
