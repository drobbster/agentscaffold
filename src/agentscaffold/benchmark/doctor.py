"""Preflight checks for AgentScaffold Benchmark."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from agentscaffold.benchmark.models import BenchmarkModel

BENCHMARK_EXTRA = "agentscaffold[benchmark]"
REQUIRED_BENCHMARK_MODULES = ("minisweagent", "litellm", "datasets")


class CheckStatus(str, Enum):
    """Status for a benchmark preflight check."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    """A single benchmark readiness check."""

    name: str
    status: CheckStatus
    message: str
    required: bool = True


@dataclass(frozen=True)
class DoctorReport:
    """Aggregate benchmark readiness report."""

    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        """Return true when no required check failed."""

        return all(check.status != CheckStatus.FAIL or not check.required for check in self.checks)

    @property
    def failed_required(self) -> tuple[CheckResult, ...]:
        """Return required checks that failed."""

        return tuple(
            check for check in self.checks if check.required and check.status == CheckStatus.FAIL
        )


def run_doctor(
    *,
    model: BenchmarkModel,
    env: Mapping[str, str] | None = None,
    require_api_key: bool = False,
    require_docker: bool = True,
    require_live_dependencies: bool = True,
) -> DoctorReport:
    """Run benchmark readiness checks.

    The default is strict enough for a live benchmark preflight. Callers can
    relax key checks for `doctor` without `--live` and for offline dry-runs.
    """

    resolved_env = env if env is not None else os.environ
    checks: list[CheckResult] = []
    if require_docker:
        checks.append(check_docker())
    if require_live_dependencies:
        checks.extend(check_live_dependencies())
    checks.append(check_api_key(model, resolved_env, required=require_api_key))
    checks.append(check_pricing(model))
    return DoctorReport(tuple(checks))


def check_docker() -> CheckResult:
    """Check that Docker is installed and the daemon responds."""

    docker = shutil.which("docker")
    if docker is None:
        return CheckResult(
            name="docker",
            status=CheckStatus.FAIL,
            message="Docker executable not found; live benchmark runs require container isolation.",
        )

    try:
        result = subprocess.run(
            [docker, "info", "--format", "{{.ServerVersion}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(
            name="docker",
            status=CheckStatus.FAIL,
            message=f"Docker daemon check failed: {exc}",
        )

    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "docker info failed"
        return CheckResult(
            name="docker",
            status=CheckStatus.FAIL,
            message=f"Docker daemon unavailable: {details}",
        )

    version = result.stdout.strip() or "unknown"
    return CheckResult(
        name="docker",
        status=CheckStatus.PASS,
        message=f"Docker daemon available ({version}).",
    )


def check_live_dependencies() -> tuple[CheckResult, ...]:
    """Check optional live benchmark Python dependencies."""

    results: list[CheckResult] = []
    for module in REQUIRED_BENCHMARK_MODULES:
        if importlib.util.find_spec(module) is None:
            results.append(
                CheckResult(
                    name=f"python:{module}",
                    status=CheckStatus.FAIL,
                    message=(
                        f"Missing optional dependency '{module}'. "
                        f"Install with: pip install '{BENCHMARK_EXTRA}'"
                    ),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"python:{module}",
                    status=CheckStatus.PASS,
                    message=f"Optional dependency '{module}' is installed.",
                )
            )
    return tuple(results)


def check_api_key(
    model: BenchmarkModel,
    env: Mapping[str, str],
    *,
    required: bool,
) -> CheckResult:
    """Check whether the selected model's API key is present without printing it."""

    if env.get(model.api_key_env):
        return CheckResult(
            name="api-key",
            status=CheckStatus.PASS,
            message=f"{model.api_key_env} is present for {model.provider}.",
            required=required,
        )

    status = CheckStatus.FAIL if required else CheckStatus.WARN
    return CheckResult(
        name="api-key",
        status=status,
        message=(
            f"{model.api_key_env} is not set for model '{model.name}'. "
            "Live runs will not start until the key is available."
        ),
        required=required,
    )


def check_pricing(model: BenchmarkModel) -> CheckResult:
    """Check that the benchmark can identify a cost source for the selected model."""

    if model.pricing_source == "litellm":
        return CheckResult(
            name="pricing",
            status=CheckStatus.PASS,
            message=(
                f"Pricing source is '{model.pricing_source}' for {model.model_id}. "
                "Cost will be read from the live model runner when available."
            ),
        )

    return CheckResult(
        name="pricing",
        status=CheckStatus.FAIL,
        message=f"No supported pricing source configured for {model.model_id}.",
    )
