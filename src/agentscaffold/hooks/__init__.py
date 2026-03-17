"""Hook generation system for AgentScaffold.

Generates platform-native lifecycle hooks from a single intent-based
``enforcement:`` configuration in scaffold.yaml.

Public API::

    from agentscaffold.hooks import HookEvent, EnforcementConfig, generate_hooks

Supported platforms: claude-code, cursor, windsurf.
"""

from __future__ import annotations

from agentscaffold.hooks.config import (
    EnforcementConfig,
    HookRuleConfig,
    PlatformHooksConfig,
)
from agentscaffold.hooks.events import HookEvent

__all__ = [
    "EnforcementConfig",
    "HookEvent",
    "HookRuleConfig",
    "PlatformHooksConfig",
]
