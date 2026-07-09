"""Guarded mini-swe-agent adapter for live AgentScaffold Benchmark runs."""

from __future__ import annotations

import importlib.util
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentscaffold.benchmark.arms import BenchmarkArm
from agentscaffold.benchmark.environment import TaskEnvironmentPlan, render_setup_script
from agentscaffold.benchmark.runner import ArmExecution, BenchmarkRunRequest
from agentscaffold.benchmark.tool_wrappers import render_install_command

MINI_SWE_AGENT_MODULES = ("minisweagent", "litellm")


class BenchmarkDependencyError(RuntimeError):
    """Raised when optional live benchmark dependencies are unavailable."""


@dataclass(frozen=True)
class MiniSweAgentAdapterConfig:
    """Configuration for the guarded mini-swe-agent adapter."""

    docker_image: str = "python:3.11-slim"
    step_limit: int = 30
    cost_limit_usd: float | None = None
    command_timeout_seconds: int = 120


def missing_live_modules() -> tuple[str, ...]:
    """Return optional live benchmark modules that are not importable."""

    return tuple(
        module for module in MINI_SWE_AGENT_MODULES if importlib.util.find_spec(module) is None
    )


def ensure_live_dependencies() -> None:
    """Raise with an actionable message when live dependencies are absent."""

    missing = missing_live_modules()
    if missing:
        joined = ", ".join(missing)
        raise BenchmarkDependencyError(
            f"Missing optional live benchmark dependencies: {joined}. "
            "Install with: pip install 'agentscaffold[benchmark]'"
        )


class MiniSweAgentExecutor:
    """Adapter boundary for executing one arm through mini-swe-agent.

    This class keeps optional imports out of the base package import path. The
    concrete mini-swe-agent run loop is intentionally centralized here so the
    rest of the benchmark package can be tested without live dependencies.
    """

    def __init__(self, config: MiniSweAgentAdapterConfig | None = None):
        self.config = config or MiniSweAgentAdapterConfig()

    def __call__(self, request: BenchmarkRunRequest, plan: TaskEnvironmentPlan) -> ArmExecution:
        ensure_live_dependencies()
        start = time.monotonic()
        trajectory = self._run_mini_swe_agent(request, plan)
        elapsed = time.monotonic() - start
        commands = tuple(_extract_commands(trajectory))
        return ArmExecution(
            validation_exit_code=_extract_validation_exit_code(trajectory),
            transcript_text=_extract_transcript_text(trajectory),
            trajectory=trajectory,
            executed_commands=commands,
            wall_time_seconds=elapsed,
            exit_status=str(trajectory.get("exit_status", "completed")),
            error=trajectory.get("error"),
        )

    def _run_mini_swe_agent(
        self,
        request: BenchmarkRunRequest,
        plan: TaskEnvironmentPlan,
    ) -> dict[str, Any]:
        model_factory, environment_class, agent_class = _load_mini_swe_agent_classes()
        _ensure_supported_environment_api(environment_class)
        model = model_factory(config=_model_config(request))
        env = environment_class(image=self.config.docker_image)
        agent = None
        try:
            env.start()
            _copy_workspace_to_container(env, plan.workspace)
            for command in build_container_setup_commands(plan):
                _execute(env, command, timeout=self.config.command_timeout_seconds)

            agent = agent_class(
                model,
                env,
                step_limit=self.config.step_limit,
                cost_limit=self.config.cost_limit_usd or request.max_cost_usd,
            )
            info = agent.run(build_agent_prompt(plan.arm, plan))
            validation_exit_code = _run_validation(env, plan, self.config.command_timeout_seconds)
            trajectory = _serialize_agent(agent, info)
            trajectory["validation_exit_code"] = validation_exit_code
            trajectory["exit_status"] = info.get(
                "exit_status", trajectory.get("exit_status", "completed")
            )
            return trajectory
        finally:
            if agent is not None and hasattr(agent, "save"):
                # The summary JSON is the canonical artifact; individual trajectory
                # persistence can be added once live smoke confirms mini-swe-agent's
                # installed save path behavior across versions.
                pass
            if hasattr(env, "stop"):
                env.stop()


