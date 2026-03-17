"""Governance document format validation.

Checks that studies, ADRs, and learnings follow the expected formats
so the knowledge graph can parse them correctly.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from agentscaffold.config import ScaffoldConfig


def check_governance_formats(config: ScaffoldConfig | None = None) -> list[str]:
    """Validate governance doc formats. Returns list of issue strings."""
    root = Path.cwd()
    issues: list[str] = []

    gc = config.graph if config else None

    studies_dir = root / (gc.studies_dir if gc else "docs/studies/")
    learnings_file = root / (gc.learnings_file if gc else "docs/ai/state/learnings_tracker.md")

    issues.extend(_check_studies(studies_dir))
    issues.extend(_check_learnings(learnings_file))

    return issues


def _check_studies(studies_dir: Path) -> list[str]:
    """Check that study files have valid YAML frontmatter."""
    issues: list[str] = []
    if not studies_dir.is_dir():
        return issues

    required_fields = {"study_id", "title", "study_type", "status"}

    for f in sorted(studies_dir.glob("STU-*.md")):
        text = f.read_text(errors="replace")

        # Check for code-fenced frontmatter (common agent mistake)
        if text.startswith("```"):
            issues.append(
                f"{f.name}: YAML frontmatter is wrapped in a code fence "
                f"(starts with a code fence). Remove the code fence wrapper."
            )
            continue

        # Check for missing YAML frontmatter
        if not text.startswith("---"):
            issues.append(
                f"{f.name}: Missing YAML frontmatter. File must start with "
                f"--- delimiter. See study_template.md for the required format."
            )
            continue

        # Parse frontmatter
        end = text.find("---", 3)
        if end == -1:
            issues.append(f"{f.name}: Unclosed YAML frontmatter (no closing ---).")
            continue

        try:
            fm = yaml.safe_load(text[3:end])
        except yaml.YAMLError as exc:
            issues.append(f"{f.name}: Invalid YAML frontmatter: {exc}")
            continue

        if not isinstance(fm, dict):
            issues.append(f"{f.name}: Frontmatter is not a YAML mapping.")
            continue

        # Check required fields
        missing = required_fields - set(fm.keys())
        if missing:
            issues.append(f"{f.name}: Missing required frontmatter fields: {sorted(missing)}")

    return issues


_LEARNING_ROW_RE = re.compile(r"^\|\s*(?P<id>L\d+-\d+)\s*\|(?P<rest>.*)$", re.MULTILINE)


def _check_learnings(learnings_file: Path) -> list[str]:
    """Check that learnings table rows have the expected column count."""
    issues: list[str] = []
    if not learnings_file.is_file():
        return issues

    text = learnings_file.read_text(errors="replace")
    short_rows: list[str] = []

    for m in _LEARNING_ROW_RE.finditer(text):
        row_id = m.group("id")
        rest = m.group("rest")
        # Count pipe-delimited columns in the rest of the row
        cols = [c.strip() for c in rest.split("|") if c.strip()]
        # Expected: Learning | Target | Status = 3 columns after ID
        if len(cols) < 3:
            short_rows.append(row_id)

    if short_rows:
        issues.append(
            f"learnings_tracker.md: {len(short_rows)} rows missing Status column "
            f"(expected 4 columns: | ID | Learning | Target | Status |). "
            f"Examples: {', '.join(short_rows[:5])}"
        )

    return issues
