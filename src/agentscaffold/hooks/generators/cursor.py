"""Cursor hook generator with rule taxonomy — Step B.3.

Emits YAML frontmatter on every generated ``.cursor/rules/`` file based on
the rule class:

  - governance / prohibitions / MCP routing rules:
    ``alwaysApply: true``
  - domain standards (with file_patterns):
    ``alwaysApply: false``, ``globs: [<file_patterns>]``
  - domain standards (without file_patterns):
    ``alwaysApply: true``  (safe fallback)
  - expert reviewer rules:
    ``alwaysApply: false``, ``description: "<when to activate>"``
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from agentscaffold.hooks.config import EnforcementConfig, HookRuleConfig
from agentscaffold.hooks.events import HookEvent


class CursorRuleClass(str, Enum):
    """Taxonomy of Cursor rule types, each with its own frontmatter shape."""

    ALWAYS = "always"
    """alwaysApply: true — governance, prohibitions, MCP routing."""

    GLOB = "glob"
    """alwaysApply: false + globs — domain standards with file_patterns."""

    AGENT_REQUESTED = "agent_requested"
    """alwaysApply: false + description — expert reviewer content."""


def _build_frontmatter(
    rule_class: CursorRuleClass,
    *,
    globs: list[str] | None = None,
    description: str = "",
) -> str:
    """Return a YAML frontmatter block (with ``---`` delimiters)."""
    data: dict[str, Any] = {}

    if rule_class == CursorRuleClass.ALWAYS:
        data["alwaysApply"] = True
    elif rule_class == CursorRuleClass.GLOB:
        data["alwaysApply"] = False
        data["globs"] = globs or []
    elif rule_class == CursorRuleClass.AGENT_REQUESTED:
        data["alwaysApply"] = False
        if description:
            data["description"] = description

    return "---\n" + yaml.dump(data, default_flow_style=False).rstrip() + "\n---\n"


def generate_enforcement_rule_file(
    rule: HookRuleConfig,
    *,
    rule_class: CursorRuleClass = CursorRuleClass.ALWAYS,
    globs: list[str] | None = None,
) -> str:
    """Generate the content of a single Cursor rule file for a hook rule.

    Args:
        rule: The enforcement rule to convert.
        rule_class: Cursor rule taxonomy class.
        globs: File patterns for GLOB-class rules.

    Returns:
        Full file content including YAML frontmatter.
    """
    frontmatter = _build_frontmatter(
        rule_class,
        globs=globs,
        description=rule.description,
    )
    body_lines = []
    if rule.description:
        body_lines.append(f"# {rule.description}")
        body_lines.append("")
    if rule.command:
        event_label = rule.event.value
        matcher_note = f" (matcher: `{rule.matcher}`)" if rule.matcher else ""
        body_lines.append(f"On **{event_label}**{matcher_note}, run: `{rule.command}`")
    return frontmatter + "\n".join(body_lines) + "\n"


def generate_cursor_enforcement_files(
    config: EnforcementConfig,
    *,
    output_dir: Path,
    dry_run: bool = False,
) -> list[Path]:
    """Write per-rule Cursor rule files to ``output_dir/.cursor/rules/``.

    Governance/prohibition/MCP rules → ``alwaysApply: true``
    Freshness and auto-orient rules → ``alwaysApply: true``

    Args:
        config: Enforcement configuration.
        output_dir: Project root directory.
        dry_run: If True, return paths without writing files.

    Returns:
        List of paths that were (or would be) written.
    """
    if not config.platform_enabled("cursor"):
        return []

    rules = config.rules_for_platform("cursor")
    if not rules:
        return []

    rules_dir = output_dir / ".cursor" / "rules"
    written: list[Path] = []

    for i, rule in enumerate(rules):
        slug = _event_slug(rule.event, i)
        dest = rules_dir / f"enforcement_{slug}.md"
        content = generate_enforcement_rule_file(rule, rule_class=CursorRuleClass.ALWAYS)

        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

        written.append(dest)

    return written


def _event_slug(event: HookEvent, index: int) -> str:
    return f"{event.value.lower()}_{index:02d}"
