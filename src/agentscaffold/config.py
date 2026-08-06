"""Configuration schema and loading for scaffold.yaml."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from agentscaffold.active_root import default_start

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
# Reviewer / expert-agent configuration
# ---------------------------------------------------------------------------


class ReviewerConfig(BaseModel):
    """A single expert reviewer definition for agent generation."""

    name: str
    description: str = ""
    cursor_description: str | None = None
    prompt_file: str | None = None
    file_patterns: list[str] = Field(default_factory=list)
    model: str | None = None
    tools: list[str] = Field(default_factory=list)

    def effective_cursor_description(self) -> str:
        """Return cursor_description or a generated fallback."""
        if self.cursor_description:
            return self.cursor_description
        return f"Load when reviewing plans tagged with {self.name} domain."


class ReviewsConfig(BaseModel):
    expert_reviewers: list[ReviewerConfig] = Field(default_factory=list)


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
# Collaboration ergonomics configuration (Plan 226)
# ---------------------------------------------------------------------------


class CollabConfig(BaseModel):
    """Opt-in sharding of high-contention governance files + plan ownership.

    When ``sharded`` is false (default), ``workflow_state.md`` / ``backlog.md``
    behave exactly as today. When true, those files are stored as per-entry
    fragments and assembled by ``scaffold state render``, so concurrent writers
    touch different files and merge conflicts are rare.
    """

    sharded: bool = False
    workflow_fragments_dir: str = "docs/ai/state/workflow_state/"
    backlog_items_dir: str = "docs/ai/state/backlog_items/"
    claims_dir: str = "docs/ai/state/claims/"


# ---------------------------------------------------------------------------
# Workspace configuration (Plan 225 - namespaced multi-project workspace)
# ---------------------------------------------------------------------------

#: Filename of the optional outer workspace manifest. Its presence is what
#: switches a tree from single-project (today's behavior) to a multi-project
#: workspace; a lone repo never has one and is byte-for-byte unchanged.
WORKSPACE_FILENAME = "workspace.yaml"

#: Delimiter that separates a project prefix from a raw node ID
#: (``{project}::{raw_id}``). Raw IDs already contain ``::`` (e.g. ``plan::224``),
#: so qualify/unqualify split on the FIRST delimiter only and project names are
#: validated to exclude it (and whitespace) -- see :func:`validate_project_name`.
PROJECT_DELIMITER = "::"


class ProjectEntry(BaseModel):
    """A single project registered in a workspace manifest.

    ``path`` is the project root (the directory containing its ``scaffold.yaml``);
    relative values resolve against the workspace root. ``name`` is the stable,
    user-facing namespace used to qualify node IDs and scope reads.
    """

    name: str
    path: str


#: The two supported asset-layout policies (Plan 234). ``project_local`` is the
#: backward-compatible default: every project keeps a full ``docs/ai`` tree.
#: ``shared_workspace`` promotes reusable process assets (prompts, standards,
#: templates, protocol, commands, shared security templates) to the workspace
#: root while project system-of-record artifacts stay project-local.
AssetLayoutMode = Literal["project_local", "shared_workspace"]


class SharedAssetPaths(BaseModel):
    """Workspace-root-relative locations of reusable *process* assets (Plan 234).

    In ``shared_workspace`` mode these directories/files resolve against the
    workspace root, so every registered project reads one committed copy of the
    reusable process material instead of duplicating it. Defaults equal the
    per-project ``GraphConfig`` literals, so promotion is byte-for-byte the same
    relative layout, just anchored at the workspace root.
    """

    prompts_dir: str = "docs/ai/prompts/"
    standards_dir: str = "docs/ai/standards/"
    templates_dir: str = "docs/ai/templates/"
    security_dir: str = "docs/security/"
    collaboration_protocol_file: str = "docs/ai/collaboration_protocol.md"
    commands_file: str = "docs/ai/commands.md"
    routing_guidance_file: str = "docs/ai/agent_routing.md"


class ProjectAssetPaths(BaseModel):
    """Project-root-relative locations of system-of-record artifacts (Plan 234).

    These are never promoted to the workspace root: plans, ADRs, contracts,
    spikes, state, backlog, architecture, vision, and history are per-project
    identity and are always resolved against the active project root. Defaults
    equal the ``GraphConfig`` literals so a ``shared_workspace`` project keeps
    today's project-local paths for its own SoR.
    """

    plans_dir: str = "docs/ai/plans/"
    adrs_dir: str = "docs/ai/adrs/"
    contracts_dir: str = "docs/ai/contracts/"
    spikes_dir: str = "docs/ai/spikes/"
    state_dir: str = "docs/ai/state/"
    studies_dir: str = "docs/studies/"
    runbook_dir: str = "docs/runbook/"
    backlog_file: str = "docs/ai/backlog.md"
    backlog_archive_file: str = "docs/ai/backlog_archive.md"
    product_vision_file: str = "docs/ai/product_vision.md"
    strategy_roadmap_file: str = "docs/ai/strategy_roadmap.md"
    system_architecture_file: str = "docs/ai/system_architecture.md"
    architectural_design_changelog_file: str = "docs/ai/architectural_design_changelog.md"


class AssetLayoutConfig(BaseModel):
    """Workspace asset-layout policy (Plan 234).

    ``layout`` selects whether reusable process assets are shared at the
    workspace root (``shared_workspace``) or kept project-local
    (``project_local``, the backward-compatible default). ``shared`` and
    ``project`` carry the relative path blocks used to resolve each class of
    asset; both default to the same literals as ``GraphConfig`` so an
    uncustomized workspace behaves exactly as before.
    """

    layout: AssetLayoutMode = "project_local"
    shared: SharedAssetPaths = Field(default_factory=SharedAssetPaths)
    project: ProjectAssetPaths = Field(default_factory=ProjectAssetPaths)

    @field_validator("layout", mode="before")
    @classmethod
    def _validate_layout(cls, value: Any) -> str:
        if value is None:
            return "project_local"
        policy = str(value)
        if policy not in ("project_local", "shared_workspace"):
            raise ValueError(
                "asset_layout.layout must be one of: project_local, shared_workspace"
            )
        return policy


class WorkspaceConfig(BaseModel):
    """Outer workspace manifest listing the projects sharing one graph cache.

    A single-project tree has no manifest; one is synthesized with exactly one
    project (see :func:`agentscaffold.paths.load_workspace`). ``is_multi_project``
    is the single switch that gates ID-prefixing and read scoping everywhere.
    ``asset_layout`` is optional (Plan 234): ``None`` behaves as
    ``project_local`` for full backward compatibility.
    """

    #: Stable opaque workspace id (Plan 249). Written on first manifest write and
    #: never derived from the path, so moving or renaming a workspace root does
    #: not orphan the state keyed by it. None for a manifest predating Plan 249.
    id: str | None = None
    projects: list[ProjectEntry] = Field(default_factory=list)
    asset_layout: AssetLayoutConfig | None = None

    @property
    def is_multi_project(self) -> bool:
        return len(self.projects) > 1

    @property
    def is_shared_workspace(self) -> bool:
        """True when this workspace opts into the shared asset layout."""
        return self.asset_layout is not None and self.asset_layout.layout == "shared_workspace"

    def project_names(self) -> list[str]:
        return [p.name for p in self.projects]

    def find_by_name(self, name: str) -> ProjectEntry | None:
        for p in self.projects:
            if p.name == name:
                return p
        return None


#: Project names are restricted to this safe charset so they can be inlined
#: into SQL/GRAPH_TABLE predicates without escaping and stay unambiguous as an
#: ID prefix. Excludes whitespace, quotes, and the ``::`` delimiter by
#: construction.
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_project_name(name: str) -> str:
    """Validate a project name and return it unchanged, or raise ConfigError.

    Names must be non-empty and match ``[A-Za-z0-9._-]+`` -- which excludes
    whitespace, quotes, and the ``::`` delimiter, so ``{project}::{raw_id}``
    stays unambiguously splittable on the first delimiter and project names are
    safe to inline into SQL predicates. (Uniqueness is checked at the workspace
    level by :func:`validate_workspace`.)
    """
    if not name or not name.strip():
        raise ConfigError("Project name must be a non-empty string.")
    if not _PROJECT_NAME_RE.match(name):
        raise ConfigError(
            f"Project name {name!r} is invalid; use only letters, digits, '.', '_', '-' "
            "(no whitespace, quotes, or '::')."
        )
    return name


def validate_workspace(workspace: WorkspaceConfig) -> WorkspaceConfig:
    """Validate every project name and reject duplicate (colliding) names."""
    seen: set[str] = set()
    for entry in workspace.projects:
        validate_project_name(entry.name)
        if entry.name in seen:
            raise ConfigError(
                f"Duplicate project name {entry.name!r} in workspace; names must be unique "
                "(explicit --name resolves basename collisions)."
            )
        seen.add(entry.name)
    return workspace


def derive_project_name(root: Path, explicit: str | None = None) -> str:
    """Derive a stable, delimiter-safe project name for a project root.

    Prefers an explicit name; otherwise the root directory basename (stable and
    filesystem-safe). The result is validated so a single-project default and an
    onboarded project share the same naming rules.
    """
    if explicit is not None:
        return validate_project_name(explicit)
    name = root.resolve().name or "project"
    # Basenames can contain spaces; normalize to keep the name delimiter-safe.
    name = "-".join(name.split())
    return validate_project_name(name)


def find_workspace_config(start: Path | None = None) -> Path | None:
    """Walk up from *start* looking for workspace.yaml. Return path or None."""
    current = (start or default_start()).resolve()
    for parent in [current, *current.parents]:
        candidate = parent / WORKSPACE_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_workspace_manifest(path: Path) -> WorkspaceConfig:
    """Load and validate a workspace.yaml manifest from *path*."""
    raw = _read_raw(path)
    workspace = WorkspaceConfig.model_validate(raw or {})
    return validate_workspace(workspace)


def effective_asset_layout(workspace: WorkspaceConfig) -> AssetLayoutConfig:
    """Return the workspace's asset-layout policy, defaulting to project_local.

    A workspace with no ``asset_layout`` block (the common, backward-compatible
    case) resolves to ``project_local`` defaults, so every caller can read a
    concrete :class:`AssetLayoutConfig` without a None check.
    """
    if workspace.asset_layout is not None:
        return workspace.asset_layout
    return AssetLayoutConfig()


# ---------------------------------------------------------------------------
# Graph (knowledge graph) configuration
# ---------------------------------------------------------------------------


class LayerMapping(BaseModel):
    pattern: str
    layer: int


class GraphConfig(BaseModel):
    # None means "use the platform default" (Plan 249 Step B4): the state
    # directory for a registered workspace, or the historical in-tree path when
    # there is no workspace id to key state by. A string here means the user
    # chose a location and it is honored unchanged.
    #
    # The meaning lives in the value rather than in Pydantic's
    # ``model_fields_set`` because ``apply_rigor_preset`` round-trips the config
    # through ``model_dump`` and re-validation, which marks every field as
    # explicitly set under the ``minimal`` and ``strict`` presets.
    db_path: str | None = None
    backend: str = "duckpgq"
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
    # Additive governance path fields (Plan 221). Defaults equal the literals
    # that the CLI / domain-pack installer previously hardcoded, so an
    # uncustomized repo is unaffected.
    backlog_file: str = "docs/ai/backlog.md"
    backlog_archive_file: str = "docs/ai/backlog_archive.md"
    standards_dir: str = "docs/ai/standards/"
    prompts_dir: str = "docs/ai/prompts/"
    templates_dir: str = "docs/ai/templates/"
    plan_completion_log_file: str = "docs/ai/state/plan_completion_log.md"
    security_dir: str = "docs/security/"
    # Git-committed governance system of record (Plan 222). Findings, sessions,
    # and backlog items are serialized here so the graph can be rebuilt from
    # git. Relative values resolve against the project root.
    governance_artifact: str = "docs/ai/state/governance.json"
    # Human-owned architecture baseline (Plan 237). Parsed into ArchitectureLayer
    # nodes + BELONGS_TO_LAYER edges so file->layer analyses activate.
    architecture_doc: str = "docs/ai/system_architecture.md"
    # Optional override for Plan 245 overlap-noise denylist. ``None`` keeps the
    # built-in defaults (contracts README, workflow_state, backlog, architecture
    # changelog). An explicit list replaces defaults (empty list disables filtering).
    overlap_noise_paths: list[str] | None = None
    embeddings: bool = False
    communities: bool = True
    incremental_community_refresh: str = "structure"
    incremental_community_threshold: int = 25
    incremental_min_interval_seconds: int = 0
    embedding_min_interval_seconds: int = 0
    async_embeddings: str = "off"

    @field_validator("async_embeddings", mode="before")
    @classmethod
    def normalize_async_embeddings(cls, value: Any) -> str:
        """Normalize YAML booleans from unquoted on/off-like policy values."""
        if isinstance(value, bool):
            return "idle" if value else "off"
        if value is None:
            return "off"
        policy = str(value).lower()
        if policy not in {"off", "idle", "interval", "commit"}:
            raise ValueError("async_embeddings must be one of: off, idle, interval, commit")
        return policy


# ---------------------------------------------------------------------------
# Freshness (MCP async refresh) configuration
# ---------------------------------------------------------------------------


class FreshnessConfig(BaseModel):
    async_enabled: bool = True
    debounce_seconds: int = 120
    gate_strict: bool = False
    background_queue_enabled: bool = True


# ---------------------------------------------------------------------------
# Semantic search / embedding configuration (Plan 227)
# ---------------------------------------------------------------------------


class SearchConfig(BaseModel):
    """Semantic-search / embedding model settings (Plan 227, Tier 2a).

    The embedding model is configurable and its weights cache is pinned to a
    workspace-local directory by default, so once provisioned (``scaffold graph
    warm``) the model loads deterministically and offline -- no surprise download
    during ``scaffold index`` / ``scaffold graph search``.
    """

    # protected_namespaces=() avoids pydantic's "model_" namespace warning while
    # keeping the field name explicit.
    model_config = {"protected_namespaces": ()}

    embedding_model: str = "all-MiniLM-L6-v2"
    # Directory where embedding model weights are cached. A relative path resolves
    # against the project root; keeping it inside the workspace makes provisioning
    # deterministic and offline-capable after a single warm. Set to empty/null to
    # use the default Hugging Face cache (~/.cache/huggingface).
    cache_dir: str = ".scaffold/models"
    rerank: bool = False
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


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
    # Config inheritance (Plan 224): inherit shared policy from a base config.
    # A filesystem path (absolute, or relative to this file's directory) or the
    # literal "home" (the org/user home config: $AGENTSCAFFOLD_HOME or
    # ~/.agentscaffold/scaffold.yaml). Values in this file override the base.
    extends: str | None = None
    profile: str = "interactive"
    rigor: str = "standard"
    gates: GatesConfig = Field(default_factory=GatesConfig)
    approval_required: ApprovalConfig = Field(default_factory=ApprovalConfig)
    standards: StandardsConfig = Field(default_factory=StandardsConfig)
    domains: list[str] = Field(default_factory=list)
    reviews: ReviewsConfig = Field(default_factory=ReviewsConfig)
    prohibitions: ProhibitionsConfig = Field(default_factory=ProhibitionsConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    semi_autonomous: SemiAutonomousConfig = Field(default_factory=SemiAutonomousConfig)
    task_runner: TaskRunnerConfig = Field(default_factory=TaskRunnerConfig)
    ci: CIConfig = Field(default_factory=CIConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    import_config: ImportConfig = Field(default_factory=ImportConfig, alias="import")
    collab: CollabConfig = Field(default_factory=CollabConfig)
    enforcement: EnforcementConfig = Field(default_factory=lambda: _get_enforcement_default())

    model_config = {"populate_by_name": True}


def _get_enforcement_default() -> EnforcementConfig:
    from agentscaffold.hooks.config import EnforcementConfig  # noqa: PLC0415

    return EnforcementConfig()


# Forward ref for type checkers
from agentscaffold.hooks.config import EnforcementConfig  # noqa: E402, PLC0415

ScaffoldConfig.model_rebuild()


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


class ConfigError(Exception):
    """Raised when scaffold.yaml inheritance (``extends``) cannot be resolved."""


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from *start* looking for scaffold.yaml. Return path or None."""
    current = (start or default_start()).resolve()
    for parent in [current, *current.parents]:
        candidate = parent / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _read_raw(path: Path) -> dict[str, Any]:
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def _resolve_extends_target(value: str, project_dir: Path) -> Path | None:
    """Resolve an ``extends`` value to a base config path (Plan 224).

    ``home`` resolves to the org/user home config, or None when no home config
    exists (a deliberate no-op so a repo with ``extends: home`` still works on a
    machine without shared config). Any other value is a filesystem path:
    absolute as-is, otherwise relative to the directory of the config that
    declared ``extends``. A bare directory resolves to ``<dir>/scaffold.yaml``.
    """
    from agentscaffold.config_home import HOME_SENTINEL, resolve_home_config  # noqa: PLC0415

    if value == HOME_SENTINEL:
        return resolve_home_config()

    candidate = Path(os.path.expanduser(value))
    if not candidate.is_absolute():
        candidate = (project_dir / candidate).resolve()
    if candidate.is_dir():
        candidate = candidate / CONFIG_FILENAME
    return candidate


