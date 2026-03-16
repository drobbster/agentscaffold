"""Pydantic models for hook configuration — ``enforcement:`` section of scaffold.yaml."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agentscaffold.hooks.events import HookEvent


class HookRuleConfig(BaseModel):
    """A single enforcement rule that generates hooks across platforms.

    Attributes:
        event: The lifecycle event that triggers this rule.
        command: Shell command to execute (Claude Code / Windsurf hooks).
        description: Human-readable description used in Cursor rule bodies.
        matcher: Optional tool-name glob for PreToolUse/PostToolUse matchers.
        enabled: Whether this rule is active (default True).
        platforms: Platforms to generate this hook for. Empty list means all.
    """

    event: HookEvent
    command: str = ""
    description: str = ""
    matcher: str = ""
    enabled: bool = True
    platforms: list[str] = Field(default_factory=list)

    @property
    def applies_to_all_platforms(self) -> bool:
        return not self.platforms

    def applies_to(self, platform: str) -> bool:
        return self.applies_to_all_platforms or platform in self.platforms


class PlatformHooksConfig(BaseModel):
    """Per-platform hook generation settings.

    Attributes:
        enabled: Whether to generate hooks for this platform.
        output_path: Override for the generated hook file path.
        extra: Arbitrary extra config passed through to the generator.
    """

    enabled: bool = True
    output_path: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class EnforcementConfig(BaseModel):
    """Top-level enforcement configuration under ``enforcement:`` in scaffold.yaml.

    Example scaffold.yaml::

        enforcement:
          rules:
            - event: PreToolUse
              matcher: "Edit|Write|Bash"
              command: "scaffold validate --pre-edit"
              description: "Block edits that would violate architecture constraints"
            - event: PostToolUse
              matcher: "Edit|Write"
              command: "scaffold index --incremental"
              description: "Keep graph fresh after every file edit"
            - event: SessionStart
              command: "scaffold orient"
              description: "Auto-orient at session start"
          platforms:
            claude_code:
              enabled: true
            cursor:
              enabled: true
            windsurf:
              enabled: true
          freshness_trigger: true
          auto_orient: true
    """

    rules: list[HookRuleConfig] = Field(default_factory=list)
    platforms: dict[str, PlatformHooksConfig] = Field(default_factory=dict)
    freshness_trigger: bool = True
    auto_orient: bool = True

    def rules_for_platform(self, platform: str) -> list[HookRuleConfig]:
        """Return enabled rules that apply to *platform*."""
        return [r for r in self.rules if r.enabled and r.applies_to(platform)]

    def platform_enabled(self, platform: str) -> bool:
        """Return True if hook generation is enabled for *platform*."""
        cfg = self.platforms.get(platform)
        if cfg is None:
            return True  # default: enabled
        return cfg.enabled
