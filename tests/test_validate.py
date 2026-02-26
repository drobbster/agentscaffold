"""Tests for validation checks (prohibitions, secrets, integration, safety)."""

from __future__ import annotations

import os
from pathlib import Path

from agentscaffold.config import ScaffoldConfig
from agentscaffold.validate.integration import check_integration
from agentscaffold.validate.prohibitions import check_prohibitions
from agentscaffold.validate.safety import check_safety_boundaries
from agentscaffold.validate.secrets import check_secrets


def test_validate_clean_project(tmp_project: Path) -> None:
    """validate on a fresh init project passes basic checks."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        prohib_issues = check_prohibitions()
        assert prohib_issues == []
    finally:
        os.chdir(orig_cwd)


def test_prohibitions_no_emojis_clean(tmp_project: Path) -> None:
    """check_prohibitions on a clean project with emojis disabled returns no issues."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        cfg = ScaffoldConfig(prohibitions={"emojis": False})
        issues = check_prohibitions(config=cfg)
        assert issues == []
    finally:
        os.chdir(orig_cwd)


def test_prohibitions_detects_emojis(tmp_project: Path) -> None:
    """Write a file with an emoji, check_prohibitions detects it when enabled."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        src_dir = tmp_project / "src"
        src_dir.mkdir(exist_ok=True)
        bad_file = src_dir / "emoji_file.py"
        bad_file.write_text("# This has an emoji \U0001f600\nprint('hello')\n")

        cfg = ScaffoldConfig(prohibitions={"emojis": True})
        issues = check_prohibitions(config=cfg)
        assert len(issues) > 0
        assert any("emoji" in issue.lower() for issue in issues)
    finally:
        os.chdir(orig_cwd)


def test_prohibitions_emojis_disabled_ignores(tmp_project: Path) -> None:
    """When emojis prohibition is disabled, emoji files are not flagged."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        src_dir = tmp_project / "src"
        src_dir.mkdir(exist_ok=True)
        bad_file = src_dir / "emoji_file.py"
        bad_file.write_text("# This has an emoji \U0001f600\n")

        cfg = ScaffoldConfig(prohibitions={"emojis": False})
        issues = check_prohibitions(config=cfg)
        assert issues == []
    finally:
        os.chdir(orig_cwd)


def test_secrets_clean(tmp_project: Path) -> None:
    """check_secrets on a clean project returns no issues."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        issues = check_secrets()
        assert issues == []
    finally:
        os.chdir(orig_cwd)


def test_secrets_detects_hardcoded(tmp_project: Path) -> None:
    """Write a file with a hardcoded password, check_secrets detects it."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        src_dir = tmp_project / "src"
        src_dir.mkdir(exist_ok=True)
        bad_file = src_dir / "config_bad.py"
        bad_file.write_text('password = "supersecretvalue123"\n')  # pragma: allowlist secret

        issues = check_secrets()
        assert len(issues) > 0
        assert any("secret" in issue.lower() for issue in issues)
    finally:
        os.chdir(orig_cwd)


def test_integration_clean(tmp_project: Path) -> None:
    """check_integration on a fresh project passes (no contract refs to break)."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        issues = check_integration()
        assert issues == []
    finally:
        os.chdir(orig_cwd)


def test_safety_boundaries_not_enabled(tmp_project: Path) -> None:
    """Returns empty list when semi_autonomous is not enabled."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        cfg = ScaffoldConfig(semi_autonomous={"enabled": False})
        issues = check_safety_boundaries(config=cfg)
        assert issues == []
    finally:
        os.chdir(orig_cwd)


def test_secrets_ignores_placeholders(tmp_project: Path) -> None:
    """Placeholder values like YOUR_KEY_HERE are not flagged."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        src_dir = tmp_project / "src"
        src_dir.mkdir(exist_ok=True)
        safe_file = src_dir / "config_safe.py"
        safe_file.write_text('api_key = "YOUR_API_KEY_HERE"\n')  # pragma: allowlist secret

        issues = check_secrets()
        assert issues == []
    finally:
        os.chdir(orig_cwd)