def build_agent_prompt(arm: BenchmarkArm, plan: TaskEnvironmentPlan) -> str:
    """Build the first user task prompt for a benchmark arm."""

    setup_note = (
        "AgentScaffold setup is available through the scaffold-* wrappers."
        if arm.scaffold_enabled
        else "Do not use AgentScaffold commands in this baseline arm."
    )
    return (
        f"Task: {plan.task.title}\n\n"
        f"{plan.task.prompt}\n\n"
        f"Arm: {arm.name}\n"
        f"Guidance: {arm.prompt_guidance}\n"
        f"{setup_note}\n"
    )


def build_container_setup_commands(plan: TaskEnvironmentPlan) -> tuple[str, ...]:
    """Return setup commands to run inside the task container."""

    commands = [render_setup_script(plan, workspace="/testbed")]
    if plan.arm.scaffold_enabled:
        commands.append(render_install_command())
    return tuple(command for command in commands if command.strip())


def _load_mini_swe_agent_classes() -> tuple[Callable[..., Any], type[Any], type[Any]]:
    from importlib import import_module

    model_factory = import_module("minisweagent.models").get_model
    environment_class = import_module("minisweagent.environments.docker").DockerEnvironment
    agent_class = import_module("minisweagent.agents.default").DefaultAgent
    return model_factory, environment_class, agent_class


def _ensure_supported_environment_api(environment_class: type[Any]) -> None:
    """Fail closed when mini-swe-agent's Docker API has drifted."""
    missing = [name for name in ("start", "execute") if not hasattr(environment_class, name)]
    if missing:
        joined = ", ".join(f"DockerEnvironment.{name}" for name in missing)
        raise BenchmarkDependencyError(
            "Docker execution is not implemented yet for the installed mini-swe-agent API. "
            f"Missing expected methods: {joined}. Use a custom executor or a compatible "
            "mini-swe-agent release."
        )


def _model_config(request: BenchmarkRunRequest) -> dict[str, Any]:
    return {
        "model_name": request.model.model_id,
        "cost_tracking": "ignore_errors",
        "model_kwargs": {
            "max_tokens": request.model.max_tokens,
            "temperature": request.model.temperature,
        },
    }


def _copy_workspace_to_container(env: Any, workspace: Path) -> None:
    container_id = getattr(env, "_container_id", None) or getattr(env, "container_id", None)
    if not container_id:
        raise RuntimeError("Unable to locate Docker container id for benchmark environment.")
    _execute(env, "rm -rf /testbed && mkdir -p /testbed", timeout=30)
    subprocess.run(
        ["docker", "cp", f"{workspace}/.", f"{container_id}:/testbed"],
        check=True,
        capture_output=True,
        text=True,
    )


def _execute(env: Any, command: str, *, timeout: int) -> dict[str, Any]:
    result = env.execute({"command": command, "timeout": timeout})
    return result if isinstance(result, dict) else {"output": str(result), "returncode": 0}


def _run_validation(
    env: Any,
    plan: TaskEnvironmentPlan,
    timeout: int,
) -> int | None:
    if not plan.task.validation_command:
        return None
    result = _execute(env, f"cd /testbed && {plan.task.validation_command}", timeout=timeout)
    return int(result.get("returncode", 0))


def _serialize_agent(agent: Any, info: dict[str, Any]) -> dict[str, Any]:
    if hasattr(agent, "serialize"):
        serialized = agent.serialize(
            {"info": {"benchmark": {"exit_status": info.get("exit_status")}}}
        )
        if isinstance(serialized, dict):
            return serialized

    model_stats = {
        "instance_cost": getattr(agent, "cost", None),
        "api_calls": getattr(agent, "n_calls", 0),
    }
    return {
        "info": {"model_stats": model_stats},
        "messages": getattr(agent, "messages", []),
        "exit_status": info.get("exit_status", "completed"),
    }


def _extract_commands(trajectory: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for message in trajectory.get("messages", []):
        extra = message.get("extra", {}) if isinstance(message, dict) else {}
        for action in extra.get("actions", []):
            command = action.get("command") if isinstance(action, dict) else None
            if command:
                commands.append(str(command))
    return commands


def _extract_validation_exit_code(trajectory: dict[str, Any]) -> int | None:
    value = trajectory.get("validation_exit_code")
    if value is None:
        return None
    return int(value)


def _extract_transcript_text(trajectory: dict[str, Any]) -> str:
    parts: list[str] = []
    for message in trajectory.get("messages", []):
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)
