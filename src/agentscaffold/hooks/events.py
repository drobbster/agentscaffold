"""HookEvent enum for AgentScaffold lifecycle hook points."""

from __future__ import annotations

from enum import Enum


class HookEvent(str, Enum):
    """Lifecycle events that can trigger hooks.

    Values match the Claude Code hook event names where applicable so that
    generated ``.claude/settings.json`` hook entries can reference them
    directly.
    """

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    PLAN_TRANSITION = "PlanTransition"
    REVIEW_COMPLETE = "ReviewComplete"
    PRE_VALIDATE = "PreValidate"
    INDEX_COMPLETE = "IndexComplete"
