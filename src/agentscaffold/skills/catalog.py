"""Progressive disclosure catalog — Step D.2.

Builds a catalog from SKILL.md frontmatter, enabling agents to discover
available skills with minimal token cost (~100 tokens per entry).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentscaffold.skills.generator import parse_skill_frontmatter


def build_catalog(skills_dirs: list[Path]) -> list[dict[str, Any]]:
    """Build a catalog from SKILL.md files across one or more directories.

    Args:
        skills_dirs: Directories to scan for SKILL.md files.

    Returns:
        List of catalog entries, each with keys:
        name, description, platforms, path.
        Sorted by name; duplicates (same name) are de-duplicated
        with first-seen winning.
    """
    seen: set[str] = set()
    entries: list[dict[str, Any]] = []

    for skills_dir in skills_dirs:
        if not skills_dir.is_dir():
            continue
        for skill_file in sorted(skills_dir.glob("*.md")):
            fm = parse_skill_frontmatter(skill_file)
            if not fm or "name" not in fm:
                continue
            name = fm["name"]
            if name in seen:
                continue
            seen.add(name)
            entries.append(
                {
                    "name": name,
                    "description": fm.get("description", ""),
                    "platforms": fm.get("platforms", []),
                    "path": fm.get("path", str(skill_file)),
                }
            )

    return sorted(entries, key=lambda e: e["name"])


def format_catalog_markdown(entries: list[dict[str, Any]]) -> str:
    """Render catalog entries as a markdown table.

    Args:
        entries: List of catalog entry dicts from ``build_catalog()``.

    Returns:
        Markdown string with a table of name + description.
    """
    if not entries:
        return "_No skills found._\n"

    lines = ["| Skill | Description |", "|-------|-------------|"]
    for e in entries:
        name = e.get("name", "")
        desc = e.get("description", "")
        lines.append(f"| {name} | {desc} |")
    return "\n".join(lines) + "\n"


def write_catalog(
    skills_dirs: list[Path],
    output_path: Path,
    dry_run: bool = False,
) -> Path:
    """Write a SKILLS_CATALOG.md file to output_path.

    Args:
        skills_dirs: Directories to scan.
        output_path: Destination file path.
        dry_run: If True, return path without writing.

    Returns:
        The output path.
    """
    entries = build_catalog(skills_dirs)
    content = "# Skills Catalog\n\n"
    content += format_catalog_markdown(entries)
    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
    return output_path
