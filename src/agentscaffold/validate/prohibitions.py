"""Prohibition checks (e.g., emoji, hardcoded secrets)."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from agentscaffold.config import ScaffoldConfig, find_config, load_config

console = Console()

EMOJI_PATTERN = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"  # dingbats
    "\U000024c2-\U0001f251"  # enclosed characters
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols extended-A
    "\U00002600-\U000026ff"  # misc symbols
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"  # zero width joiner
    "\U0000200b-\U0000200f"  # zero width spaces
    "\U00002028-\U00002029"  # line/paragraph separator
    "\U00002b50"  # star
    "\U00002b55"  # circle
    "\U00002934-\U00002935"  # arrows
    "\U00003030"  # wavy dash
    "\U000025aa-\U000025ab"  # squares
    "\U000025fb-\U000025fe"  # squares
    "\U0000231a-\U0000231b"  # watch/hourglass
    "\U000023e9-\U000023f3"  # media controls
    "\U000023f8-\U000023fa"  # media controls
    "]+"
)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}

SCAN_EXTENSIONS = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".txt",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".html",
    ".css",
    ".sh",
    ".cfg",
    ".ini",
    ".rst",
}


def _find_project_root() -> Path | None:
    cfg_path = find_config()
    if cfg_path is not None:
        return cfg_path.parent
    return None


def _should_skip(path: Path) -> bool:
    """Return True if the path should be skipped during scanning."""
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    return False


def _is_scannable(path: Path) -> bool:
    """Return True if the file extension is one we should scan."""
    return path.suffix.lower() in SCAN_EXTENSIONS


def _scan_files(root: Path, directories: list[str]) -> list[Path]:
    """Collect scannable files from the given directories under root."""
    files: list[Path] = []
    for dir_name in directories:
        scan_dir = root / dir_name
        if not scan_dir.is_dir():
            continue
        for path in scan_dir.rglob("*"):
            if path.is_file() and not _should_skip(path) and _is_scannable(path):
                files.append(path)
    return files


def _check_emojis(root: Path) -> list[str]:
    """Scan key directories for emoji characters."""
    issues: list[str] = []
    scan_dirs = ["src", "libs", "docs/ai", "tests"]
    files = _scan_files(root, scan_dirs)

    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            matches = EMOJI_PATTERN.findall(line)
            if matches:
                rel = path.relative_to(root)
                emoji_str = " ".join(matches)
                issues.append(f"{rel}:{line_no}: found prohibited emoji: {emoji_str}")

    return issues


def _check_patterns(root: Path, patterns: list[str]) -> list[str]:
    """Scan for custom prohibited patterns."""
    issues: list[str] = []
    scan_dirs = ["src", "libs", "docs/ai", "tests"]
    files = _scan_files(root, scan_dirs)

    compiled: list[tuple[str, re.Pattern[str]]] = []
    for pat_str in patterns:
        try:
            compiled.append((pat_str, re.compile(pat_str)))
        except re.error as exc:
            issues.append(f"Invalid prohibition pattern '{pat_str}': {exc}")
            continue

    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue

        rel = path.relative_to(root)
        for line_no, line in enumerate(content.splitlines(), start=1):
            for pat_str, pat_re in compiled:
                if pat_re.search(line):
                    issues.append(f"{rel}:{line_no}: found prohibited pattern: {pat_str}")

    return issues


def check_prohibitions(config: ScaffoldConfig | None = None) -> list[str]:
    """Check for prohibited patterns and return list of violations."""
    if config is None:
        config = load_config()

    root = _find_project_root()
    if root is None:
        return ["Could not find project root (no scaffold.yaml found)"]

    issues: list[str] = []

    if config.prohibitions.emojis:
        issues.extend(_check_emojis(root))

    if config.prohibitions.patterns:
        issues.extend(_check_patterns(root, config.prohibitions.patterns))

    return issues
