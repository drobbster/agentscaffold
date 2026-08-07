"""Tests for Phase B hook generators — Steps B.2, B.3, B.3a, B.4, B.5, B.8."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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
    assert 'write_lock_dir="$state_dir/graph.write.lock"' in script
    assert 'while [ -d "$write_lock_dir" ]' in script
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
# Plan 253: the per-project config must not undo the single-server migration
#
# Since 0.10 one project-aware server serves every registered project, so a
# per-project `.cursor/mcp.json` in a registered root is the legacy registration
# that `scaffold mcp install --migrate` exists to retire. Generating one there
# reverts the migration along the documented upgrade path.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_client_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real ``~/.cursor/mcp.json`` out of these results.

    The generator now consults the client config to decide whether a shared
    server already covers a repo, so without this the outcome of several tests
    would depend on whether whoever runs the suite happens to have AgentScaffold
    installed -- passing on one laptop and failing on the next.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "clean-home"))


def _install_canonical_entry(home: Path) -> Path:
    """Put a canonical shared-server entry in the client config under *home*."""
    config = home / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"mcpServers": {"agentscaffold": {"command": "scaffold"}}}))
    return config


def test_write_cursor_mcp_json_dry_run_writes_nothing_at_all(tmp_path: Path, capsys) -> None:
    """A dry run must not create the file *or* its parent directory.

    The directory matters: the writer used to run its own ``mkdir``, duplicating
    the one the caller already guarded, so a fix that only skips the file write
    would still leave ``.cursor/`` behind and pass a weaker assertion.
    """
    from agentscaffold.agents.cursor import write_cursor_mcp_json

    cursor_dir = tmp_path / ".cursor"
    write_cursor_mcp_json(cursor_dir, dry_run=True)

    assert not (cursor_dir / "mcp.json").exists()
    assert not cursor_dir.exists()
    assert "dry-run" in capsys.readouterr().out.lower()


def test_write_cursor_mcp_json_skipped_for_a_registered_root(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The reported regression: a registered root must not get a per-project file."""
    from agentscaffold.agents.cursor import write_cursor_mcp_json
    from agentscaffold.workspace_registry import register_workspace

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install_canonical_entry(tmp_path / "home")
    root = tmp_path / "repo"
    root.mkdir()
    register_workspace(root)

    write_cursor_mcp_json(root / ".cursor")

    assert not (root / ".cursor" / "mcp.json").exists()
    assert "skip" in capsys.readouterr().out.lower()


def test_write_cursor_mcp_json_still_written_for_an_unregistered_root(tmp_path: Path) -> None:
    """Zero-config setup must survive the fix.

    A lone repo that has only ever run ``scaffold init`` is not in the registry
    and has no shared server, so the per-project file is its only registration.
    This fails if the skip is made unconditional.
    """
    from agentscaffold.agents.cursor import write_cursor_mcp_json

    root = tmp_path / "repo"
    root.mkdir()

    write_cursor_mcp_json(root / ".cursor")

    assert (root / ".cursor" / "mcp.json").exists()


def test_write_cursor_mcp_json_skipped_when_the_shared_server_is_already_installed(
    tmp_path: Path, monkeypatch
) -> None:
    """A project created after ``scaffold mcp install`` is not registered yet.

    Registration alone would miss it, so the documented quick start would hand a
    brand-new project two servers: ``scaffold init`` writes the per-project file
    and ``scaffold mcp install`` then adds the shared entry beside it.
    """
    from agentscaffold.agents.cursor import write_cursor_mcp_json

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install_canonical_entry(tmp_path / "home")
    root = tmp_path / "repo"
    root.mkdir()  # deliberately never registered

    write_cursor_mcp_json(root / ".cursor")

    assert not (root / ".cursor" / "mcp.json").exists()


def test_write_cursor_mcp_json_skipped_for_a_registered_workspace_root(
    tmp_path: Path, monkeypatch
) -> None:
    """A workspace root whose projects live in subdirectories is registered too.

    ``scaffold project register`` records a lone repo as a workspace root holding
    one project at ``.``; a ``workspace.yaml`` records subdirectories. Matching
    only project paths passes the lone-repo test and still fails in the field.
    """
    from agentscaffold.agents.cursor import write_cursor_mcp_json
    from agentscaffold.workspace_registry import register_workspace

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install_canonical_entry(tmp_path / "home")
    workspace = tmp_path / "ws"
    (workspace / "alpha").mkdir(parents=True)
    (workspace / "beta").mkdir(parents=True)
    register_workspace(workspace, projects=[("alpha", "alpha"), ("beta", "beta")])

    write_cursor_mcp_json(workspace / ".cursor")

    assert not (workspace / ".cursor" / "mcp.json").exists()


def test_write_cursor_mcp_json_matches_a_root_spelled_differently(
    tmp_path: Path, monkeypatch
) -> None:
    """The registry stores a resolved path; callers arrive with any spelling.

    Observed for real: the registry held ``/private/tmp/x`` while the working
    directory was ``/tmp/x``. A string comparison silently fails to match, the
    skip never fires, and the bug survives a test written with one spelling.
    """
    from agentscaffold.agents.cursor import write_cursor_mcp_json
    from agentscaffold.workspace_registry import register_workspace

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install_canonical_entry(tmp_path / "home")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    register_workspace(real)

    write_cursor_mcp_json(link / ".cursor")

    assert not (link / ".cursor" / "mcp.json").exists()


def test_write_cursor_mcp_json_writes_when_the_registry_cannot_be_read(
    tmp_path: Path, monkeypatch
) -> None:
    """Generation must not depend on a readable registry.

    The lookup is advisory, so an unreadable registry falls back to the previous
    behaviour rather than failing the whole generate run. Anything written this
    way is caught by ``scaffold doctor``.
    """
    import agentscaffold.workspace_registry as registry_module
    from agentscaffold.agents.cursor import write_cursor_mcp_json

    def _boom(*args, **kwargs):
        raise OSError("registry unreadable")

    monkeypatch.setattr(registry_module, "load_registry", _boom)
    root = tmp_path / "repo"
    root.mkdir()

    write_cursor_mcp_json(root / ".cursor")

    assert (root / ".cursor" / "mcp.json").exists()


def test_write_cursor_mcp_json_names_the_install_step_when_no_server_is_registered(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Registered does not imply installed.

    ``scaffold project register`` only writes a registry row. Skipping on the
    strength of registration alone can leave a project with no server at all, so
    the skip has to say what to run.
    """
    from agentscaffold.agents.cursor import write_cursor_mcp_json
    from agentscaffold.workspace_registry import register_workspace

    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # no canonical entry installed
    root = tmp_path / "repo"
    root.mkdir()
    register_workspace(root)

    write_cursor_mcp_json(root / ".cursor")

    assert not (root / ".cursor" / "mcp.json").exists()
    assert "scaffold mcp install" in capsys.readouterr().out


def test_run_cursor_setup_also_skips_a_registered_root(tmp_path: Path, monkeypatch) -> None:
    """``scaffold agents cursor`` is the second caller and the quieter route.

    Fixing only ``generate-all`` leaves this path recreating the same file.
    """
    from agentscaffold.agents.cursor import run_cursor_setup
    from agentscaffold.workspace_registry import register_workspace

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _install_canonical_entry(tmp_path / "home")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "scaffold.yaml").write_text("framework:\n  project_name: repo\n")
    register_workspace(root)
    monkeypatch.chdir(root)

    run_cursor_setup()

    assert not (root / ".cursor" / "mcp.json").exists()


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
