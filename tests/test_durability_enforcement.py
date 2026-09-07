"""Plan 251: gitignore detection, including the parent-directory case."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentscaffold.doctor import DoctorContext, check_guidance_ignored
from agentscaffold.rendering import (
    GUIDANCE_IGNORE_REMEDIATION,
    ensure_agents_guidance_pointer,
    ignored_guidance_files,
    is_git_ignored,
    write_managed_block,
)


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_gitignore_file_pattern(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True)
    target = rules / "agentscaffold.mdc"
    target.write_text("x")
    (root / ".gitignore").write_text(".cursor/rules/agentscaffold.mdc\n")
    _git_init(root)
    assert is_git_ignored(root, ".cursor/rules/agentscaffold.mdc")
    assert target in ignored_guidance_files(root)


def test_parent_directory_exclude_defeats_file_negation(tmp_path: Path) -> None:
    """`.cursor/` as a directory ignore cannot be undone by a file negation."""
    root = tmp_path / "repo"
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True)
    target = rules / "agentscaffold.mdc"
    target.write_text("x")
    (root / ".gitignore").write_text(".cursor/\n!.cursor/rules/agentscaffold.mdc\n")
    _git_init(root)
    assert is_git_ignored(root, ".cursor/rules/agentscaffold.mdc")
    assert "!.cursor/rules/" in GUIDANCE_IGNORE_REMEDIATION
    assert "!.cursor/rules/agentscaffold.mdc" not in GUIDANCE_IGNORE_REMEDIATION.split("Use")[1]


def test_directory_scoped_remediation_reincludes_rules(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True)
    target = rules / "agentscaffold.mdc"
    target.write_text("x")
    (root / ".gitignore").write_text(".cursor/*\n!.cursor/rules/\n")
    _git_init(root)
    assert not is_git_ignored(root, ".cursor/rules/agentscaffold.mdc")
    assert target not in ignored_guidance_files(root)


def test_git_info_exclude(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("# x\n")
    _git_init(root)
    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("AGENTS.md\n")
    assert is_git_ignored(root, "AGENTS.md")


def test_doctor_reports_ignored_guidance(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    rules = root / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "agentscaffold.mdc").write_text("x")
    (root / ".gitignore").write_text(".cursor/\n")
    _git_init(root)
    result = check_guidance_ignored(DoctorContext(project_root=root, mcp_config_path=root / "x"))
    assert result.status == "warn"
    assert "!.cursor/rules/" in (result.remediation or "")


def test_agents_pointer_is_outside_managed_markers(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("# Human title\n\nKeep this paragraph.\n")
    write_managed_block(path, "generated routing")
    status = ensure_agents_guidance_pointer(path)
    assert status == "inserted"
    text = path.read_text()
    assert "agentscaffold-guidance-pointer" in text
    assert "Keep this paragraph." in text
    pointer_at = text.index("agentscaffold-guidance-pointer")
    managed_at = text.index("BEGIN AGENTSCAFFOLD MANAGED SECTION")
    assert pointer_at < managed_at
    write_managed_block(path, "generated routing v2")
    again = path.read_text()
    assert "Keep this paragraph." in again
    assert "generated routing v2" in again
    assert again.count("agentscaffold-guidance-pointer") == 1
