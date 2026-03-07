"""Tests for AGENTS.md and Cursor rules generation."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agentscaffold.cli import app


def test_agents_generate(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Generate AGENTS.md and verify it contains key sections."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        # Remove existing AGENTS.md to test generation from scratch
        agents_md = tmp_project / "AGENTS.md"
        if agents_md.exists():
            agents_md.unlink()

        result = cli_runner.invoke(app, ["agents", "generate"])
        assert result.exit_code == 0

        assert agents_md.is_file()
        content = agents_md.read_text()
        assert len(content) > 100

        # Key sections expected in any AGENTS.md
        content_lower = content.lower()
        assert "planning" in content_lower or "plan" in content_lower
        assert "test" in content_lower
    finally:
        os.chdir(orig_cwd)


def test_agents_generate_with_semi_autonomous(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Enable semi_autonomous in config and verify the section appears in AGENTS.md."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)

        # Update scaffold.yaml to enable semi_autonomous
        yaml_path = tmp_project / "scaffold.yaml"
        data = yaml.safe_load(yaml_path.read_text())
        data["semi_autonomous"] = {"enabled": True}
        yaml_path.write_text(yaml.dump(data))

        # Remove existing AGENTS.md
        agents_md = tmp_project / "AGENTS.md"
        if agents_md.exists():
            agents_md.unlink()

        result = cli_runner.invoke(app, ["agents", "generate"])
        assert result.exit_code == 0

        content = agents_md.read_text()
        content_lower = content.lower()
        assert (
            "semi" in content_lower or "autonomous" in content_lower or "session" in content_lower
        )
    finally:
        os.chdir(orig_cwd)


def test_cursor_setup(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Generate .cursor/rules.md and .cursor/rules/agentscaffold.md."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        # Remove existing rules.md
        rules_md = tmp_project / ".cursor" / "rules.md"
        if rules_md.exists():
            rules_md.unlink()
        intent_md = tmp_project / ".cursor" / "rules" / "agentscaffold.md"
        if intent_md.exists():
            intent_md.unlink()

        result = cli_runner.invoke(app, ["agents", "cursor"])
        assert result.exit_code == 0

        assert rules_md.is_file()
        content = rules_md.read_text()
        assert len(content) > 0
        content_lower = content.lower()
        assert "agents" in content_lower or "scaffold" in content_lower

        assert intent_md.is_file()
        intent_content = intent_md.read_text().lower()
        assert "tool selection policy" in intent_content
        assert "governance guardrails" in intent_content
        assert "intent map" in intent_content
        assert "scaffold_prepare_review" in intent_content
    finally:
        os.chdir(orig_cwd)


def test_windsurf_setup(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Generate .windsurfrules and verify policy sections exist."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        rules = tmp_project / ".windsurfrules"
        if rules.exists():
            rules.unlink()

        result = cli_runner.invoke(app, ["agents", "windsurf"])
        assert result.exit_code == 0
        assert rules.is_file()
        content = rules.read_text().lower()
        assert "tool selection policy" in content
        assert "fallback is allowed when" in content
        assert "governance guardrails" in content
        assert "intent map" in content
    finally:
        os.chdir(orig_cwd)


def test_claude_setup(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Generate CLAUDE.md and verify policy sections exist."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        rules = tmp_project / "CLAUDE.md"
        if rules.exists():
            rules.unlink()

        result = cli_runner.invoke(app, ["agents", "claude"])
        assert result.exit_code == 0
        assert rules.is_file()
        content = rules.read_text().lower()
        assert "tool selection policy" in content
        assert "required procedure" in content
        assert "governance guardrails" in content
        assert "scaffold_orient" in content
    finally:
        os.chdir(orig_cwd)


def test_prompt_export(tmp_project: Path, cli_runner: CliRunner) -> None:
    """Generate prompt snippet and verify policy sections exist."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        snippet = tmp_project / ".scaffold" / "prompt_snippet.txt"
        if snippet.exists():
            snippet.unlink()

        result = cli_runner.invoke(app, ["agents", "prompt"])
        assert result.exit_code == 0
        assert snippet.is_file()
        content = snippet.read_text().lower()
        assert "tool selection policy" in content
        assert "fallback is allowed when" in content
        assert "intent map" in content
        assert "scaffold_decision_context" in content
    finally:
        os.chdir(orig_cwd)


def test_agents_generate_no_config(tmp_path: Path, cli_runner: CliRunner) -> None:
    """agents generate without scaffold.yaml fails gracefully."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["agents", "generate"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_cursor_setup_no_config(tmp_path: Path, cli_runner: CliRunner) -> None:
    """agents cursor without scaffold.yaml fails gracefully."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["agents", "cursor"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_other_agent_exports_no_config(tmp_path: Path, cli_runner: CliRunner) -> None:
    """agents windsurf/claude/prompt without scaffold.yaml fail gracefully."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        for command in ("windsurf", "claude", "prompt"):
            result = cli_runner.invoke(app, ["agents", command])
            assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)