def _load_raw_with_extends(path: Path, _seen: list[Path] | None = None) -> dict[str, Any]:
    """Load a raw config dict, recursively merging any ``extends`` base under it.

    Precedence: a child's values override its base's (deep-merged; lists are
    replaced wholesale, not concatenated). Cycles raise :class:`ConfigError`; an
    explicit (non-``home``) base that does not exist raises :class:`ConfigError`;
    an absent ``home`` base is a no-op.
    """
    if _seen is None:
        _seen = []
    resolved = path.resolve()
    if resolved in _seen:
        chain = " -> ".join(str(p) for p in [*_seen, resolved])
        raise ConfigError(f"Circular 'extends' detected: {chain}")
    _seen = [*_seen, resolved]

    raw = _read_raw(path)
    extends = raw.get("extends")
    if not extends:
        return raw
    if not isinstance(extends, str):
        raise ConfigError(f"'extends' in {path} must be a string, got {type(extends).__name__}")

    base_path = _resolve_extends_target(extends, path.parent)
    if base_path is None:
        # extends: home, but no home config present -> behave as if no extends.
        return raw
    if not base_path.is_file():
        raise ConfigError(f"'extends: {extends}' referenced by {path} was not found at {base_path}")

    merged = _load_raw_with_extends(base_path, _seen)
    _deep_merge(merged, raw)  # child (raw) overrides base (merged)
    return merged


