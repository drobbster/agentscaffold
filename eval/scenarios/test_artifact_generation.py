"""Artifact generation eval scenarios — Step E.5.

Tests that scaffold agents cursor/claude/windsurf setup commands produce
correct, well-formed output files.  Uses the sim_project scaffold.yaml
which includes reviews, enforcement, and platform sections.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.evaluator import score_frontmatter_correctness
from eval.runner import EvalResult, collect_result


def _load_sim_config(sim_root: Path):
    from agentscaffold.config import load_config

    config_path = sim_root / "scaffold.yaml"
    return load_config(config_path)


# ---------------------------------------------------------------------------
# TestCursorMcpJsonGeneration (2 scenarios)
# ---------------------------------------------------------------------------


class TestCursorMcpJsonGeneration:
    """scaffold agents cursor writes .cursor/mcp.json correctly."""

    def test_mcp_json_written_on_first_run(self, fresh_sim, monkeypatch):
        from agentscaffold.agents.cursor import write_cursor_mcp_json

        # Plan 253 skips the write when a shared client entry already exists.
        # Isolate so this scenario measures the lone-repo first-run path.
        monkeypatch.setattr(
            "agentscaffold.agents.cursor._canonical_entry_installed",
            lambda: False,
        )
        monkeypatch.setattr(
            "agentscaffold.mcp.install.is_registered_root",
            lambda _root: False,
        )

        cursor_dir = fresh_sim / ".cursor"
        write_cursor_mcp_json(cursor_dir)

        mcp_path = cursor_dir / "mcp.json"
        exists = mcp_path.exists()
        if exists:
            data = json.loads(mcp_path.read_text())
            has_servers = "mcpServers" in data
            has_agentscaffold = "agentscaffold" in data.get("mcpServers", {})
        else:
            has_servers = has_agentscaffold = False

        passed = exists and has_servers and has_agentscaffold
        collect_result(
            EvalResult(
                scenario="artifact_mcp_json_first_run",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected=".cursor/mcp.json with mcpServers.agentscaffold entry",
                actual=f"exists={exists}, has_servers={has_servers}, "
                f"has_agentscaffold={has_agentscaffold}",
                category="artifact",
            )
        )
        assert passed, f"mcp.json not correctly written: exists={exists}"

    def test_mcp_json_not_overwritten_if_exists(self, fresh_sim):
        from agentscaffold.agents.cursor import write_cursor_mcp_json

        cursor_dir = fresh_sim / ".cursor"
        cursor_dir.mkdir(parents=True, exist_ok=True)
        mcp_path = cursor_dir / "mcp.json"

        original_content = '{"mcpServers": {"custom": {"command": "my-custom-mcp"}}}'
        mcp_path.write_text(original_content)

        write_cursor_mcp_json(cursor_dir)

        after_content = mcp_path.read_text()
        unchanged = after_content == original_content

        collect_result(
            EvalResult(
                scenario="artifact_mcp_json_not_overwritten",
                passed=unchanged,
                score=1.0 if unchanged else 0.0,
                expected="Existing mcp.json not overwritten",
                actual=f"unchanged={unchanged}",
                category="artifact",
            )
        )
        assert unchanged, "Existing mcp.json was overwritten"


# ---------------------------------------------------------------------------
# TestCursorRuleTaxonomy (4 scenarios)
# ---------------------------------------------------------------------------


class TestCursorRuleTaxonomy:
    """Cursor rule files have correct frontmatter flags."""

    @pytest.fixture()
    def cursor_rules_dir(self, fresh_sim):
        """Run cursor setup on a fresh sim project; return .cursor/rules/ dir."""
        from unittest.mock import patch

        config = _load_sim_config(fresh_sim)
        from agentscaffold.agents.cursor import run_cursor_setup

        with (
            patch(
                "agentscaffold.agents.cursor.find_config",
                return_value=fresh_sim / "scaffold.yaml",
            ),
            patch("agentscaffold.agents.cursor.load_config", return_value=config),
            patch("agentscaffold.config.find_config", return_value=fresh_sim / "scaffold.yaml"),
            patch("agentscaffold.config.load_config", return_value=config),
            patch.object(Path, "cwd", return_value=fresh_sim),
        ):
            run_cursor_setup()

        return fresh_sim / ".cursor" / "rules"

    def test_agentscaffold_rule_always_apply(self, cursor_rules_dir):
        """agentscaffold.mdc MCP routing rule should alwaysApply (Cursor loads .mdc)."""
        rule_file = cursor_rules_dir / "agentscaffold.mdc"
        assert rule_file.exists(), f"agentscaffold.mdc not found in {cursor_rules_dir}"

        content = rule_file.read_text()
        has_always_apply = "alwaysApply: true" in content
        has_compression = "Call Compression Discipline" in content

        collect_result(
            EvalResult(
                scenario="artifact_governance_rule_always_apply",
                passed=has_always_apply and has_compression,
                score=1.0 if has_always_apply and has_compression else 0.0,
                expected="agentscaffold.mdc has alwaysApply: true + Call Compression Discipline",
                actual=(f"has_always_apply={has_always_apply}, has_compression={has_compression}"),
                category="artifact",
            )
        )
        assert has_always_apply, "agentscaffold.mdc missing alwaysApply: true"
        assert has_compression, "agentscaffold.mdc missing Call Compression Discipline"

    def test_reviewer_rule_always_apply_false(self, cursor_rules_dir):
        """Per-reviewer rules should have alwaysApply: false."""
        reviewer_file = cursor_rules_dir / "quant_architect.mdc"
        assert reviewer_file.exists(), f"quant_architect.mdc not in {cursor_rules_dir}"

        content = reviewer_file.read_text()
        has_false = "alwaysApply: false" in content

        collect_result(
            EvalResult(
                scenario="artifact_reviewer_rule_always_apply_false",
                passed=has_false,
                score=1.0 if has_false else 0.0,
                expected="quant_architect.mdc has alwaysApply: false",
                actual=f"has_false={has_false}",
                category="artifact",
            )
        )
        assert has_false, f"quant_architect.mdc missing 'alwaysApply: false': {content[:200]}"

    def test_domain_reviewer_rule_has_globs(self, cursor_rules_dir):
        """Reviewer with file_patterns should have globs: in frontmatter."""
        reviewer_file = cursor_rules_dir / "quant_architect.mdc"
        assert reviewer_file.exists()

        content = reviewer_file.read_text()
        has_globs = "globs:" in content

        collect_result(
            EvalResult(
                scenario="artifact_reviewer_rule_has_globs",
                passed=has_globs,
                score=1.0 if has_globs else 0.0,
                expected="quant_architect.mdc (with file_patterns) has globs: field",
                actual=f"has_globs={has_globs}",
                category="artifact",
            )
        )
        assert (
            has_globs
        ), f"quant_architect.mdc missing globs despite file_patterns: {content[:300]}"

    def test_no_file_patterns_reviewer_no_globs(self, cursor_rules_dir):
        """Reviewer without file_patterns falls back to alwaysApply: false (no globs)."""
        reviewer_file = cursor_rules_dir / "devils_advocate.mdc"
        assert reviewer_file.exists(), f"devils_advocate.mdc not in {cursor_rules_dir}"

        content = reviewer_file.read_text()
        no_globs = "globs:" not in content
        has_always_apply_false = "alwaysApply: false" in content

        passed = no_globs and has_always_apply_false
        collect_result(
            EvalResult(
                scenario="artifact_no_patterns_reviewer_no_globs",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="devils_advocate.mdc has no globs, has alwaysApply: false",
                actual=f"no_globs={no_globs}, has_always_apply_false={has_always_apply_false}",
                category="artifact",
            )
        )
        assert passed, f"devils_advocate.mdc unexpected content: {content[:300]}"


# ---------------------------------------------------------------------------
# TestCursorPerReviewerRules (5 scenarios)
# ---------------------------------------------------------------------------


class TestCursorPerReviewerRules:
    """Per-reviewer .cursor/rules/<reviewer>.mdc files are well-formed."""

    @pytest.fixture()
    def rules_dir(self, fresh_sim):
        from unittest.mock import patch

        config = _load_sim_config(fresh_sim)
        from agentscaffold.agents.cursor import run_cursor_setup

        with (
            patch(
                "agentscaffold.agents.cursor.find_config",
                return_value=fresh_sim / "scaffold.yaml",
            ),
            patch("agentscaffold.agents.cursor.load_config", return_value=config),
            patch("agentscaffold.config.find_config", return_value=fresh_sim / "scaffold.yaml"),
            patch("agentscaffold.config.load_config", return_value=config),
            patch.object(Path, "cwd", return_value=fresh_sim),
        ):
            run_cursor_setup()
        return fresh_sim / ".cursor" / "rules"

    def test_reviewer_files_created_for_each(self, rules_dir):
        """Both configured reviewers have rule files."""
        quant = rules_dir / "quant_architect.mdc"
        devil = rules_dir / "devils_advocate.mdc"
        both_exist = quant.exists() and devil.exists()
        collect_result(
            EvalResult(
                scenario="artifact_reviewer_files_created",
                passed=both_exist,
                score=1.0 if both_exist else (0.5 if quant.exists() or devil.exists() else 0.0),
                expected="quant_architect.mdc and devils_advocate.mdc created",
                actual=f"quant={quant.exists()}, devil={devil.exists()}",
                category="artifact",
            )
        )
        assert both_exist, "Not all reviewer rule files were created"

    def test_reviewer_description_present_and_nonempty(self, rules_dir):
        """description: field in frontmatter is non-empty."""
        content = (rules_dir / "quant_architect.mdc").read_text()
        fm_result = score_frontmatter_correctness(content, ["description"], name="quant_architect")
        collect_result(fm_result)
        assert fm_result.passed, f"quant_architect.mdc missing description: {fm_result.actual}"

    def test_reviewer_body_contains_mcp_tool_calls(self, rules_dir):
        """Rule body instructs use of scaffold_record_finding."""
        content = (rules_dir / "quant_architect.mdc").read_text()
        has_tool = "scaffold_record_finding" in content

        collect_result(
            EvalResult(
                scenario="artifact_reviewer_rule_has_mcp_tool",
                passed=has_tool,
                score=1.0 if has_tool else 0.0,
                expected="scaffold_record_finding mentioned in quant_architect.mdc",
                actual=f"has_tool={has_tool}",
                category="artifact",
            )
        )
        assert has_tool, "quant_architect.mdc missing scaffold_record_finding instruction"

    def test_reviewer_rule_always_apply_is_false(self, rules_dir):
        """alwaysApply: false so the rule loads on-demand."""
        for name in ("quant_architect", "devils_advocate"):
            content = (rules_dir / f"{name}.mdc").read_text()
            assert "alwaysApply: false" in content, f"{name}.mdc missing 'alwaysApply: false'"

        collect_result(
            EvalResult(
                scenario="artifact_reviewer_rules_not_always_apply",
                passed=True,
                score=1.0,
                expected="Both reviewer rules have alwaysApply: false",
                actual="Verified for quant_architect and devils_advocate",
                category="artifact",
            )
        )

    def test_reviewer_rule_globs_from_file_patterns(self, rules_dir):
        """quant_architect (has file_patterns) includes globs: in frontmatter."""
        content = (rules_dir / "quant_architect.mdc").read_text()
        has_globs = "globs:" in content
        collect_result(
            EvalResult(
                scenario="artifact_reviewer_rule_globs_from_patterns",
                passed=has_globs,
                score=1.0 if has_globs else 0.0,
                expected="globs: present in quant_architect.mdc from file_patterns",
                actual=f"has_globs={has_globs}",
                category="artifact",
            )
        )
        assert has_globs


# ---------------------------------------------------------------------------
# TestWindsurfCascadeStubs (1 scenario)
# ---------------------------------------------------------------------------


class TestWindsurfCascadeStubs:
    """Windsurf agent stubs reference MCP tools."""

    def test_windsurf_stub_created_and_references_tools(self, fresh_sim):
        config = _load_sim_config(fresh_sim)
        from agentscaffold.agents.windsurf import write_windsurf_agent_stubs

        written = write_windsurf_agent_stubs(config, fresh_sim)
        assert written, "No windsurf agent stubs were written"

        for path in written:
            assert path.exists(), f"Stub not written: {path}"
            content = path.read_text()
            has_mcp = "scaffold_record_finding" in content

            collect_result(
                EvalResult(
                    scenario=f"artifact_windsurf_stub_{path.stem}",
                    passed=has_mcp,
                    score=1.0 if has_mcp else 0.0,
                    expected=f"{path.name} references scaffold_record_finding",
                    actual=f"has_mcp={has_mcp}",
                    category="artifact",
                )
            )
            assert has_mcp, f"{path.name} missing MCP tool reference"
