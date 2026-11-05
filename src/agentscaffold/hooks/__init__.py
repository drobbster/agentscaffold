"""Hook generation system for AgentScaffold.

Generates platform-native lifecycle hooks from a single intent-based
``enforcement:`` configuration in scaffold.yaml.

Public API::

    from agentscaffold.hooks import HookEvent, EnforcementConfig, generate_hooks

Supported platforms: claude-code, cursor, windsurf.

Exports resolve lazily: the edit-hook router (``agentscaffold.hooks.router``)
runs on every agent edit in every workspace and must not import pydantic just
because it lives in this package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


def __getattr__(name: str) -> Any:
    if name == "HookEvent":
        from agentscaffold.hooks.events import HookEvent

        return HookEvent
    if name in ("EnforcementConfig", "HookRuleConfig", "PlatformHooksConfig"):
        from agentscaffold.hooks import config

        return getattr(config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
