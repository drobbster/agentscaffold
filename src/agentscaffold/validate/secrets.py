"""Secrets and credential exposure checks."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config

console = Console()

SCAN_EXTENSIONS = {".py", ".yaml", ".yml", ".json", ".md", ".env", ".toml"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}
SKIP_FILENAMES = {".env.example", ".env.sample"}

SENSITIVE_ASSIGNMENT = re.compile(
    r"""(?:password|secret|api_key|apikey|token|private_key)\s*[=:]\s*["']([^"'${\s]{8,})["']""",
    re.IGNORECASE,
)

AWS_KEY_PATTERN = re.compile(r"AKIA[0-9A-Z]{16}")

SENSITIVE_HEX_BASE64 = re.compile(
    r"""(?:password|secret|api_key|apikey|token|private_key)\s*[=:]\s*["']?"""
    r"([A-Za-z0-9+/=]{32,})(?:[\"'\s]|$)",
    re.IGNORECASE,
)

PLACEHOLDER_PATTERNS = re.compile(
    r"\$\{|YOUR_|CHANGE_ME|REPLACE_ME|TODO|<.*>|xxx|PLACEHOLDER",
    re.IGNORECASE,
)

ENV_VALUE_LINE = re.compile(r"^([A-Z_]+)\s*=\s*(.+)$")


def _find_project_root() -> Path | None:
    cfg_path = find_config()
    if cfg_path is not None:
        return cfg_path.parent
    return None


def _should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    return path.name in SKIP_FILENAMES


def _is_scannable(path: Path) -> bool:
    return path.suffix.lower() in SCAN_EXTENSIONS


def _check_env_file(path: Path, rel: Path) -> list[str]:
    """Check .env files for actual secret values (not placeholders)."""
    issues: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return issues

    for line_no, line in enumerate(content.splitlines(), start=1):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        match = ENV_VALUE_LINE.match(line_stripped)
        if not match:
            continue

        key, value = match.group(1), match.group(2).strip().strip("\"'")
        sensitive_keys = {"password", "secret", "token", "api_key", "apikey", "private_key"}
        is_sensitive = any(s in key.lower() for s in sensitive_keys)

        if is_sensitive and value and not PLACEHOLDER_PATTERNS.search(value):
            issues.append(f"{rel}:{line_no}: possible secret in env var '{key}'")

    return issues


def check_secrets() -> list[str]:
    """Check for exposed secrets and return list of issues."""
    issues: list[str] = []

    root = _find_project_root()
    if root is None:
        return ["Could not find project root (no scaffold.yaml found)"]

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip(path):
            continue
        if not _is_scannable(path):
            continue

        rel = path.relative_to(root)

        if path.suffix == ".env":
            issues.extend(_check_env_file(path, rel))
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            if PLACEHOLDER_PATTERNS.search(line):
                continue

            for match in SENSITIVE_ASSIGNMENT.finditer(line):
                issues.append(f"{rel}:{line_no}: possible hardcoded secret")

            for match in AWS_KEY_PATTERN.finditer(line):
                issues.append(f"{rel}:{line_no}: possible AWS access key")

    return issues
