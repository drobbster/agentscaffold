"""The registry-routed hook router and its background worker."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentscaffold import workspace_registry
from agentscaffold.hooks import router, worker
from agentscaffold.workspace_registry import register_workspace


def _project(root: Path, *, config: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(config or "agents:\n  agents_md: false\n")
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "main.py").write_text("x = 1\n")
    return root.resolve()


@pytest.fixture()
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, router.RoutedProject, str]]:
    calls: list[tuple[str, router.RoutedProject, str]] = []

    def fake_spawn(kind: str, project: router.RoutedProject, event: str) -> bool:
        calls.append((kind, project, event))
        return True

    monkeypatch.setattr(router, "spawn_worker", fake_spawn)
    return calls


def _run(event: str, payload: Any, *extra: str) -> str:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    out = io.StringIO()
    assert router.main([event, *extra], stdin=io.StringIO(raw), stdout=out) == 0
    return out.getvalue()


def _single_json(text: str) -> Any:
    lines = text.splitlines()
    assert len(lines) == 1, text
    return json.loads(lines[0])


# ---------------------------------------------------------------------------
# Registry reading
# ---------------------------------------------------------------------------


def test_registry_constants_match_workspace_registry() -> None:
    assert router.REGISTRY_FILENAME == workspace_registry.REGISTRY_FILENAME
    assert router.REGISTRY_VERSION == workspace_registry.REGISTRY_VERSION


def test_registry_is_read_without_pydantic_models(tmp_path: Path) -> None:
    mono = tmp_path / "mono"
    _project(mono / "svc")
    _project(mono / "svc" / "inner")
    (mono / "workspace.yaml").write_text("")
    register_workspace(mono, name="mono", projects=[("svc", "svc"), ("inner", "svc/inner")])

    projects = router.load_registered_projects()

    assert sorted(name for name, _ in projects) == ["inner", "svc"]
    deep = router.resolve_registered(str(mono.resolve() / "svc/inner/src/main.py"), projects)
    assert deep is not None and deep.name == "inner"
    shallow = router.resolve_registered(str(mono.resolve() / "svc/src/main.py"), projects)
    assert shallow is not None and shallow.name == "svc"


def test_broken_or_newer_registry_yields_no_projects(
    isolate_agentscaffold_home: Path,
) -> None:
    registry = isolate_agentscaffold_home / router.REGISTRY_FILENAME
    registry.write_text("{not: [valid")
    assert router.load_registered_projects() == []
    registry.write_text(f"version: {router.REGISTRY_VERSION + 1}\nworkspaces: []\n")
    assert router.load_registered_projects() == []


# ---------------------------------------------------------------------------
# Edit events
# ---------------------------------------------------------------------------


def test_edit_outside_every_project_answers_and_spawns_nothing(
    tmp_path: Path, spawned: list[Any]
) -> None:
    register_workspace(_project(tmp_path / "alpha"), name="alpha")
    elsewhere = tmp_path / "elsewhere" / "x.py"

    assert _single_json(_run("cursor-after-edit", {"file_path": str(elsewhere)})) == {}
    assert _single_json(_run("cursor-pre-edit", {"tool_input": {"file_path": str(elsewhere)}})) == {
        "permission": "allow"
    }
    assert spawned == []


def test_edit_inside_a_project_schedules_its_index(tmp_path: Path, spawned: list[Any]) -> None:
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")

    _run("cursor-after-edit", {"file_path": str(alpha / "src" / "main.py")})
    _run("claude-post-tool-use", {"tool_input": {"file_path": "src/main.py"}, "cwd": str(alpha)})

    assert [(k, p.name, p.root, e) for k, p, e in spawned] == [
        ("index", "alpha", alpha, "cursor-after-edit"),
        ("index", "alpha", alpha, "claude-post-tool-use"),
    ]


def test_edits_to_state_directories_never_retrigger(tmp_path: Path, spawned: list[Any]) -> None:
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")
    _run("cursor-after-edit", {"file_path": str(alpha / ".scaffold" / "knowledge_graph.db")})
    assert spawned == []


def test_project_scope_serves_an_unregistered_repo_from_its_cwd(
    tmp_path: Path, spawned: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _project(tmp_path / "repo")
    monkeypatch.chdir(repo)
    payload = {"file_path": str(repo / "src" / "main.py")}

    _run("cursor-after-edit", payload)
    assert spawned == []

    _run("cursor-after-edit", payload, "--scope", "project")
    assert [(p.name, p.root) for _, p, _ in spawned] == [(None, repo)]


def test_git_post_commit_schedules_embeddings(
    tmp_path: Path, spawned: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")
    monkeypatch.chdir(alpha)
    assert _run("git-post-commit", "", "--scope", "project") == ""
    assert [(k, p.root) for k, p, _ in spawned] == [("embed", alpha)]


# ---------------------------------------------------------------------------
# Protected files
# ---------------------------------------------------------------------------


def test_pre_edit_denies_read_only_paths_in_a_registered_project(
    tmp_path: Path, spawned: list[Any]
) -> None:
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")
    target = alpha / "docs" / "ai" / "system_architecture.md"

    cursor = _single_json(_run("cursor-pre-edit", {"tool_input": {"file_path": str(target)}}))
    assert cursor["permission"] == "deny"
    assert "docs/ai/system_architecture.md" in cursor["user_message"]
    assert "protect_read_only_paths: false" in cursor["agent_message"]

    claude = _single_json(_run("claude-pre-edit", {"tool_input": {"file_path": str(target)}}))
    out = claude["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"

    allowed = _run("claude-pre-edit", {"tool_input": {"file_path": str(alpha / "src/main.py")}})
    assert allowed == ""
    assert spawned == []


def test_pre_edit_check_can_be_switched_off(tmp_path: Path) -> None:
    alpha = _project(
        tmp_path / "alpha",
        config="agents:\n  agents_md: false\n  protect_read_only_paths: false\n",
    )
    register_workspace(alpha, name="alpha")
    payload = {"tool_input": {"file_path": str(alpha / "scaffold.yaml")}}
    assert _single_json(_run("cursor-pre-edit", payload)) == {"permission": "allow"}


# ---------------------------------------------------------------------------
# Guidance delivery
# ---------------------------------------------------------------------------


def _write_manifest(home: Path, manifest: dict[str, Any]) -> None:
    (home / router.MANIFEST_FILENAME).write_text(json.dumps(manifest))


def test_workspace_open_returns_shared_and_matching_pointer_plugins(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    mono = tmp_path / "mono"
    _project(mono / "a")
    _project(mono / "b")
    (mono / "workspace.yaml").write_text("")
    register_workspace(mono, name="mono", projects=[("a", "a"), ("b", "b")])
    other = _project(tmp_path / "other")
    register_workspace(other, name="other")
    plugins = {name: tmp_path / "plugins" / name for name in ("shared", "a", "b", "other")}
    for path in plugins.values():
        path.mkdir(parents=True)
    _write_manifest(
        isolate_agentscaffold_home,
        {
            "cursor_plugins": {
                "shared": str(plugins["shared"]),
                "projects": {n: str(plugins[n]) for n in ("a", "b", "other")},
            }
        },
    )

    opened = _single_json(_run("cursor-workspace-open", {"workspace_roots": [str(mono)]}))
    assert opened == {"pluginPaths": [str(plugins[n]) for n in ("shared", "a", "b")]}

    inside = _single_json(
        _run("cursor-workspace-open", {"workspace_roots": [str(mono / "b" / "src")]})
    )
    assert inside == {"pluginPaths": [str(plugins["shared"]), str(plugins["b"])]}

    unrelated = _run("cursor-workspace-open", {"workspace_roots": [str(tmp_path / "nowhere")]})
    assert _single_json(unrelated) == {}


def test_workspace_open_skips_plugins_deleted_since_install(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")
    _write_manifest(
        isolate_agentscaffold_home,
        {"cursor_plugins": {"shared": str(tmp_path / "gone"), "projects": {"alpha": "/gone"}}},
    )
    assert _single_json(_run("cursor-workspace-open", {"workspace_roots": [str(alpha)]})) == {}


def test_claude_session_start_adds_pointer_context(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")
    context = tmp_path / "alpha.md"
    context.write_text("# AgentScaffold project: alpha\n")
    _write_manifest(isolate_agentscaffold_home, {"claude_context": {"alpha": str(context)}})

    out = _single_json(_run("claude-session-start", {"cwd": str(alpha)}))
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    text = out["hookSpecificOutput"]["additionalContext"]
    assert text.startswith("AgentScaffold MCP tools")
    assert "project: alpha" in text
    assert len(text) <= 9000
    assert _run("claude-session-start", {"cwd": str(tmp_path / "nowhere")}) == ""


def test_session_text_drops_the_body_when_claude_md_already_has_it(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    from agentscaffold.rendering import MANAGED_BLOCK_BEGIN

    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")
    (alpha / "CLAUDE.md").write_text(f"{MANAGED_BLOCK_BEGIN}\nrouting\n", encoding="utf-8")
    context = tmp_path / "alpha.md"
    context.write_text("# AgentScaffold project: alpha\n", encoding="utf-8")
    _write_manifest(isolate_agentscaffold_home, {"claude_context": {"alpha": str(context)}})

    out = _single_json(_run("claude-session-start", {"cwd": str(alpha)}))
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "project: alpha" in text
    assert "Intent Map" not in text
    assert len(text) <= 9000


def test_prompt_hook_names_the_matched_tool(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")

    out = _single_json(
        _run("claude-user-prompt", {"cwd": str(alpha), "prompt": "please review plan 12"})
    )
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "scaffold_prepare_review" in text
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert _run("claude-user-prompt", {"cwd": str(alpha), "prompt": "hello"}) == ""
    outside = _run(
        "claude-user-prompt",
        {"cwd": str(tmp_path / "nowhere"), "prompt": "review plan 12"},
    )
    assert outside == ""


# ---------------------------------------------------------------------------
# One JSON object, always
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[1, 2]", '{"file_path": 7}', "x" * (router.MAX_STDIN_BYTES + 10)],
)
def test_unusable_stdin_still_allows(raw: str, spawned: list[Any]) -> None:
    assert _single_json(_run("cursor-pre-edit", raw)) == {"permission": "allow"}
    assert _single_json(_run("cursor-after-edit", raw)) == {}
    assert spawned == []


def test_internal_error_and_stray_output_still_yield_one_allow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def noisy(event: str, payload: dict[str, Any], scope: str) -> str:
        print("stray output from deep inside")
        raise RuntimeError("boom")

    monkeypatch.setattr(router, "handle_event", noisy)
    out = io.StringIO()
    router.main(["cursor-pre-edit"], stdin=io.StringIO("{}"), stdout=out)

    assert _single_json(out.getvalue()) == {"permission": "allow"}
    err = capsys.readouterr().err
    assert "stray output" in err and "RuntimeError: boom" in err


def test_unknown_event_and_disable_switch(
    tmp_path: Path, spawned: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _single_json(_run("no-such-event", "{}")) == {}
    alpha = _project(tmp_path / "alpha")
    register_workspace(alpha, name="alpha")
    monkeypatch.setenv(router.DISABLE_ENV, "1")
    _run("cursor-after-edit", {"file_path": str(alpha / "src" / "main.py")})
    assert spawned == []


def test_outside_path_runs_light_in_a_fresh_interpreter(tmp_path: Path) -> None:
    """The path every edit in every workspace takes: no pydantic, config or graph."""
    register_workspace(_project(tmp_path / "alpha"), name="alpha")
    probe = (
        "import sys\n"
        "from agentscaffold.hooks import router\n"
        "router.main(['cursor-pre-edit'])\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] == 'pydantic'"
        " or m in ('agentscaffold.config', 'agentscaffold.cli')"
        " or m.startswith('agentscaffold.graph'))\n"
        "print('HEAVY=' + ','.join(heavy), file=sys.stderr)\n"
    )
    payload = json.dumps({"tool_input": {"file_path": str(tmp_path / "elsewhere" / "x.py")}})
    env = {**os.environ, "SCAFFOLD_HOOK_TIMING": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=True,
    )

    assert _single_json(proc.stdout) == {"permission": "allow"}
    assert "HEAVY=\n" in proc.stderr
    timing = next(line for line in proc.stderr.splitlines() if "cursor-pre-edit:" in line)
    assert float(timing.rsplit(" ", 1)[1].rstrip("s")) < 0.1


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class _FakeRun:
    """Stands in for ``subprocess.run``; can simulate an edit arriving mid-index."""

    def __init__(self, on_call: Any = None) -> None:
        self.calls: list[list[str]] = []
        self.on_call = on_call

    def __call__(self, argv: list[str], **kwargs: Any) -> None:
        self.calls.append(argv)
        if self.on_call is not None:
            self.on_call(len(self.calls))


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


@pytest.fixture()
def fake_scaffold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "scaffold_command", lambda: ["scaffold"])


def test_worker_state_dir_follows_resolve_db_path(tmp_path: Path) -> None:
    from agentscaffold.config import load_config
    from agentscaffold.paths import resolve_db_path

    in_tree = _project(tmp_path / "plain")
    state, _ = worker.project_state(in_tree)
    assert state == resolve_db_path(load_config(in_tree / "scaffold.yaml"), start=in_tree).parent

    registered = _project(tmp_path / "registered")
    register_workspace(registered, name="registered")
    state, _ = worker.project_state(registered)
    expected = resolve_db_path(load_config(registered / "scaffold.yaml"), start=registered)
    assert state == expected.parent


def test_worker_indexes_and_records_last_run(tmp_path: Path, fake_scaffold: None) -> None:
    root = _project(tmp_path / "alpha")
    run = _FakeRun()
    assert worker.run_index_worker(root, event="cursor-after-edit", run=run) == "indexed"
    assert run.calls == [["scaffold", "index", "--incremental"]]
    state, _ = worker.project_state(root)
    assert worker.read_last_run(state)["event"] == "cursor-after-edit"
    assert not (state / worker.INDEX_LOCK).exists()


def test_worker_reruns_when_an_edit_lands_mid_index(tmp_path: Path, fake_scaffold: None) -> None:
    root = _project(tmp_path / "alpha")
    state, _ = worker.project_state(root)
    clock = _Clock()

    def edit_during_first_run(n: int) -> None:
        if n == 1:
            (state / worker.INDEX_REQUEST).write_text(f"{clock.now + 0.5}\n")

    run = _FakeRun(edit_during_first_run)
    assert worker.run_index_worker(root, run=run, clock=clock) == "indexed"
    assert len(run.calls) == 2


def test_worker_is_single_flight_and_reaps_stale_locks(tmp_path: Path, fake_scaffold: None) -> None:
    root = _project(tmp_path / "alpha")
    state, _ = worker.project_state(root)
    state.mkdir(parents=True, exist_ok=True)
    lock = state / worker.INDEX_LOCK
    lock.mkdir()

    run = _FakeRun()
    assert worker.run_index_worker(root, run=run) == "busy"
    assert run.calls == []
    assert (state / worker.INDEX_REQUEST).is_file()

    old = lock.stat().st_mtime - worker.LOCK_STALE_SECONDS - 5
    os.utime(lock, (old, old))
    assert worker.run_index_worker(root, run=run) == "indexed"
    assert len(run.calls) == 1


def test_worker_throttles_on_min_interval(tmp_path: Path, fake_scaffold: None) -> None:
    root = _project(
        tmp_path / "alpha",
        config="agents:\n  agents_md: false\ngraph:\n  incremental_min_interval_seconds: 60\n",
    )
    run = _FakeRun()
    clock = _Clock()
    assert worker.run_index_worker(root, run=run, clock=clock) == "indexed"
    assert worker.run_index_worker(root, run=run, clock=clock) == "throttled"
    assert len(run.calls) == 1


def test_wait_for_graph_writer_gives_up_after_timeout(tmp_path: Path) -> None:
    (tmp_path / worker.GRAPH_WRITE_LOCK_NAME).mkdir()
    clock = _Clock(0.0)
    assert not worker.wait_for_graph_writer(tmp_path, timeout=5, clock=clock, sleep=lambda _: None)
    (tmp_path / worker.GRAPH_WRITE_LOCK_NAME).rmdir()
    assert worker.wait_for_graph_writer(tmp_path, timeout=5, clock=clock, sleep=lambda _: None)


def test_embed_worker_defers_to_a_running_index(tmp_path: Path, fake_scaffold: None) -> None:
    root = _project(tmp_path / "alpha")
    state, _ = worker.project_state(root)
    state.mkdir(parents=True, exist_ok=True)
    (state / worker.INDEX_LOCK).mkdir()
    run = _FakeRun()
    assert worker.run_embed_worker(root, run=run) == "deferred"
    (state / worker.INDEX_LOCK).rmdir()
    assert worker.run_embed_worker(root, run=run) == "embedded"
    assert run.calls == [["scaffold", "index", "--incremental", "--embeddings"]]


def test_hook_command_runs_the_router(cli_runner: Any) -> None:
    from agentscaffold.cli import app

    result = cli_runner.invoke(app, ["hook", "cursor-pre-edit"], input="{}")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"permission": "allow"}
