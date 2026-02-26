"""Tests for study lifecycle commands (create, lint, list)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from agentscaffold.cli import app


def test_study_create(tmp_project: Path, cli_runner: CliRunner) -> None:
    """study create produces a file with the STU-YYYY-MM-DD-slug format."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["study", "create", "Attention vs MLP"])
        assert result.exit_code == 0
        today = date.today().isoformat()
        expected_name = f"STU-{today}-attention-vs-mlp.md"
        study_file = tmp_project / "docs/studies" / expected_name
        assert study_file.is_file(), f"Expected study file: {expected_name}"
        content = study_file.read_text()
        assert len(content) > 50
    finally:
        os.chdir(orig_cwd)


def _write_valid_study(studies_dir: Path, name: str = "STU-2026-01-01-test.md") -> Path:
    """Write a minimal valid study file."""
    study_file = studies_dir / name
    study_file.write_text(
        "---\n"
        "title: Test Study\n"
        "status: complete\n"
        "tags: [test, unit]\n"
        "---\n\n"
        "## Overview\n\nA test study.\n\n"
        "## Hypothesis\n\nWe hypothesize X > Y.\n\n"
        "## Methodology\n\nRun both variants.\n\n"
        "## Results\n\n| Variant | Score |\n|---------|-------|\n| A | 0.8 |\n\n"
        "## Conclusion\n\nA is better.\n"
    )
    return study_file


def test_study_lint_valid(tmp_project: Path, cli_runner: CliRunner) -> None:
    """lint a valid study file -- should pass."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        studies_dir = tmp_project / "docs/studies"
        _write_valid_study(studies_dir)
        result = cli_runner.invoke(app, ["study", "lint"])
        assert result.exit_code == 0
        assert "PASS" in result.output
    finally:
        os.chdir(orig_cwd)


def test_study_lint_missing_frontmatter(tmp_project: Path, cli_runner: CliRunner) -> None:
    """lint a study without YAML frontmatter fails."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        studies_dir = tmp_project / "docs/studies"
        bad_study = studies_dir / "STU-2026-01-01-bad.md"
        bad_study.write_text(
            "## Overview\n\nNo frontmatter.\n\n"
            "## Hypothesis\n\n## Methodology\n\n## Results\n\n## Conclusion\n"
        )
        result = cli_runner.invoke(app, ["study", "lint"])
        assert result.exit_code == 1
        assert "FAIL" in result.output
    finally:
        os.chdir(orig_cwd)


def test_study_list_empty(tmp_project: Path, cli_runner: CliRunner) -> None:
    """list with no study files shows a warning."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        # Remove any STU-*.md files that might exist
        studies_dir = tmp_project / "docs/studies"
        for f in studies_dir.glob("STU-*.md"):
            f.unlink()

        result = cli_runner.invoke(app, ["study", "list"])
        assert result.exit_code == 0
        assert "No study files" in result.output
    finally:
        os.chdir(orig_cwd)


def test_study_list_with_studies(tmp_project: Path, cli_runner: CliRunner) -> None:
    """list shows studies with their metadata."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        studies_dir = tmp_project / "docs/studies"
        _write_valid_study(studies_dir, "STU-2026-01-15-widget-test.md")
        result = cli_runner.invoke(app, ["study", "list"])
        assert result.exit_code == 0
        assert "STU-2026-01-15-widget-test.md" in result.output
    finally:
        os.chdir(orig_cwd)
