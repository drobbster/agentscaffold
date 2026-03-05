"""Conversation replay: simulates a full Plan 139-style development session.

Sequence:
1. Index project
2. Start session with plan context
3. Generate review brief
4. Run devil's advocate (challenges)
5. Run expansion review (gaps)
6. Verify implementation
7. Generate retro enrichment
8. End session with summary
9. Verify session context for next session
"""

from __future__ import annotations

import shutil

from eval.conftest import SIM_PROJECT
from eval.runner import EvalResult, check_template_wellformedness, collect_result


class TestConversationReplay:
    """Full conversation replay simulating a development session."""

    def test_full_session_replay(self, tmp_path):
        """Replay a full development session: index -> review -> execute -> retro."""
        dest = tmp_path / "sim"
        shutil.copytree(SIM_PROJECT, dest)

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline
        from agentscaffold.graph.store import GraphStore

        db_path = dest / ".scaffold" / "graph.db"
        config = ScaffoldConfig()
        config.graph = GraphConfig(
            db_path=str(db_path),
            plans_dir="docs/ai/plans/",
            contracts_dir="docs/ai/contracts/",
            learnings_file="docs/ai/state/learnings_tracker.md",
        )

        observations = []
        errors = []

        # Step 1: Index the project
        try:
            summary = run_pipeline(dest, config)
            observations.append(f"Step 1 (Index): {summary.get('phases_completed', [])}")
        except Exception as exc:
            errors.append(f"Step 1 (Index) failed: {exc}")

        store = GraphStore(db_path)

        try:
            # Step 2: Start a session (simulating agent beginning work on Plan 068)
            try:
                from agentscaffold.graph.sessions import start_session

                session_id = start_session(
                    store, plan_numbers=[68], summary="Implementing execution engine"
                )
                observations.append(f"Step 2 (Session start): {session_id}")
            except Exception as exc:
                errors.append(f"Step 2 (Session start) failed: {exc}")
                session_id = None

            # Step 3: Generate review brief
            try:
                from agentscaffold.review.brief import format_brief_markdown, generate_brief

                brief = generate_brief(store, 68)
                brief_md = format_brief_markdown(brief)
                observations.append(f"Step 3 (Brief): {len(brief_md)} chars")
            except Exception as exc:
                errors.append(f"Step 3 (Brief) failed: {exc}")

            # Step 4: Generate adversarial challenges
            try:
                from agentscaffold.review.challenges import (
                    format_challenges_markdown,
                    generate_challenges,
                )

                challenges = generate_challenges(store, 68)
                format_challenges_markdown(challenges)
                observations.append(f"Step 4 (Challenges): {len(challenges)} challenges")
            except Exception as exc:
                errors.append(f"Step 4 (Challenges) failed: {exc}")

            # Step 5: Generate gap analysis
            try:
                from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps

                gaps = generate_gaps(store, 68)
                format_gaps_markdown(gaps)
                observations.append(f"Step 5 (Gaps): {len(gaps)} gaps")
            except Exception as exc:
                errors.append(f"Step 5 (Gaps) failed: {exc}")

            # Step 6: Simulate implementation -- add a new test file
            try:
                new_test = dest / "tests" / "unit" / "test_execution.py"
                new_test.write_text(
                    '"""Tests for execution engine."""\n\n'
                    "from libs.execution.engine import ExecutionEngine\n"
                    "from libs.data.router import DataRouter\n"
                    "from libs.risk.manager import RiskManager\n\n\n"
                    "def test_submit_buy():\n"
                    "    router = DataRouter()\n"
                    "    risk = RiskManager()\n"
                    "    engine = ExecutionEngine(router, risk)\n"
                    '    result = engine.submit("AAPL", {"signal": "buy", "strength": 0.5})\n'
                    '    assert result["status"] == "filled"\n'
                )

                if session_id:
                    from agentscaffold.graph.sessions import record_modification

                    record_modification(store, session_id, "tests/unit/test_execution.py")
                    record_modification(store, session_id, "libs/execution/engine.py")

                observations.append("Step 6 (Implementation): test file created, mods recorded")
            except Exception as exc:
                errors.append(f"Step 6 (Implementation) failed: {exc}")

            # Step 7: Verify implementation
            try:
                from agentscaffold.review.verify import verify_implementation

                verification = verify_implementation(store, 68)
                observations.append(f"Step 7 (Verify): {len(verification)} checks")
            except Exception as exc:
                errors.append(f"Step 7 (Verify) failed: {exc}")

            # Step 8: Generate retrospective enrichment
            try:
                from agentscaffold.review.feedback import (
                    format_retro_markdown,
                    generate_retro_enrichment,
                )

                retro = generate_retro_enrichment(store, 68)
                format_retro_markdown(retro)
                observations.append(f"Step 8 (Retro): {len(retro)} insights")
            except Exception as exc:
                errors.append(f"Step 8 (Retro) failed: {exc}")

            # Step 9: End session
            try:
                if session_id:
                    from agentscaffold.graph.sessions import end_session

                    end_session(
                        store, session_id, summary="Completed execution engine implementation"
                    )
                    observations.append("Step 9 (Session end): completed")
            except Exception as exc:
                errors.append(f"Step 9 (Session end) failed: {exc}")

            # Step 10: Verify session context is available for next session
            try:
                from agentscaffold.graph.sessions import get_session_context

                ctx = get_session_context(store, limit=3)
                _ = len(ctx.get("hot_files", []))
                observations.append(
                    f"Step 10 (Next context): hot_files={len(ctx.get('hot_files', []))}, "
                    f"plans={ctx.get('recent_plans', [])}"
                )
            except Exception as exc:
                errors.append(f"Step 10 (Next context) failed: {exc}")

        finally:
            store.close()

        # Overall result
        total_steps = 10
        passed_steps = total_steps - len(errors)

        result = EvalResult(
            scenario="conversation_replay",
            passed=len(errors) == 0,
            score=passed_steps / total_steps,
            expected=f"All {total_steps} steps complete without errors",
            actual=f"{passed_steps}/{total_steps} passed, {len(errors)} errors",
            observations=observations + [f"ERROR: {e}" for e in errors],
            category="conversation_replay",
        )
        collect_result(result)
        assert len(errors) == 0, f"Session replay errors: {errors}"

    def test_enriched_templates_during_session(self, tmp_path):
        """Templates rendered mid-session should include session context."""
        dest = tmp_path / "sim"
        shutil.copytree(SIM_PROJECT, dest)

        from agentscaffold.config import GraphConfig, ScaffoldConfig
        from agentscaffold.graph.pipeline import run_pipeline
        from agentscaffold.rendering import (
            get_default_context,
            get_graph_context,
            get_review_context,
            render_template,
        )

        db_path = dest / ".scaffold" / "graph.db"
        config = ScaffoldConfig()
        config.graph = GraphConfig(
            db_path=str(db_path),
            plans_dir="docs/ai/plans/",
            contracts_dir="docs/ai/contracts/",
            learnings_file="docs/ai/state/learnings_tracker.md",
        )

        run_pipeline(dest, config)

        graph_ctx = get_graph_context(config)
        review_ctx = get_review_context(plan_number=68, config=config)
        default_ctx = get_default_context(config)
        full_ctx = {**default_ctx, **graph_ctx, **review_ctx}

        rendered = render_template("prompts/plan_critique.md.j2", full_ctx)
        issues = check_template_wellformedness(rendered)

        result = EvalResult(
            scenario="mid_session_template",
            passed=len(issues) == 0 and len(rendered) > 100,
            score=1.0 if not issues and len(rendered) > 100 else 0.5,
            expected="Well-formed enriched template",
            actual=f"Length: {len(rendered)}, Issues: {issues}",
            category="conversation_replay",
        )
        collect_result(result)
        assert len(issues) == 0
