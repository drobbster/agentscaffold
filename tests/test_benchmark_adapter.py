"""Offline tests for the guarded mini-swe-agent benchmark adapter."""

from __future__ import annotations

import importlib.util

import pytest

from agentscaffold.benchmark import adapter
from agentscaffold.benchmark.environment import create_workspace_plan
from agentscaffold.benchmark.models import get_model
from agentscaffold.benchmark.runner import BenchmarkRunRequest
from agentscaffold.benchmark.tasks import select_tasks


def _request() -> BenchmarkRunRequest:
    return BenchmarkRunRequest(
        model=get_model("claude-haiku"),
        task_slice="0:1",
        max_cost_usd=1.0,
        workers=1,
        dry_run=False,
        confirm_live=True,
    )


def test_ensure_live_dependencies_fails_with_actionable_install(monkeypatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(adapter.BenchmarkDependencyError, match="agentscaffold\\[benchmark\\]"):
        adapter.ensure_live_dependencies()


def test_build_agent_prompt_mentions_arm_guidance(tmp_path) -> None:
    root = tmp_path / "package"
    repo = root / "tests/fixtures/sample_repo"
    repo.mkdir(parents=True)
    (repo / "router.py").write_text("# sample")
    task = select_tasks("0:1")[0]
    arm = adapter.BenchmarkArm(
        name="equipped",
        description="test",
        scaffold_enabled=True,
        prompt_guidance="Use graph evidence.",
    )
    plan = create_workspace_plan(
        task=task,
        arm=arm,
        seed=1,
        package_root=root,
        output_root=tmp_path / "out",
    )

    prompt = adapter.build_agent_prompt(arm, plan)

    assert task.title in prompt
    assert "Use graph evidence." in prompt
    assert "scaffold-* wrappers" in prompt


def test_container_setup_commands_include_wrappers_for_equipped_arm(tmp_path) -> None:
    root = tmp_path / "package"
    repo = root / "tests/fixtures/sample_repo"
    repo.mkdir(parents=True)
    (repo / "router.py").write_text("# sample")
    task = select_tasks("0:1")[0]
    arm = adapter.BenchmarkArm(
        name="equipped",
        description="test",
        scaffold_enabled=True,
        setup_commands=("scaffold index",),
    )
    plan = create_workspace_plan(
        task=task,
        arm=arm,
        seed=1,
        package_root=root,
        output_root=tmp_path / "out",
    )

    commands = adapter.build_container_setup_commands(plan)

    assert any("scaffold index" in command for command in commands)
    assert any("scaffold-search" in command for command in commands)


def test_executor_runs_fake_mini_swe_agent_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(adapter, "ensure_live_dependencies", lambda: None)
    monkeypatch.setattr(adapter, "_copy_workspace_to_container", lambda _env, _workspace: None)

    class FakeEnv:
        def __init__(self, image: str):
            self.image = image
            self.container_id = "fake-container"
            self.commands: list[str] = []
            self.stopped = False

        def start(self) -> None:
            self.commands.append("start")

        def execute(self, action: dict) -> dict:
            command = action["command"]
            self.commands.append(command)
            return {"returncode": 0, "output": "ok"}

        def stop(self) -> None:
            self.stopped = True

    class FakeAgent:
        def __init__(self, model, env, **kwargs):
            self.model = model
            self.env = env
            self.kwargs = kwargs
            self.cost = 0.03
            self.n_calls = 2
            self.messages = [
                {
                    "content": "ran scaffold search",
                    "extra": {"actions": [{"command": "scaffold-search router"}]},
                }
            ]

        def run(self, prompt: str) -> dict:
            self.prompt = prompt
            return {"exit_status": "submitted"}

        def serialize(self, extra: dict) -> dict:
            return {
                "info": {"model_stats": {"instance_cost": self.cost, "api_calls": self.n_calls}},
                "messages": self.messages,
                "extra": extra,
            }

    def fake_get_model(config: dict):
        return {"config": config}

    monkeypatch.setattr(
        adapter,
        "_load_mini_swe_agent_classes",
        lambda: (fake_get_model, FakeEnv, FakeAgent),
    )
    root = tmp_path / "package"
    repo = root / "tests/fixtures/sample_repo"
    repo.mkdir(parents=True)
    (repo / "router.py").write_text("# sample")
    task = select_tasks("0:1")[0]
    plan = create_workspace_plan(
        task=task,
        arm=adapter.BenchmarkArm(name="baseline", description="test", scaffold_enabled=False),
        seed=1,
        package_root=root,
        output_root=tmp_path / "out",
    )

    execution = adapter.MiniSweAgentExecutor()(_request(), plan)

    assert execution.validation_exit_code == 0
    assert execution.wall_time_seconds is not None
    assert execution.trajectory is not None
    assert execution.trajectory["validation_exit_code"] == 0
    assert execution.executed_commands == ("scaffold-search router",)
