"""Review quality scenarios: Dialectic Engine modules produce meaningful output."""

from __future__ import annotations

from eval.runner import EvalResult, collect_result, timed


class TestBriefGeneration:
    """Scenario: Review brief generation for plans."""

    @timed
    def test_brief_for_complete_plan(self, indexed_sim):
        """Brief for plan 042 (Complete) should have file impact and dependencies."""
        root, store, config = indexed_sim
        from agentscaffold.review.brief import format_brief_markdown, generate_brief

        brief = generate_brief(store, 42)
        md = format_brief_markdown(brief)

        plan_info = brief.get("plan", {})
        has_title = bool(plan_info.get("title"))
        has_status = bool(plan_info.get("status"))
        has_files = len(brief.get("file_profiles", [])) > 0

        total = 3
        passed = sum([has_title, has_status, has_files])

        result = EvalResult(
            scenario="brief_complete_plan",
            passed=passed == total,
            score=passed / total,
            expected="Brief with title, status, file impact",
            actual=f"title={has_title}, status={has_status}, files={has_files}",
            observations=[f"Markdown length: {len(md)}"],
            category="review",
        )
        collect_result(result)
        assert has_title
        assert has_status

    @timed
    def test_brief_for_missing_plan(self, indexed_sim):
        """Brief for non-existent plan should return gracefully."""
        root, store, config = indexed_sim
        from agentscaffold.review.brief import generate_brief

        brief = generate_brief(store, 9999)

        result = EvalResult(
            scenario="brief_missing_plan",
            passed=brief is not None,
            score=1.0 if brief is not None else 0.0,
            expected="Non-None brief (graceful degradation)",
            actual=f"Brief type: {type(brief).__name__}",
            category="review",
        )
        collect_result(result)
        assert brief is not None


class TestChallengesGeneration:
    """Scenario: Adversarial challenges for plans."""

    @timed
    def test_challenges_for_ready_plan(self, indexed_sim):
        """Plan 068 (Ready, execution engine) should have risk challenges."""
        root, store, config = indexed_sim
        from agentscaffold.review.challenges import generate_challenges

        challenges = generate_challenges(store, 68)

        result = EvalResult(
            scenario="challenges_ready_plan",
            passed=len(challenges) > 0,
            score=min(len(challenges) / 3, 1.0),
            expected="At least 1 challenge",
            actual=f"{len(challenges)} challenges generated",
            observations=[f"{c.category}: {c.text[:60]}" for c in challenges[:3]],
            category="review",
        )
        collect_result(result)
        assert len(challenges) > 0


class TestGapAnalysis:
    """Scenario: Gap analysis detects missing items."""

    @timed
    def test_gaps_for_draft_plan(self, indexed_sim):
        """Plan 075 (Draft, no tests) should flag missing test coverage."""
        root, store, config = indexed_sim
        from agentscaffold.review.gaps import generate_gaps

        gaps = generate_gaps(store, 75)

        result = EvalResult(
            scenario="gaps_draft_plan",
            passed=len(gaps) > 0,
            score=min(len(gaps) / 2, 1.0),
            expected="At least 1 gap identified",
            actual=f"{len(gaps)} gaps found",
            observations=[f"{g.category}: {g.text[:60]}" for g in gaps[:3]],
            category="review",
        )
        collect_result(result)
        assert len(gaps) > 0


class TestVerification:
    """Scenario: Post-implementation verification."""

    @timed
    def test_verify_complete_plan(self, indexed_sim):
        """Plan 042 (Complete) verification should check implementation exists."""
        root, store, config = indexed_sim
        from agentscaffold.review.verify import verify_implementation

        items = verify_implementation(store, 42)

        result = EvalResult(
            scenario="verify_complete_plan",
            passed=len(items) > 0,
            score=min(len(items) / 2, 1.0),
            expected="At least 1 verification item",
            actual=f"{len(items)} checks: {[(i.check, i.status) for i in items[:3]]}",
            category="review",
        )
        collect_result(result)
        assert len(items) > 0

    @timed
    def test_verify_partial_plan(self, indexed_sim):
        """Plan 068 (partially implemented) should flag incomplete steps."""
        root, store, config = indexed_sim
        from agentscaffold.review.verify import verify_implementation

        items = verify_implementation(store, 68)

        has_items = len(items) > 0
        result = EvalResult(
            scenario="verify_partial_plan",
            passed=has_items,
            score=1.0 if has_items else 0.0,
            expected="Verification flags for partially complete plan",
            actual=f"{len(items)} checks",
            observations=[f"{i.check}: {i.status}" for i in items[:5]],
            category="review",
        )
        collect_result(result)
        assert has_items


class TestRetroEnrichment:
    """Scenario: Retrospective enrichment from graph data."""

    @timed
    def test_retro_for_complete_plan(self, indexed_sim):
        """Retro enrichment for Plan 042 should include module insights."""
        root, store, config = indexed_sim
        from agentscaffold.review.feedback import generate_retro_enrichment

        insights = generate_retro_enrichment(store, 42)

        result = EvalResult(
            scenario="retro_complete_plan",
            passed=len(insights) > 0,
            score=min(len(insights) / 2, 1.0),
            expected="At least 1 retrospective insight",
            actual=f"{len(insights)} insights",
            observations=[f"{i.category}: {i.text[:60]}" for i in insights[:3]],
            category="review",
        )
        collect_result(result)
        assert len(insights) > 0


class TestCommunities:
    """Scenario: Community detection finds meaningful clusters."""

    @timed
    def test_communities_detected(self, indexed_sim):
        """Community detection should find at least 1 module cluster."""
        root, store, config = indexed_sim

        communities = store.query("MATCH (c:Community) RETURN c.id, c.label, c.fileCount")

        result = EvalResult(
            scenario="communities_detected",
            passed=len(communities) > 0,
            score=min(len(communities) / 2, 1.0),
            expected="At least 1 community",
            actual=f"{len(communities)} communities",
            observations=[f"{c['c.label']}: {c['c.fileCount']} files" for c in communities[:5]],
            category="review",
        )
        collect_result(result)

    @timed
    def test_community_membership(self, indexed_sim):
        """Files should be assigned to communities."""
        root, store, config = indexed_sim

        members = store.query(
            "MATCH (f:File)-[:MEMBER_OF_COMMUNITY]->(c:Community) RETURN f.path, c.label"
        )

        result = EvalResult(
            scenario="community_membership",
            passed=len(members) > 0,
            score=min(len(members) / 5, 1.0),
            expected="Files assigned to communities",
            actual=f"{len(members)} file-community memberships",
            category="review",
        )
        collect_result(result)