def resolve_config_chain(path: Path) -> list[Path]:
    """Return the ordered config files contributing to *path*, base-first (Plan 224).

    Used by ``scaffold config show`` to display inheritance provenance. Skips
    missing/cyclic bases rather than raising (display must not crash).
    """
    chain: list[Path] = []

    def _walk(p: Path, seen: list[Path]) -> None:
        resolved = p.resolve()
        if resolved in seen:
            return
        seen = [*seen, resolved]
        raw = _read_raw(p)
        extends = raw.get("extends")
        if isinstance(extends, str) and extends:
            base = _resolve_extends_target(extends, p.parent)
            if base is not None and base.is_file():
                _walk(base, seen)
        chain.append(resolved)

    _walk(path, [])
    return chain


def load_config(path: Path | None = None) -> ScaffoldConfig:
    """Load and validate scaffold.yaml, applying inheritance then rigor presets.

    Resolution precedence (low -> high): built-in defaults, then any ``extends``
    base chain (recursively), then this file's values. Environment overrides
    (e.g. ``AGENTSCAFFOLD_DB_PATH``, Plan 223) apply later at path-resolution
    time, so they sit above all of these.
    """
    if path is None:
        path = find_config()
    if path is None or not path.is_file():
        return apply_rigor_preset(ScaffoldConfig())

    raw = _load_raw_with_extends(path)
    config = ScaffoldConfig.model_validate(raw)
    return apply_rigor_preset(config)
