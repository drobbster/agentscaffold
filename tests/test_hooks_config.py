"""Tests for hooks/events.py and hooks/config.py — Step B.1."""

from __future__ import annotations

from agentscaffold.hooks.config import EnforcementConfig, HookRuleConfig, PlatformHooksConfig
from agentscaffold.hooks.events import HookEvent

# ---------------------------------------------------------------------------
# HookEvent
# ---------------------------------------------------------------------------


def test_hook_event_values_are_strings() -> None:
    for event in HookEvent:
        assert isinstance(event.value, str)


def test_hook_event_pre_tool_use() -> None:
    assert HookEvent.PRE_TOOL_USE == "PreToolUse"


def test_hook_event_post_tool_use() -> None:
    assert HookEvent.POST_TOOL_USE == "PostToolUse"


def test_hook_event_session_start() -> None:
    assert HookEvent.SESSION_START == "SessionStart"


def test_hook_event_index_complete() -> None:
    assert HookEvent.INDEX_COMPLETE == "IndexComplete"


def test_hook_event_count() -> None:
    assert len(HookEvent) == 8


# ---------------------------------------------------------------------------
# HookRuleConfig
# ---------------------------------------------------------------------------


def test_hook_rule_defaults() -> None:
    rule = HookRuleConfig(event=HookEvent.SESSION_START)
    assert rule.enabled is True
    assert rule.platforms == []
    assert rule.command == ""
    assert rule.matcher == ""


def test_hook_rule_applies_to_all_when_empty_platforms() -> None:
    rule = HookRuleConfig(event=HookEvent.SESSION_START)
    assert rule.applies_to_all_platforms is True
    assert rule.applies_to("claude-code") is True
    assert rule.applies_to("cursor") is True
    assert rule.applies_to("windsurf") is True


def test_hook_rule_applies_to_specific_platform() -> None:
    rule = HookRuleConfig(event=HookEvent.SESSION_START, platforms=["cursor"])
    assert rule.applies_to_all_platforms is False
    assert rule.applies_to("cursor") is True
    assert rule.applies_to("claude-code") is False


def test_hook_rule_disabled_not_applied() -> None:
    rule = HookRuleConfig(event=HookEvent.SESSION_START, enabled=False)
    assert rule.enabled is False


# ---------------------------------------------------------------------------
# PlatformHooksConfig
# ---------------------------------------------------------------------------


def test_platform_hooks_config_defaults() -> None:
    cfg = PlatformHooksConfig()
    assert cfg.enabled is True
    assert cfg.output_path == ""
    assert cfg.extra == {}


def test_platform_hooks_config_disabled() -> None:
    cfg = PlatformHooksConfig(enabled=False)
    assert cfg.enabled is False


# ---------------------------------------------------------------------------
# EnforcementConfig
# ---------------------------------------------------------------------------


def test_enforcement_config_defaults() -> None:
    cfg = EnforcementConfig()
    assert cfg.rules == []
    assert cfg.platforms == {}
    assert cfg.freshness_trigger is True
    assert cfg.auto_orient is True


def test_enforcement_rules_for_platform_empty() -> None:
    cfg = EnforcementConfig()
    assert cfg.rules_for_platform("claude-code") == []


def test_enforcement_rules_for_platform_filters_disabled() -> None:
    cfg = EnforcementConfig(
        rules=[
            HookRuleConfig(event=HookEvent.SESSION_START, enabled=False),
            HookRuleConfig(event=HookEvent.INDEX_COMPLETE, enabled=True),
        ]
    )
    rules = cfg.rules_for_platform("claude-code")
    assert len(rules) == 1
    assert rules[0].event == HookEvent.INDEX_COMPLETE


def test_enforcement_rules_for_platform_filters_by_platform() -> None:
    cfg = EnforcementConfig(
        rules=[
            HookRuleConfig(event=HookEvent.SESSION_START, platforms=["cursor"]),
            HookRuleConfig(event=HookEvent.INDEX_COMPLETE),  # all platforms
        ]
    )
    claude_rules = cfg.rules_for_platform("claude-code")
    assert len(claude_rules) == 1
    assert claude_rules[0].event == HookEvent.INDEX_COMPLETE

    cursor_rules = cfg.rules_for_platform("cursor")
    assert len(cursor_rules) == 2


def test_enforcement_platform_enabled_defaults_true() -> None:
    cfg = EnforcementConfig()
    assert cfg.platform_enabled("claude-code") is True
    assert cfg.platform_enabled("cursor") is True
    assert cfg.platform_enabled("windsurf") is True


def test_enforcement_platform_can_be_disabled() -> None:
    cfg = EnforcementConfig(platforms={"cursor": PlatformHooksConfig(enabled=False)})
    assert cfg.platform_enabled("cursor") is False
    assert cfg.platform_enabled("claude-code") is True


# ---------------------------------------------------------------------------
# ScaffoldConfig integration
# ---------------------------------------------------------------------------


def test_scaffold_config_has_enforcement_field() -> None:
    from agentscaffold.config import ScaffoldConfig

    config = ScaffoldConfig()
    assert hasattr(config, "enforcement")
    assert isinstance(config.enforcement, EnforcementConfig)


def test_scaffold_config_enforcement_from_dict() -> None:
    from agentscaffold.config import ScaffoldConfig

    config = ScaffoldConfig(
        enforcement={
            "freshness_trigger": False,
            "auto_orient": False,
            "rules": [
                {
                    "event": "SessionStart",
                    "command": "scaffold orient",
                }
            ],
        }
    )
    assert config.enforcement.freshness_trigger is False
    assert len(config.enforcement.rules) == 1
    assert config.enforcement.rules[0].event == HookEvent.SESSION_START
