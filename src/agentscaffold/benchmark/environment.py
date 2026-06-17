"""Isolated task workspace helpers for AgentScaffold Benchmark."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agentscaffold.benchmark.arms import BenchmarkArm
from agentscaffold.benchmark.tasks import BenchmarkTask


@dataclass(frozen=True)
class TaskEnvironmentPlan:
    """Resolved per-arm task environment plan."""

    task: BenchmarkTask
    arm: BenchmarkArm
    seed: int
    source_repo: Path
    workspace: Path
    docker_required: bool = True


def resolve_task_repo(task: BenchmarkTask, package_root: Path) -> Path:
    """Resolve a task repo path relative to the package root."""

    repo = Path(task.repo_path)
    if not repo.is_absolute():
        repo = package_root / repo
    resolved = repo.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Benchmark task repo not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Benchmark task repo is not a directory: {resolved}")
    return resolved


def create_workspace_plan(
    *,
    task: BenchmarkTask,
    arm: BenchmarkArm,
    seed: int,
    package_root: Path,
    output_root: Path | None = None,
) -> TaskEnvironmentPlan:
    """Create an isolated per-arm workspace by copying the source task repo."""

    source_repo = resolve_task_repo(task, package_root)
    root = output_root or Path(tempfile.mkdtemp(prefix="agentscaffold-benchmark-"))
    workspace = root / task.task_id / arm.name / f"seed-{seed}" / "repo"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source_repo,
        workspace,
        ignore=shutil.ignore_patterns(
            ".git",
            ".scaffold",
            ".pytest_cache",
            "__pycache__",
            "*.pyc",
        ),
    )
    return TaskEnvironmentPlan(
        task=task,
        arm=arm,
        seed=seed,
        source_repo=source_repo,
        workspace=workspace,
    )


def render_setup_script(plan: TaskEnvironmentPlan, workspace: str | Path | None = None) -> str:
    """Render shell setup commands for a task workspace."""

    target = workspace if workspace is not None else plan.workspace
    commands = [f"cd {target}"]
    commands.extend(plan.arm.setup_commands)
    return "\n".join(commands)
