"""Configuration schema and loading for scaffold.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Gate configuration
# ---------------------------------------------------------------------------


class DraftToReviewGates(BaseModel):
    plan_lint: bool = True
    architecture_layer_check: bool = True


class ReviewToReadyGates(BaseModel):
    devils_advocate: bool = True
    expansion_review: bool = True
    domain_reviews: list[str] = Field(default_factory=list)
    spike_for_high_uncertainty: bool = True
    interface_contracts: bool = True
    security_review: bool = True


class ReadyToInProgressGates(BaseModel):
    review_checklist: bool = True
    approval_gates: bool = True
    interactive_gate: bool = True


class InProgressToCompleteGates(BaseModel):
    all_steps_checked: bool = True
    validation_commands: bool = True
    tests_pass: bool = True
    retrospective: bool = True
    domain_implementation_review: bool = False


class GatesConfig(BaseModel):
    draft_to_review: DraftToReviewGates = Field(default_factory=DraftToReviewGates)
    review_to_ready: ReviewToReadyGates = Field(default_factory=ReviewToReadyGates)
    ready_to_in_progress: ReadyToInProgressGates = Field(default_factory=ReadyToInProgressGates)
    in_progress_to_complete: InProgressToCompleteGates = Field(
        default_factory=InProgressToCompleteGates
    )


# ---------------------------------------------------------------------------
# Approval configuration
# ---------------------------------------------------------------------------


class ApprovalConfig(BaseModel):
    breaking_changes: bool = True
    security_sensitive: bool = True
    data_migrations: bool = True
    infrastructure: bool = True
    external_apis: bool = True


# ---------------------------------------------------------------------------
# Standards configuration
# ---------------------------------------------------------------------------


class StandardsConfig(BaseModel):
    core: list[str] = Field(default_factory=lambda: ["errors", "logging", "config", "testing"])
    domain: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prohibitions configuration
# ---------------------------------------------------------------------------


class ProhibitionsConfig(BaseModel):
    emojis: bool = False
    patterns: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent integration configuration
# ---------------------------------------------------------------------------


class AgentsConfig(BaseModel):
    agents_md: bool = True
    cursor_rules: bool = True


# ---------------------------------------------------------------------------
# Semi-autonomous configuration
# ---------------------------------------------------------------------------


class SafetyConfig(BaseModel):
    read_only_paths: list[str] = Field(
        default_factory=lambda: [
            "docs/ai/system_architecture.md",
            "scaffold.yaml",
            ".github/",
        ]
    )
    require_approval_paths: list[str] = Field(default_factory=lambda: ["infra/", "docs/security/"])


class NotificationsConfig(BaseModel):
    enabled: bool = True
    channel: str = "github_issue"
    slack_webhook_env: str = "SLACK_WEBHOOK_URL"
    notify_on: list[str] = Field(
        default_factory=lambda: [
            "plan_complete",
            "escalation",
            "validation_failure",
            "approval_required",
        ]
    )


class CautiousExecutionConfig(BaseModel):
    max_fix_attempts: int = 2
    max_new_files_before_escalation: int = 5


class SemiAutonomousConfig(BaseModel):
    enabled: bool = False
    session_tracking: bool = True
    context_handoff: bool = True
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    cautious_execution: CautiousExecutionConfig = Field(default_factory=CautiousExecutionConfig)


# ---------------------------------------------------------------------------
# Task runner configuration
# ---------------------------------------------------------------------------


class TaskRunnerConfig(BaseModel):
    justfile: bool = True
    makefile: bool = True


# ---------------------------------------------------------------------------
# CI configuration
# ---------------------------------------------------------------------------


class CIConfig(BaseModel):
    provider: str = "github"
    security_scanning: bool = True
    study_lint: bool = True
    plan_lint: bool = False
    semi_autonomous_pr_checks: bool = False


# ---------------------------------------------------------------------------
# Import configuration
# ---------------------------------------------------------------------------


class ImportConfig(BaseModel):
    conversation_dir: str = "data/conversations"


# ---------------------------------------------------------------------------
# Graph (knowledge graph) configuration
# ---------------------------------------------------------------------------


class LayerMapping(BaseModel):
    pattern: str
    layer: int


class GraphConfig(BaseModel):
    db_path: str = ".scaffold/graph.db"
    languages: list[str] | None = None
    ignore: list[str] = Field(default_factory=list)
    layer_mapping: list[LayerMapping] = Field(default_factory=list)
    plans_dir: str = "docs/ai/plans/"
    contracts_dir: str = "docs/ai/contracts/"
    learnings_file: str = "docs/ai/state/learnings_tracker.md"
    studies_dir: str = "docs/studies/"
    adrs_dir: str = "docs/ai/adrs/"
    spikes_dir: str = "docs/ai/spikes/"
    workflow_state_file: str = "docs/ai/state/workflow_state.md"
    embeddings: bool = False
    communities: bool = True


# ---------------------------------------------------------------------------
# Framework (top-level) configuration
# ---------------------------------------------------------------------------


class FrameworkMeta(BaseModel):
    version: str = "1.0"
    project_name: str = "My Project"
    architecture_layers: int = 6


# ---------------------------------------------------------------------------
# Root configuration
# ---------------------------------------------------------------------------

VALID_PROFILES = ("interactive", "semi_autonomous")
VALID_RIGOR_LEVELS = ("minimal", "standard", "strict")


class ScaffoldConfig(BaseModel):
    """Root configuration loaded from scaffold.yaml."""

    framework: FrameworkMeta = Field(default_factory=FrameworkMeta)
    profile: str = "interactive"
    rigor: str = "standard"
    gates: GatesConfig = Field(default_factory=GatesConfig)
    approval_required: ApprovalConfig = Field(default_factory=ApprovalConfig)
    standards: StandardsConfig = Field(default_factory=StandardsConfig)
    domains: list[str] = Field(default_factory=list)
    prohibitions: ProhibitionsConfig = Field(default_factory=ProhibitionsConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    semi_autonomous: SemiAutonomousConfig = Field(default_factory=SemiAutonomousConfig)
    task_runner: TaskRunnerConfig = Field(default_factory=TaskRunnerConfig)
    ci: CIConfig = Field(default_factory=CIConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    import_config: ImportConfig = Field(default_factory=ImportConfig, alias="import")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Rigor presets
# ---------------------------------------------------------------------------

RIGOR_PRESETS: dict[str, dict[str, Any]] = {
    "minimal": {
        "gates": {
            "draft_to_review": {"plan_lint": True, "architecture_layer_check": False},
            "review_to_ready": {
                "devils_advocate": False,
                "expansion_review": False,
                "spike_for_high_uncertainty": False,
                "interface_contracts": False,
                "security_review": False,
            },
            "ready_to_in_progress": {
                "review_checklist": False,
                "approval_gates": False,
                "interactive_gate": False,
            },
            "in_progress_to_complete": {
                "all_steps_checked": True,
                "validation_commands": True,
                "tests_pass": True,
                "retrospective": False,
                "domain_implementation_review": False,
            },
        },
    },
    "standard": {},
    "strict": {
        "gates": {
            "review_to_ready": {"security_review": True},
            "ready_to_in_progress": {"approval_gates": True},
            "in_progress_to_complete": {"domain_implementation_review": True},
        },
        "ci": {"plan_lint": True},
    },
}


def apply_rigor_preset(config: ScaffoldConfig) -> ScaffoldConfig:
    """Apply rigor-level preset overrides where the user has not explicitly set values."""
    preset = RIGOR_PRESETS.get(config.rigor, {})
    if not preset:
        return config

    raw = config.model_dump(by_alias=True)
    _deep_merge(raw, preset)
    return ScaffoldConfig.model_validate(raw)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge *override* into *base* (mutates base)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

CONFIG_FILENAME = "scaffold.yaml"


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from *start* looking for scaffold.yaml. Return path or None."""
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        candidate = parent / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None) -> ScaffoldConfig:
    """Load and validate scaffold.yaml, applying rigor presets."""
    if path is None:
        path = find_config()
    if path is None or not path.is_file():
        return apply_rigor_preset(ScaffoldConfig())

    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}

    config = ScaffoldConfig.model_validate(raw)
    return apply_rigor_preset(config)
