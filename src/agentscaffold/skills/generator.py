"""SKILL.md generator — Step D.1.

Converts domain standards markdown files into SKILL.md format with
progressive-disclosure YAML frontmatter for cross-platform AI agent discovery.

SKILL.md format::

    ---
    name: <slug>
    description: <one-line, ~100 tokens>
    platforms: [claude-code, cursor, windsurf]
    ---
    ## Catalog Entry
    <~100 token summary>

    ## Full Instructions
    <full standards content>

    ## Resources
    <related files / links>
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _slugify(name: str) -> str:
    """Convert a name to a lowercase slug."""
    return re.sub(r"[^a-z0-9_-]", "_", name.lower()).strip("_")


def _extract_first_paragraph(text: str) -> str:
    """Return the first non-heading paragraph from markdown text."""
    lines = text.splitlines()
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if current:
                break
            continue
        if stripped == "---":
            if current:
                break
            continue
        if stripped:
            current.append(stripped)
        elif current:
            break
    return " ".join(current)


def _build_catalog_entry(name: str, description: str, full_content: str) -> str:
    """Build a ~100-token catalog entry for progressive disclosure."""
    first_para = _extract_first_paragraph(full_content)
    summary = first_para[:400] if first_para else description
    return f"**{name}**: {summary}"


def generate_skill_md(
    name: str,
    description: str,
    full_content: str,
    platforms: list[str] | None = None,
    resources: list[str] | None = None,
) -> str:
    """Render a SKILL.md file from a standard's content.

    Args:
        name: Skill slug (e.g. "testing", "rl_patterns").
        description: One-line description for frontmatter.
        full_content: Full markdown body of the standard.
        platforms: Platforms that should use this skill.
        resources: Optional list of related resource paths/URLs.

    Returns:
        SKILL.md content as a string.
    """
    slug = _slugify(name)
    plats = platforms or ["claude-code", "cursor", "windsurf"]
    catalog_entry = _build_catalog_entry(name, description, full_content)

    frontmatter = "---\n"
    frontmatter += f"name: {slug}\n"
    frontmatter += f"description: {description}\n"
    frontmatter += f"platforms: [{', '.join(plats)}]\n"
    frontmatter += "---\n"

    body = f"## Catalog Entry\n\n{catalog_entry}\n\n"
    body += f"## Full Instructions\n\n{full_content.strip()}\n"

    if resources:
        body += "\n## Resources\n\n"
        for r in resources:
            body += f"- {r}\n"

    return frontmatter + "\n" + body + "\n"


def generate_skills_from_standards_dir(
    standards_dir: Path,
    output_dir: Path,
    dry_run: bool = False,
) -> list[Path]:
    """Generate SKILL.md files from all .md files in a standards directory.

    Args:
        standards_dir: Directory containing standards markdown files.
        output_dir: Output directory for SKILL.md files.
        dry_run: If True, return paths without writing files.

    Returns:
        List of output paths (written or would-be-written).
    """
    if not standards_dir.is_dir():
        return []

    written: list[Path] = []
    for std_file in sorted(standards_dir.glob("*.md")):
        if std_file.name == "README.md":
            continue
        content = std_file.read_text()
        name = std_file.stem
        description = _infer_description(name, content)
        skill_content = generate_skill_md(name, description, content)
        dest = output_dir / f"{name}.md"
        written.append(dest)
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(skill_content)
    return written


def _infer_description(name: str, content: str) -> str:
    """Infer a short description from the standard name and first heading."""
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped.lstrip("# ").strip()
    return name.replace("_", " ").title() + " standards"


def parse_skill_frontmatter(skill_md_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from a SKILL.md file.

    Returns dict with keys: name, description, platforms, path.
    Returns empty dict if the file has no frontmatter.
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return {}

    text = skill_md_path.read_text()
    if not text.startswith("---"):
        return {}

    end = text.find("---", 3)
    if end == -1:
        return {}

    raw_fm = text[3:end].strip()
    try:
        fm: dict[str, Any] = yaml.safe_load(raw_fm) or {}
    except Exception:
        return {}

    fm["path"] = str(skill_md_path)
    return fm
