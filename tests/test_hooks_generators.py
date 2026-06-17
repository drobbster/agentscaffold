"""Tests for Phase B hook generators — Steps B.2, B.3, B.3a, B.4, B.5, B.8."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentscaffold.hooks.config import EnforcementConfig, HookRuleConfig, PlatformHooksConfig
from agentscaffold.hooks.engine import HookEngine
from agentscaffold.hooks.events import HookEvent
from agentscaffold.hooks.generators.claude_code import (
    generate_claude_code_hooks,
    write_claude_code_hooks,
)
from agentscaffold.hooks.generators.cursor import (
    EMBED_COMMIT_HOOK_REL_PATHS,
    INDEX_HOOK_REL_PATH,
    CursorRuleClass,
    _build_frontmatter,
    generate_cursor_enforcement_files,
    generate_cursor_hooks_config,
    generate_enforcement_rule_file,
    render_embedding_commit_hook_script,
    render_index_hook_script,
    write_cursor_hooks,
    write_embedding_commit_hooks,
)
from agentscaffold.hooks.generators.windsurf import (
    generate_windsurf_enforcement_section,
    write_windsurf_hooks,
)

# ---------------------------------------------------------------------------
# B.2: Claude Code hook generator
# ---------------------------------------------------------------------------


def test_generate_claude_code_hooks_empty_config() -> None:
    cfg = EnforcementConfig(freshness_trigger=False, auto_orient=False)
    result = generate_claude_code_hooks(cfg, include_builtins=False)
    assert result == {"hooks": {}}


def test_generate_claude_code_hooks_builtins_freshness() -> None:
    cfg = EnforcementConfig(freshness_trigger=True, auto_orient=False)
    result = generate_claude_code_hooks(cfg, include_builtins=True)
    assert "PostToolUse" in result["hooks"]
    entries = result["hooks"]["PostToolUse"]
    commands = [e["hooks"][0]["command"] for e in entries]
    assert commands == ["./.cursor/hooks/scaffold-index.sh"]


def test_generate_claude_code_hooks_builtins_orient() -> None:
    cfg = EnforcementConfig(freshness_trigger=False, auto_orient=True)
    result = generate_claude_code_hooks(cfg, include_builtins=True)
    assert "SessionStart" in result["hooks"]


def test_generate_claude_code_hooks_user_rule() -> None:
    cfg = EnforcementConfig(
        freshness_trigger=False,
        auto_orient=False,
        rules=[
            HookRuleConfig(
                event=HookEvent.PRE_TOOL_USE,
                matcher="Edit",
                command="scaffold validate",
            )
        ],
    )
    result = generate_claude_code_hooks(cfg, include_builtins=False)
    assert "PreToolUse" in result["hooks"]
    entry = result["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Edit"
    assert entry["hooks"][0]["command"] == "scaffold validate"


def test_generate_claude_code_hooks_non_tool_event_has_empty_matcher() -> None:
    cfg = EnforcementConfig(
        freshness_trigger=False,
        auto_orient=False,
        rules=[HookRuleConfig(event=HookEvent.SESSION_END, command="scaffold finalize")],
    )
    result = generate_claude_code_hooks(cfg, include_builtins=False)
    entry = result["hooks"]["SessionEnd"][0]
    assert entry["matcher"] == ""


def test_write_claude_code_hooks_creates_file(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    path = write_claude_code_hooks(cfg, tmp_path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert "hooks" in data
    script = tmp_path / INDEX_HOOK_REL_PATH
    assert script.exists()
    assert script.stat().st_mode & 0o111


def test_write_claude_code_hooks_dry_run(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    path = write_claude_code_hooks(cfg, tmp_path, dry_run=True)
    assert not path.exists()


def test_write_claude_code_hooks_merges_existing(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "claude-opus-4-6"}))
    write_claude_code_hooks(cfg, tmp_path)
    data = json.loads(settings.read_text())
    assert "model" in data  # preserved
    assert "hooks" in data  # merged


def test_write_claude_code_hooks_validates_schema(tmp_path: Path) -> None:
    """Generated hooks must conform to Claude Code hook schema."""
    cfg = EnforcementConfig()
    write_claude_code_hooks(cfg, tmp_path)
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    hooks = data["hooks"]
    for event_name, entries in hooks.items():
        assert isinstance(event_name, str)
        for entry in entries:
            assert "matcher" in entry
            assert "hooks" in entry
            for h in entry["hooks"]:
                assert h["type"] == "command"
                assert isinstance(h["command"], str)


# ---------------------------------------------------------------------------
# B.3: Cursor rule taxonomy
# ---------------------------------------------------------------------------


def test_build_frontmatter_always() -> None:
    fm = _build_frontmatter(CursorRuleClass.ALWAYS)
    assert "alwaysApply: true" in fm
    assert fm.startswith("---")
    assert fm.count("---") == 2


def test_build_frontmatter_glob() -> None:
    fm = _build_frontmatter(CursorRuleClass.GLOB, globs=["src/**/*.py", "lib/**"])
    assert "alwaysApply: false" in fm
    assert "src/**/*.py" in fm


def test_build_frontmatter_agent_requested() -> None:
    fm = _build_frontmatter(CursorRuleClass.AGENT_REQUESTED, description="when editing API files")
    assert "alwaysApply: false" in fm
    assert "when editing API files" in fm


def test_generate_enforcement_rule_file_always() -> None:
    rule = HookRuleConfig(
        event=HookEvent.POST_TOOL_USE,
        matcher="Edit|Write",
        command="scaffold index --incremental",
        description="Keep graph fresh",
    )
    content = generate_enforcement_rule_file(rule, rule_class=CursorRuleClass.ALWAYS)
    assert "alwaysApply: true" in content
    assert "Keep graph fresh" in content
    assert "scaffold index --incremental" in content


def test_generate_cursor_enforcement_files_empty_rules(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    paths = generate_cursor_enforcement_files(cfg, output_dir=tmp_path)
    assert paths == []


def test_generate_cursor_enforcement_files_writes_files(tmp_path: Path) -> None:
    cfg = EnforcementConfig(
        rules=[
            HookRuleConfig(
                event=HookEvent.SESSION_START,
                command="scaffold orient",
                description="Auto-orient",
            )
        ]
    )
    paths = generate_cursor_enforcement_files(cfg, output_dir=tmp_path)
    assert len(paths) == 1
    assert paths[0].exists()
    content = paths[0].read_text()
    assert "alwaysApply: true" in content


def test_generate_cursor_enforcement_files_dry_run(tmp_path: Path) -> None:
    cfg = EnforcementConfig(
        rules=[HookRuleConfig(event=HookEvent.SESSION_START, command="scaffold orient")]
    )
    paths = generate_cursor_enforcement_files(cfg, output_dir=tmp_path, dry_run=True)
    assert len(paths) == 1
    assert not paths[0].exists()


def test_generate_cursor_enforcement_files_platform_disabled(tmp_path: Path) -> None:
    cfg = EnforcementConfig(
        rules=[HookRuleConfig(event=HookEvent.SESSION_START, command="x")],
        platforms={"cursor": PlatformHooksConfig(enabled=False)},
    )
    paths = generate_cursor_enforcement_files(cfg, output_dir=tmp_path)
    assert paths == []


# ---------------------------------------------------------------------------
# Native Cursor hooks (.cursor/hooks.json + afterFileEdit wrapper)
# ---------------------------------------------------------------------------


def test_generate_cursor_hooks_config_freshness() -> None:
    cfg = EnforcementConfig(freshness_trigger=True)
    payload = generate_cursor_hooks_config(cfg)
    assert payload["version"] == 1
    entries = payload["hooks"]["afterFileEdit"]
    assert entries[0]["command"] == f"./{INDEX_HOOK_REL_PATH}"


def test_generate_cursor_hooks_config_no_freshness() -> None:
    cfg = EnforcementConfig(freshness_trigger=False)
    payload = generate_cursor_hooks_config(cfg)
    assert payload["hooks"] == {}


def test_render_index_hook_script_uses_scaffold_bin() -> None:
    script = render_index_hook_script("/opt/venv/bin/scaffold")
    assert script.startswith("#!/usr/bin/env bash")
    assert 'scaffold_bin="/opt/venv/bin/scaffold"' in script
    assert '"$scaffold_bin" index --incremental' in script
    # Must emit a JSON object on stdout and exit cleanly (Cursor contract).
    assert "'{}'" in script
    assert "exit 0" in script


def test_render_index_hook_script_is_single_flight_and_nonblocking() -> None:
    script = render_index_hook_script("scaffold", min_interval_seconds=30)
    # Single-flight lock + coalesced trailing run + backgrounded so the hook
    # returns immediately and rapid edits never stack.
    assert 'mkdir "$lock_dir"' in script
    assert "index.request" in script
    assert "index.last_success" in script
    assert "min_interval_seconds=30" in script
    assert "disown" in script
    # Honors an explicit disable switch.
    assert "SCAFFOLD_HOOK_DISABLE" in script


def test_render_embedding_commit_hook_script_is_nonblocking_and_lock_aware() -> None:
    script = render_embedding_commit_hook_script("/tmp/scaffold", min_interval_seconds=45)
    assert 'scaffold_bin="/tmp/scaffold"' in script
    assert "min_interval_seconds=45" in script
    assert "structural_lock_dir" in script
    assert "index --incremental --embeddings" in script
    assert ") >/dev/null 2>&1 &" in script


def test_write_embedding_commit_hooks_creates_executable_git_hooks(tmp_path: Path) -> None:
    paths = write_embedding_commit_hooks(tmp_path, scaffold_bin="/tmp/scaffold")
    assert [p.relative_to(tmp_path).as_posix() for p in paths] == list(EMBED_COMMIT_HOOK_REL_PATHS)
    for path in paths:
        assert path.exists()
        assert path.stat().st_mode & 0o111


def test_write_cursor_hooks_creates_script_and_json(tmp_path: Path) -> None:
    cfg = EnforcementConfig(freshness_trigger=True)
    paths = write_cursor_hooks(cfg, tmp_path, scaffold_bin="scaffold")
    script_path, hooks_path = paths
    assert script_path.exists()
    assert script_path.name == "scaffold-index.sh"
    # Script must be executable.
    assert script_path.stat().st_mode & 0o111
    data = json.loads(hooks_path.read_text())
    assert data["version"] == 1
    assert data["hooks"]["afterFileEdit"][0]["command"] == f"./{INDEX_HOOK_REL_PATH}"


def test_write_cursor_hooks_dry_run(tmp_path: Path) -> None:
    cfg = EnforcementConfig(freshness_trigger=True)
    paths = write_cursor_hooks(cfg, tmp_path, dry_run=True)
    assert len(paths) == 2
    assert not paths[0].exists()
    assert not paths[1].exists()


def test_write_cursor_hooks_disabled_platform(tmp_path: Path) -> None:
    cfg = EnforcementConfig(
        freshness_trigger=True,
        platforms={"cursor": PlatformHooksConfig(enabled=False)},
    )
    assert write_cursor_hooks(cfg, tmp_path) == []


def test_write_cursor_hooks_no_freshness(tmp_path: Path) -> None:
    cfg = EnforcementConfig(freshness_trigger=False)
    assert write_cursor_hooks(cfg, tmp_path) == []


def test_write_cursor_hooks_merges_and_is_idempotent(tmp_path: Path) -> None:
    hooks_path = tmp_path / ".cursor" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {"beforeShellExecution": [{"command": "./guard.sh"}]},
            }
        )
    )
    cfg = EnforcementConfig(freshness_trigger=True)
    write_cursor_hooks(cfg, tmp_path)
    write_cursor_hooks(cfg, tmp_path)  # second run must not duplicate
    data = json.loads(hooks_path.read_text())
    assert data["hooks"]["beforeShellExecution"] == [{"command": "./guard.sh"}]
    assert len(data["hooks"]["afterFileEdit"]) == 1


# ---------------------------------------------------------------------------
# B.3a: write_cursor_mcp_json
# ---------------------------------------------------------------------------


def test_write_cursor_mcp_json_creates_file(tmp_path: Path) -> None:
    from agentscaffold.agents.cursor import write_cursor_mcp_json

    cursor_dir = tmp_path / ".cursor"
    write_cursor_mcp_json(cursor_dir)
    mcp_path = cursor_dir / "mcp.json"
    assert mcp_path.exists()
    data = json.loads(mcp_path.read_text())
    assert "mcpServers" in data
    assert "agentscaffold" in data["mcpServers"]


def test_write_cursor_mcp_json_skips_existing(tmp_path: Path, capsys) -> None:
    from agentscaffold.agents.cursor import write_cursor_mcp_json

    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    mcp_path = cursor_dir / "mcp.json"
    original = {"mcpServers": {"other": {"command": "other"}}}
    mcp_path.write_text(json.dumps(original))

    write_cursor_mcp_json(cursor_dir)
    # Original content must be preserved
    data = json.loads(mcp_path.read_text())
    assert "other" in data["mcpServers"]


# ---------------------------------------------------------------------------
# B.4: Windsurf hook generator
# ---------------------------------------------------------------------------


def test_generate_windsurf_enforcement_section_builtins() -> None:
    cfg = EnforcementConfig(freshness_trigger=True, auto_orient=True)
    section = generate_windsurf_enforcement_section(cfg)
    assert "scaffold index --incremental" in section
    assert "scaffold orient" in section


def test_generate_windsurf_enforcement_section_no_builtins() -> None:
    cfg = EnforcementConfig(freshness_trigger=False, auto_orient=False)
    section = generate_windsurf_enforcement_section(cfg)
    assert "scaffold index" not in section
    assert "scaffold orient" not in section


def test_write_windsurf_hooks_creates_file(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    path = write_windsurf_hooks(cfg, tmp_path)
    assert path.exists()
    assert "Enforcement Rules" in path.read_text()


def test_write_windsurf_hooks_appends_to_existing(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    rules_path = tmp_path / ".windsurfrules"
    rules_path.write_text("# Existing rules\n")
    write_windsurf_hooks(cfg, tmp_path)
    content = rules_path.read_text()
    assert "Existing rules" in content
    assert "Enforcement Rules" in content


def test_write_windsurf_hooks_no_duplicate_section(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    write_windsurf_hooks(cfg, tmp_path)
    write_windsurf_hooks(cfg, tmp_path)  # second call
    content = (tmp_path / ".windsurfrules").read_text()
    assert content.count("## Enforcement Rules") == 1


def test_write_windsurf_hooks_dry_run(tmp_path: Path) -> None:
    cfg = EnforcementConfig()
    path = write_windsurf_hooks(cfg, tmp_path, dry_run=True)
    assert not path.exists()


def test_write_windsurf_hooks_platform_disabled(tmp_path: Path) -> None:
    cfg = EnforcementConfig(platforms={"windsurf": PlatformHooksConfig(enabled=False)})
    path = write_windsurf_hooks(cfg, tmp_path)
    assert not path.exists()


# ---------------------------------------------------------------------------
# B.5: HookEngine
# ---------------------------------------------------------------------------


def test_hook_engine_register_and_fire() -> None:
    engine = HookEngine()
    calls: list[dict] = []
    engine.register(HookEvent.SESSION_START, lambda **kw: calls.append(kw))
    engine.fire(HookEvent.SESSION_START, context="test")
    assert len(calls) == 1
    assert calls[0]["context"] == "test"


def test_hook_engine_disabled_no_fire() -> None:
    engine = HookEngine(enabled=False)
    calls: list = []
    engine.register(HookEvent.SESSION_START, lambda **kw: calls.append(1))
    engine.fire(HookEvent.SESSION_START)
    assert calls == []


def test_hook_engine_handler_exception_caught() -> None:
    engine = HookEngine()

    def bad_handler(**kw: Any) -> None:
        raise RuntimeError("boom")

    engine.register(HookEvent.SESSION_START, bad_handler)
    engine.fire(HookEvent.SESSION_START)  # must not raise


def test_hook_engine_multiple_handlers_called_in_order() -> None:
    engine = HookEngine()
    order: list[int] = []
    engine.register(HookEvent.SESSION_START, lambda **kw: order.append(1))
    engine.register(HookEvent.SESSION_START, lambda **kw: order.append(2))
    engine.fire(HookEvent.SESSION_START)
    assert order == [1, 2]


def test_hook_engine_unregister() -> None:
    engine = HookEngine()
    calls: list = []
    handler = lambda **kw: calls.append(1)  # noqa: E731
    engine.register(HookEvent.SESSION_START, handler)
    engine.unregister(HookEvent.SESSION_START, handler)
    engine.fire(HookEvent.SESSION_START)
    assert calls == []


def test_hook_engine_handler_count() -> None:
    engine = HookEngine()
    assert engine.handler_count(HookEvent.SESSION_START) == 0
    engine.register(HookEvent.SESSION_START, lambda **kw: None)
    assert engine.handler_count(HookEvent.SESSION_START) == 1


def test_hook_engine_toggle_enabled() -> None:
    engine = HookEngine()
    assert engine.enabled is True
    engine.enabled = False
    assert engine.enabled is False


# ---------------------------------------------------------------------------
# B.8: DomainManifest with file_patterns
# ---------------------------------------------------------------------------


def test_domain_manifest_file_patterns() -> None:
    from agentscaffold.domain_packs.manifest_schema import DomainManifest

    manifest = DomainManifest(name="trading", file_patterns=["libs/risk/**", "execution/**"])
    assert manifest.has_file_patterns is True
    assert manifest.cursor_always_apply is False


def test_domain_manifest_no_file_patterns_always_apply() -> None:
    from agentscaffold.domain_packs.manifest_schema import DomainManifest

    manifest = DomainManifest(name="trading")
    assert manifest.has_file_patterns is False
    assert manifest.cursor_always_apply is True


def test_domain_manifest_trading_has_patterns() -> None:
    from pathlib import Path

    import yaml

    from agentscaffold.domain_packs.manifest_schema import DomainManifest

    manifest_path = (
        Path(__file__).parent.parent
        / "src"
        / "agentscaffold"
        / "domains"
        / "trading"
        / "manifest.yaml"
    )
    data = yaml.safe_load(manifest_path.read_text())
    manifest = DomainManifest(**data)
    assert manifest.has_file_patterns
    assert any("risk" in p for p in manifest.file_patterns)
