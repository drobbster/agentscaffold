"""Safety boundary checks."""

from __future__ import annotations

import subprocess
from fnmatch import fnmatch

from rich.console import Console

from agentscaffold.config import ScaffoldConfig, load_config

console = Console()


def _get_modified_files() -> list[str] | None:
    """Get list of modified files via git. Returns None if git is unavailable."""
    for cmd in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--name-only", "main...HEAD"],
    ):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
                if files:
                    return files
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            files: list[str] = []
            for line in result.stdout.splitlines():
                if len(line) > 3:
                    files.append(line[3:].strip())
            return files
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def _matches_read_only(filepath: str, read_only_paths: list[str]) -> bool:
    """Check if a filepath matches any read-only path pattern."""
    for pattern in read_only_paths:
        if pattern.endswith("/"):
            if filepath.startswith(pattern) or filepath.startswith(pattern.rstrip("/")):
                return True
        elif fnmatch(filepath, pattern) or filepath == pattern:
            return True
    return False


def check_safety_boundaries(config: ScaffoldConfig | None = None) -> list[str]:
    """Check safety boundaries and return list of issues."""
    if config is None:
        config = load_config()

    if not config.semi_autonomous.enabled:
        return []

    issues: list[str] = []

    modified = _get_modified_files()
    if modified is None:
        issues.append(
            "WARNING: git is not available or not in a git repository -- "
            "cannot verify safety boundaries"
        )
        return issues

    read_only = config.semi_autonomous.safety.read_only_paths
    for filepath in modified:
        if _matches_read_only(filepath, read_only):
            issues.append(f"Read-only file was modified: {filepath}")

    return issues
