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

import json
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from agentscaffold.hooks.config import EnforcementConfig, HookRuleConfig
from agentscaffold.hooks.events import HookEvent

# Native Cursor hooks (.cursor/hooks.json). Cursor's afterFileEdit event fires
# after the agent edits a file -- the right place to keep the knowledge graph
# fresh. The command receives JSON on stdin (file_path, edits) and must emit a
# JSON object on stdout; we wrap the index call in a script that keeps scaffold
# output on stderr and prints "{}" so Cursor treats it as a clean success.
CURSOR_HOOKS_VERSION = 1
INDEX_HOOK_REL_PATH = ".cursor/hooks/scaffold-index.sh"


def resolve_scaffold_bin() -> str:
    """Best-effort path to the ``scaffold`` executable for generated hooks.

    Prefers the ``scaffold`` binary that sits beside the running interpreter
    (the venv that invoked ``scaffold agents cursor``) so the hook works without
    relying on PATH; falls back to the bare ``scaffold`` name otherwise.
    """
    import sys

    candidate = Path(sys.executable).parent / "scaffold"
    if candidate.exists():
        return str(candidate)
    return "scaffold"


# Debounce window note: instead of a fixed-window throttle (which can drop the
# final edit of a burst and leave the graph stale), the script below uses a
# single-flight lock plus a coalesced trailing run. Rapid multi-file edits never
# stack: at most one incremental index runs at a time, and if edits arrive while
# it runs, exactly one more (coalesced) index runs afterward. The hook returns
# immediately so Cursor is never blocked.
_INDEX_HOOK_TEMPLATE = """#!/usr/bin/env bash
# AgentScaffold afterFileEdit hook: keep the knowledge graph fresh.
#
# Non-blocking + single-flight: rapid multi-file edits never stack. At most one
# incremental index runs at a time; if edits arrive while it runs, exactly one
# more (coalesced) index runs afterward so nothing is left stale. The hook
# returns immediately with "{}" so Cursor is never blocked.
#
# Disable with SCAFFOLD_HOOK_DISABLE=1 or by deleting .cursor/hooks.json.
set -uo pipefail

# Cursor passes JSON on stdin (file_path, edits); consume and ignore it.
cat >/dev/null 2>&1 || true

emit() { printf '%s\\n' '{}'; }

if [ "${SCAFFOLD_HOOK_DISABLE:-0}" = "1" ]; then
  emit
  exit 0
fi

scaffold_bin="__SCAFFOLD_BIN__"
state_dir=".scaffold"
lock_dir="$state_dir/index.lock"
req_stamp="$state_dir/index.request"
log_file="$state_dir/index-hook.log"
mkdir -p "$state_dir" 2>/dev/null || true

now=$(date +%s)

# Record this edit as an index request (used to coalesce a trailing run).
printf '%s\\n' "$now" > "$req_stamp" 2>/dev/null || true

# Reap a stale lock left behind by a killed indexer (older than 10 minutes).
if [ -d "$lock_dir" ]; then
  lock_mtime=$(stat -f %m "$lock_dir" 2>/dev/null \\
    || stat -c %Y "$lock_dir" 2>/dev/null || echo "$now")
  if [ $((now - lock_mtime)) -gt 600 ]; then
    rmdir "$lock_dir" 2>/dev/null || true
  fi
fi

# Single-flight: acquire the lock or let the running indexer pick up our request.
if mkdir "$lock_dir" 2>/dev/null; then
  (
    trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
    while :; do
      start=$(date +%s)
      "$scaffold_bin" index --incremental >> "$log_file" 2>&1 || true
      req=$(cat "$req_stamp" 2>/dev/null || echo 0)
      [ "$req" -le "$start" ] && break
    done
  ) >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

emit
exit 0
"""


def render_index_hook_script(scaffold_bin: str = "scaffold") -> str:
    """Return the bash wrapper that refreshes the graph on afterFileEdit.

    The wrapper is non-blocking and single-flight: it backgrounds the
    incremental index behind a lock so concurrent edits cannot stack multiple
    indexers, and coalesces a trailing run so the last edit of a burst is still
    captured. ``scaffold_bin`` is the executable invoked for indexing.
    """
    return _INDEX_HOOK_TEMPLATE.replace("__SCAFFOLD_BIN__", scaffold_bin)


def generate_cursor_hooks_config(
    config: EnforcementConfig,
    *,
    command: str = f"./{INDEX_HOOK_REL_PATH}",
    include_builtins: bool = True,
) -> dict[str, Any]:
    """Build the ``.cursor/hooks.json`` payload from enforcement config."""
    hooks: dict[str, list[dict[str, str]]] = {}
    if include_builtins and config.freshness_trigger:
        hooks.setdefault("afterFileEdit", []).append({"command": command})
    return {"version": CURSOR_HOOKS_VERSION, "hooks": hooks}


def write_cursor_hooks(
    config: EnforcementConfig,
    output_dir: Path,
    *,
    scaffold_bin: str = "scaffold",
    dry_run: bool = False,
) -> list[Path]:
    """Write ``.cursor/hooks.json`` + the index wrapper script.

    Generates a native Cursor ``afterFileEdit`` hook so the knowledge graph is
    refreshed automatically after the agent edits files (the deterministic
    equivalent of the Claude Code PostToolUse freshness trigger). Merges into an
    existing ``hooks.json`` without clobbering unrelated events.

    Returns the list of paths written (script, then hooks.json).
    """
    if not config.platform_enabled("cursor") or not config.freshness_trigger:
        return []

    script_path = output_dir / INDEX_HOOK_REL_PATH
    hooks_path = output_dir / ".cursor" / "hooks.json"

    if dry_run:
        return [script_path, hooks_path]

    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(render_index_hook_script(scaffold_bin))
    script_path.chmod(0o755)

    payload = generate_cursor_hooks_config(config)
    existing: dict[str, Any] = {}
    if hooks_path.is_file():
        try:
            existing = json.loads(hooks_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing.setdefault("version", payload["version"])
    existing_hooks = existing.setdefault("hooks", {})
    for event, entries in payload["hooks"].items():
        bucket = existing_hooks.setdefault(event, [])
        for entry in entries:
            if not any(e.get("command") == entry["command"] for e in bucket):
                bucket.append(entry)

    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(existing, indent=2) + "\n")
    return [script_path, hooks_path]


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
