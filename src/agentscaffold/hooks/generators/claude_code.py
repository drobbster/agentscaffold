"""Claude Code hook generator — Step B.2.

Generates the ``hooks`` section of ``.claude/settings.json`` from an
``EnforcementConfig``.

Claude Code hook schema::

    {
      "hooks": {
        "<HookEvent>": [
          {
            "matcher": "<tool-name glob or empty>",
            "hooks": [
              {"type": "command", "command": "<shell command>"}
            ]
          }
        ]
      }
    }

Only PreToolUse and PostToolUse entries use ``matcher``.  Other events
(SessionStart, SessionEnd, etc.) use an empty string matcher.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentscaffold.hooks.config import EnforcementConfig
from agentscaffold.hooks.events import HookEvent

_TOOL_EVENTS = {HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE}

# Built-in templates that are always included unless disabled via config
_BUILTIN_HOOKS: list[dict[str, Any]] = [
    {
        "event": HookEvent.POST_TOOL_USE,
        "matcher": "Edit|Write|NotebookEdit",
        "command": "scaffold index --incremental",
        "description": "Keep graph fresh after every file edit",
    },
    {
        "event": HookEvent.SESSION_START,
        "matcher": "",
        "command": "scaffold orient",
        "description": "Auto-orient at session start",
    },
]


def generate_claude_code_hooks(
    config: EnforcementConfig,
    *,
    include_builtins: bool = True,
) -> dict[str, Any]:
    """Generate the ``hooks`` dict for ``.claude/settings.json``.

    Args:
        config: Enforcement configuration.
        include_builtins: If True, include built-in templates (freshness
            trigger, auto-orient) unless suppressed by config flags.

    Returns:
        A dict with a top-level ``"hooks"`` key containing the Claude Code
        hook entries, ready to be merged into ``.claude/settings.json``.
    """
    rules = config.rules_for_platform("claude-code")

    # Accumulate per-event entries: {event_name: [{"matcher": ..., "hooks": [...]}]}
    event_buckets: dict[str, list[dict[str, Any]]] = {}

    def _add(event: HookEvent, matcher: str, command: str) -> None:
        name = event.value
        entry = {
            "matcher": matcher,
            "hooks": [{"type": "command", "command": command}],
        }
        event_buckets.setdefault(name, []).append(entry)

    # User-defined rules
    for rule in rules:
        if not rule.command:
            continue
        matcher = rule.matcher if rule.event in _TOOL_EVENTS else ""
        _add(rule.event, matcher, rule.command)

    # Built-in hooks
    if include_builtins:
        if config.freshness_trigger:
            _add(
                HookEvent.POST_TOOL_USE,
                "Edit|Write|NotebookEdit",
                "scaffold index --incremental",
            )
        if config.auto_orient:
            _add(HookEvent.SESSION_START, "", "scaffold orient")

    return {"hooks": event_buckets}


def write_claude_code_hooks(
    config: EnforcementConfig,
    output_dir: Path,
    *,
    include_builtins: bool = True,
    dry_run: bool = False,
) -> Path:
    """Write ``.claude/settings.json`` with generated hooks.

    If the file already exists its existing content is preserved and the
    ``hooks`` key is merged (replaced).

    Args:
        config: Enforcement configuration.
        output_dir: Project root directory (parent of ``.claude/``).
        include_builtins: Pass through to generate_claude_code_hooks.
        dry_run: If True, return the target path without writing anything.

    Returns:
        Path to the settings.json file (written or would-be written).
    """
    settings_path = output_dir / ".claude" / "settings.json"

    if dry_run:
        return settings_path

    hooks_payload = generate_claude_code_hooks(config, include_builtins=include_builtins)

    existing: dict[str, Any] = {}
    if settings_path.is_file():
        try:
            existing = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing.update(hooks_payload)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, indent=2) + "\n")
    return settings_path
