"""Unified project-root and governance-path resolution (Plan 221).

AgentScaffold historically resolved paths three different ways: the walk-up
``find_config()`` in :mod:`agentscaffold.config`, bare ``Path.cwd()``, and a
cluster of CLI commands that hardcoded ``docs/ai/*`` literals while ignoring
``GraphConfig``. This module gives the package a single project-root rule and a
single accessor (:class:`ResolvedPaths`) so every command resolves governance
paths the same way.

Backward compatibility: ``GraphConfig`` defaults already equal the literals the
CLI hardcoded, so routing a callsite through :class:`ResolvedPaths` is
behavior-preserving for any repo that has not customized ``graph.*``. The only
intended change is that customized ``graph.*`` paths finally take effect.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import cached_property
from pathlib import Path

from agentscaffold.active_root import default_start
from agentscaffold.config import (
    AssetLayoutConfig,
    GraphConfig,
    ProjectEntry,
    ScaffoldConfig,
    WorkspaceConfig,
    derive_project_name,
    effective_asset_layout,
    find_config,
    find_workspace_config,
    load_config,
    load_workspace_manifest,
)

logger = logging.getLogger(__name__)

#: Matches an unexpanded ``${VAR}`` placeholder left behind by expandvars when
#: the referenced environment variable is not set.
_UNRESOLVED_ENV_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")

#: Environment variable that overrides ``graph.db_path`` entirely (Plan 223).
#: Lets the same committed ``scaffold.yaml`` point the cache at a durable mounted
#: volume on a persistent box and a scratch path on an ephemeral devbox.
DB_PATH_ENV_VAR = "AGENTSCAFFOLD_DB_PATH"

#: Environment variable that overrides the embedding weights cache entirely
#: (Plan 249, Step A7c). Mirrors ``DB_PATH_ENV_VAR``: one machine-level escape
#: hatch for images and air-gapped builds that provision weights elsewhere.
MODEL_CACHE_ENV_VAR = "AGENTSCAFFOLD_MODEL_CACHE"

#: Environment variables that configure the MCP resolution anchor (Plan 234) when
#: the IDE launches the MCP server from a directory that is not the active
#: project (e.g. Cursor opening a parent monorepo folder). They mirror the
#: ``scaffold mcp --workspace`` / ``--project`` flags for user-level MCP installs.
WORKSPACE_ROOT_ENV_VAR = "AGENTSCAFFOLD_WORKSPACE_ROOT"
PROJECT_ENV_VAR = "AGENTSCAFFOLD_PROJECT"

#: Module-level MCP anchor override set by ``scaffold mcp`` before the server
#: starts (see :func:`configure_mcp_start`). Takes precedence over the
#: environment variables so an explicit flag always wins.
_MCP_WORKSPACE_OVERRIDE: str | None = None
_MCP_PROJECT_OVERRIDE: str | None = None


def configure_mcp_start(*, workspace: str | None = None, project: str | None = None) -> None:
    """Set the process-wide MCP resolution anchor from CLI flags (Plan 234).

    ``scaffold mcp --workspace <root> --project <name>`` calls this once before
    :func:`agentscaffold.mcp.server.run_mcp_server` so every no-argument tool
    resolves the configured project instead of the launch cwd. Passing ``None``
    for either value clears that field (falling back to env vars / cwd walk-up).
    """
    global _MCP_WORKSPACE_OVERRIDE, _MCP_PROJECT_OVERRIDE
    _MCP_WORKSPACE_OVERRIDE = workspace
    _MCP_PROJECT_OVERRIDE = project


def _resolve_project_in_workspace(workspace_root: Path, project: str) -> Path | None:
    """Resolve a registered project's root dir within *workspace_root*, or None."""
    try:
        ws_path = find_workspace_config(workspace_root)
        if ws_path is not None:
            workspace = load_workspace_manifest(ws_path)
        else:
            workspace = load_workspace(workspace_root)
        entry = workspace.find_by_name(project)
        if entry is None:
            return None
        project_path = Path(entry.path)
        if not project_path.is_absolute():
            project_path = workspace_root / project_path
        return project_path.resolve() if project_path.is_dir() else None
    except Exception:
        return None


def resolve_mcp_start(start: Path | None = None) -> Path:
    """Resolve the effective start anchor for MCP tool resolution (Plan 234).

    Precedence:
    1. An explicit *start* passed by a caller that already resolved flags.
    2. The module-level override set by ``scaffold mcp`` (:func:`configure_mcp_start`).
    3. The ``AGENTSCAFFOLD_PROJECT`` env var (resolved against the workspace root,
       which may come from ``AGENTSCAFFOLD_WORKSPACE_ROOT`` or a cwd walk-up).
    4. The ``AGENTSCAFFOLD_WORKSPACE_ROOT`` env var alone (workspace root; the
       active project is inferred later from cwd/single-project heuristics).
    5. Otherwise the current working directory (existing walk-up behavior).

    This is the single place where flags/env are allowed to beat ``Path.cwd()``;
    downstream heuristics (single-child workspace, single project) still apply in
    :func:`agentscaffold.mcp.server._effective_mcp_root`.
    """
    if start is not None:
        return start.resolve()

    workspace = _MCP_WORKSPACE_OVERRIDE or os.environ.get(WORKSPACE_ROOT_ENV_VAR) or None
    project = _MCP_PROJECT_OVERRIDE or os.environ.get(PROJECT_ENV_VAR) or None

    workspace_root: Path | None = None
    if workspace:
        workspace_root = Path(os.path.expanduser(workspace)).resolve()

    if project:
        base = workspace_root if workspace_root is not None else resolve_workspace_root()
        project_root = _resolve_project_in_workspace(base, project)
        if project_root is not None:
            return project_root

    if workspace_root is not None:
        return workspace_root

    return Path.cwd().resolve()


def _git_root(start: Path | None = None) -> Path | None:
    """Return the nearest ancestor containing a ``.git`` entry, or None."""
    current = (start or default_start()).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


_DEFAULT_DB_PATH = ".scaffold/graph.duckdb"

#: Filename of the graph database once it lives under the state directory. The
#: workspace id already keys the directory, so the file itself needs no suffix.
_STATE_DB_FILENAME = "graph.duckdb"


def resolve_workspace_state_id(start: Path | None = None) -> str | None:
    """Return the stable id keying this workspace's state, if it has one.

    Prefers the committed ``id:`` in ``workspace.yaml`` over the user-level
    registry so a workspace cannot key its state two ways depending on which
    source resolution happened to consult first.

    None means there is no stable id -- an unregistered lone repo -- and per the
    approved Step B4 scope such a repo keeps the in-tree default rather than
    having its state keyed by a path (rejected in ADR-025, since moving the root
    would orphan it).
    """
    try:
        workspace = load_workspace(start)
    except Exception:
        workspace = None

    if workspace is not None and workspace.id:
        from agentscaffold.workspace_ids import is_valid_workspace_id  # noqa: PLC0415

        if is_valid_workspace_id(workspace.id):
            return workspace.id
        logger.warning(
            "Ignoring malformed workspace id %r in workspace.yaml; falling back to the registry.",
            workspace.id,
        )

    try:
        from agentscaffold.workspace_registry import load_registry  # noqa: PLC0415

        entry = load_registry().find_workspace_by_root(resolve_workspace_root(start))
    except Exception:
        logger.debug("Registry unavailable while resolving workspace state id", exc_info=True)
        return None
    return entry.id if entry is not None else None


def _platform_db_path(start: Path | None = None) -> Path:
    """The default graph location when the user has not chosen one.

    Registered workspaces resolve under the platform state directory keyed by
    workspace id; everything else keeps the historical in-tree path.

    **An existing in-tree database always wins over an empty state directory.**
    Flipping a default is not a migration: without this, upgrading would point
    resolution at nothing, silently re-index from scratch, and leave the
    populated database orphaned in the tree -- the two-divergent-databases
    outcome Section 3 forbids, reached without any migration having run. The
    user moves it deliberately with ``scaffold workspace migrate-state``. This
    mirrors the warm-local fallback Step A7c established for model weights.
    """
    in_tree = resolve_workspace_root(start) / _DEFAULT_DB_PATH

    workspace_id = resolve_workspace_state_id(start)
    if workspace_id is None:
        return in_tree

    relocated = resolve_user_state_dir() / workspace_id / _STATE_DB_FILENAME
    if not relocated.exists() and in_tree.exists():
        return in_tree
    return relocated


def resolve_db_path(config: ScaffoldConfig | None, start: Path | None = None) -> Path:
    """Resolve the graph database path for durable/ephemeral environments.

    Resolution order (Plan 221 + 223, extended by Plan 249 Step B4):
    1. The ``AGENTSCAFFOLD_DB_PATH`` environment variable, if set, overrides
       everything (durable-volume vs scratch-path selection per machine).
    2. Otherwise an explicit ``config.graph.db_path``, so a config pinning
       ``.scaffold/graph.duckdb`` keeps its database exactly where it is.
    3. Otherwise the platform default -- see :func:`_platform_db_path`.

    A chosen value then has ``${VAR}``/``$VAR`` environment placeholders and a
    leading ``~`` expanded, so one committed ``scaffold.yaml`` works across
    machines. A relative result resolves under :func:`resolve_workspace_root`
    (the project root for a lone repo, or the shared workspace root when a
    ``workspace.yaml`` exists) so every project in a multi-project workspace
    reads and writes the same graph cache; an absolute result is honored
    unchanged.
    """
    override = os.environ.get(DB_PATH_ENV_VAR)
    if override:
        raw = override
    else:
        configured = (
            config.graph.db_path if config is not None and hasattr(config, "graph") else None
        )
        if not configured:
            return _platform_db_path(start)
        raw = configured

    raw = os.path.expandvars(os.path.expanduser(raw))
    unresolved = _UNRESOLVED_ENV_RE.search(raw)
    if unresolved:
        source = DB_PATH_ENV_VAR if override else "graph.db_path"
        raise ValueError(
            f"Cannot resolve db_path: environment variable '{unresolved.group()}' "
            f"referenced by {source} is not set. Set it (or use a literal path)."
        )
    p = Path(raw)
    if p.is_absolute():
        return p
    # Relative caches live at the workspace root so projects share one graph;
    # for a lone repo the workspace root collapses to the project root, so this
    # is byte-for-byte the previous single-project behavior.
    return resolve_workspace_root(start) / p


def resolve_user_cache_dir() -> Path:
    """Return the user-level cache root for AgentScaffold (Plan 249, Step A7c).

    ``$XDG_CACHE_HOME/agentscaffold`` when set, else ``~/.cache/agentscaffold``.
    Native Windows has no XDG convention; ``%LOCALAPPDATA%`` is the equivalent.

    Note for Step B4, which adds the *state* default: state and cache are
    deliberately different XDG roots. Graph state is per-workspace and worth
    keeping, so it belongs under ``XDG_STATE_HOME`` keyed by workspace id. Model
    weights are byte-identical everywhere and re-downloadable, so they belong
    under ``XDG_CACHE_HOME`` and are explicitly *not* keyed by workspace -- that
    key is what caused the duplication this function exists to remove. B4 should
    reuse this platform branch rather than write a second one.
    """
    override = os.environ.get("XDG_CACHE_HOME")
    if override:
        return Path(os.path.expanduser(override)).resolve() / "agentscaffold"
    if _running_on_windows():
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "agentscaffold" / "Cache"
    return (Path.home() / ".cache" / "agentscaffold").resolve()


def _running_on_windows() -> bool:
    """Whether this is a native Windows host.

    A named indirection rather than an inline ``os.name`` check so the Windows
    branch can be exercised from a POSIX host. Patching ``os.name`` itself is not
    an option: it changes which concrete class ``Path`` instantiates process-wide,
    and a Windows-flavoured Path cannot operate on this host's paths.
    """
    return os.name == "nt"


def resolve_user_state_dir() -> Path:
    """Return the user-level *state* root for AgentScaffold (Plan 249, Step B4).

    ``$XDG_STATE_HOME/agentscaffold`` when set, else ``~/.local/state/agentscaffold``.
    Native Windows has no XDG convention; ``%LOCALAPPDATA%`` is the equivalent,
    and the platform branch deliberately mirrors :func:`resolve_user_cache_dir`
    rather than reimplementing it differently.

    State and cache are separate roots on purpose. Graph state is per-workspace,
    expensive to rebuild, and worth keeping. Model weights are byte-identical
    everywhere and re-downloadable, so they are a cache and are explicitly not
    keyed by workspace.
    """
    override = os.environ.get("XDG_STATE_HOME")
    if override:
        return Path(os.path.expanduser(override)).resolve() / "agentscaffold"
    if _running_on_windows():
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            # Deliberately not resolved: %LOCALAPPDATA% is already absolute, so
            # resolving buys nothing and would call realpath on a path this host
            # may not own.
            return Path(local_app_data) / "agentscaffold" / "State"
    return (Path.home() / ".local" / "state" / "agentscaffold").resolve()


def _ensure_private_dir(path: Path) -> Path:
    """Create *path* readable and writable only by its owner.

    Threat model Vector 4: the state directory aggregates indexed content from
    every registered workspace into one place, which is a concentration the
    per-repo layout never had. It is created 0o700 rather than inheriting
    whatever the ambient umask happens to allow, and an existing directory is
    tightened rather than trusted, since it may predate this rule.
    """
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.chmod(0o700)
        except OSError:  # pragma: no cover - unusual filesystems
            logger.warning("Could not restrict permissions on %s", path)
    return path


def ensure_user_state_dir() -> Path:
    """Return the user-level state root, creating it user-only if absent."""
    return _ensure_private_dir(resolve_user_state_dir())


def ensure_workspace_state_dir(workspace_id: str) -> Path:
    """Return this workspace's state directory, creating it user-only if absent."""
    ensure_user_state_dir()
    return _ensure_private_dir(resolve_user_state_dir() / workspace_id)


#: Written inside each workspace state directory to record which root it serves.
STATE_PROVENANCE_FILENAME = "workspace.json"


def write_state_provenance(state_dir: Path, workspace_id: str, root: Path) -> None:
    """Record which workspace root *state_dir* was created for.

    Without this, ``scaffold gc`` has only a directory name to reason from, and
    a directory name cannot distinguish a workspace that was deleted from one
    that was simply never registered -- the manifest is the source of truth, so
    an unregistered workspace's state is live and must not be reclaimed. The
    marker turns that guess into a decidable question.

    Best-effort by design: failing to write a hint must never fail a graph open.
    """
    try:
        (state_dir / STATE_PROVENANCE_FILENAME).write_text(
            json.dumps({"id": workspace_id, "root": str(root)}, indent=2) + "\n"
        )
    except OSError:  # pragma: no cover - unwritable state dir surfaces elsewhere
        logger.debug("Could not record state provenance in %s", state_dir, exc_info=True)


def read_state_provenance(state_dir: Path) -> dict[str, str] | None:
    """Return the provenance record for *state_dir*, or None if it has none."""
    marker = state_dir / STATE_PROVENANCE_FILENAME
    if not marker.is_file():
        return None
    try:
        loaded = json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _record_provenance_if_certain(parent: Path, state_root: Path) -> None:
    """Record provenance for *parent* only when it is unambiguously this root's.

    ``ensure_parent_dir`` is called from the graph-open path, which knows the
    directory but not the workspace behind it. Rather than assume the ambient
    workspace is the one being opened -- it need not be, since the MCP server
    serves several -- the ambient id is resolved and the record is written only
    if it matches the directory being created. A missed record is handled
    conservatively by gc; a wrong one would not be.
    """
    if parent.parent != state_root:
        return
    try:
        workspace_id = resolve_workspace_state_id()
        if workspace_id != parent.name:
            return
        write_state_provenance(parent, workspace_id, resolve_workspace_root())
    except Exception:  # pragma: no cover - provenance is never load-bearing
        logger.debug("Could not determine provenance for %s", parent, exc_info=True)


def ensure_parent_dir(path: Path) -> Path:
    """Create the parent directory of *path*, user-only when it is state we own.

    Every site that creates a graph database or its sidecars routes through this
    rather than calling ``mkdir`` itself. Directly calling ``mkdir`` is how the
    0o700 requirement gets satisfied in a helper and quietly missed on the path
    that actually runs: the permission is a property of the directory, so it has
    to be applied where the directory is made.

    Outside the state root the ambient umask still applies, because those
    directories live in the user's own tree and are not ours to tighten.
    """
    parent = path.parent
    state_root = resolve_user_state_dir()
    try:
        inside_state = parent == state_root or state_root in parent.parents
    except (OSError, ValueError):  # pragma: no cover - unresolvable path flavour
        inside_state = False

    if not inside_state:
        parent.mkdir(parents=True, exist_ok=True)
        return parent

    _ensure_private_dir(state_root)
    relative = parent.relative_to(state_root)
    current = state_root
    for part in relative.parts:
        current = current / part
        _ensure_private_dir(current)
    _record_provenance_if_certain(parent, state_root)
    return parent


def _has_cached_weights(path: Path) -> bool:
    """True when *path* looks like a populated Hugging Face cache.

    Existence alone is not enough: a failed warm leaves an empty directory
    behind, and treating that as warm would pin the project to a cache that has
    nothing in it. Hugging Face names each entry ``models--<org>--<name>``.
    """
    try:
        return any(child.name.startswith("models--") for child in path.iterdir())
    except OSError:
        return False


def resolve_model_cache_dir(
    config: ScaffoldConfig | None, start: Path | None = None
) -> Path | None:
    """Resolve where embedding model weights are cached (Plan 249, Step A7c).

    Returns ``None`` to mean "use the default Hugging Face cache", preserving the
    existing meaning of an empty ``search.cache_dir``.

    Resolution order:

    1. ``AGENTSCAFFOLD_MODEL_CACHE``, if set, overrides everything.
    2. An empty ``search.cache_dir`` yields ``None`` (Hugging Face default).
    3. An absolute ``search.cache_dir`` is honored unchanged.
    4. A relative ``search.cache_dir`` the user actually wrote resolves against
       the project root -- pinning weights inside a repo is legitimate for an
       air-gapped build, so a deliberate choice is never redirected.
    5. The shipped default resolves to the shared user-level cache.

    Case 5 is the change. The default was project-relative, so N projects held N
    copies of byte-identical weights (four were measured at 87 MB each). Note
    that it is the *default* that redirects, not relative paths in general: the
    distinction is between a value nobody chose and one somebody wrote.

    One exception keeps upgrades cheap. If the shared cache is cold but this
    project already has a warmed local one, the local one is used, so upgrading
    never forces an 87 MB re-download. That is a migration aid, not a
    preference -- once the shared cache is warm it wins, and ``scaffold gc``
    reclaims the leftovers.
    """
    override = os.environ.get(MODEL_CACHE_ENV_VAR)
    if override:
        return Path(os.path.expanduser(os.path.expandvars(override))).resolve()

    raw = config.search.cache_dir if config is not None and hasattr(config, "search") else None
    if not raw:
        return None

    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if path.is_absolute():
        return path

    from agentscaffold.config import SearchConfig

    if raw != SearchConfig.model_fields["cache_dir"].default:
        return resolve_root(start) / path

    shared = resolve_user_cache_dir() / "models"
    if _has_cached_weights(shared):
        return shared
    project_local = resolve_root(start) / path
    if _has_cached_weights(project_local):
        return project_local
    return shared


def resolve_root(start: Path | None = None) -> Path:
    """Resolve the project root with one deterministic rule.

    Precedence:
    1. The directory containing the nearest ``scaffold.yaml`` (walk-up).
    2. Otherwise the nearest ancestor containing ``.git``.
    3. Otherwise ``start`` (or the current working directory).

    The ``.git`` and cwd fallbacks preserve today's behavior for repos without a
    ``scaffold.yaml``: code that previously assumed ``cwd == project root`` keeps
    working when invoked from the repo root.
    """
    config_path = find_config(start)
    if config_path is not None:
        return config_path.parent.resolve()
    git_root = _git_root(start)
    if git_root is not None:
        return git_root
    return (start or default_start()).resolve()


def resolve_workspace_root(start: Path | None = None) -> Path:
    """Resolve the outer workspace root (Plan 225).

    Precedence:
    1. The directory containing the nearest ``workspace.yaml`` (walk-up).
    2. Otherwise the project root (:func:`resolve_root`).

    For a lone repo with no workspace manifest, the workspace root collapses to
    the project root, so single-project behavior is unchanged.
    """
    ws_path = find_workspace_config(start)
    if ws_path is not None:
        return ws_path.parent.resolve()
    return resolve_root(start)


def load_workspace(start: Path | None = None) -> WorkspaceConfig:
    """Load the workspace manifest, or synthesize a single-project workspace.

    When no ``workspace.yaml`` exists (the common, single-project case) a
    workspace with exactly one project is synthesized: its name is derived from
    the project-root basename and its path is the project root. This keeps every
    downstream consumer (scoping, indexing) able to ask "what projects exist?"
    uniformly, while ``is_multi_project`` stays False so nothing is prefixed.
    """
    ws_path = find_workspace_config(start)
    if ws_path is not None:
        return load_workspace_manifest(ws_path)
    root = resolve_root(start)
    name = derive_project_name(root)
    return WorkspaceConfig(projects=[ProjectEntry(name=name, path=str(root))])


class ResolvedPaths:
    """Governance paths derived from a :class:`GraphConfig`, joined to a root.

    Every path is the project root joined with the corresponding ``GraphConfig``
    field. Relative config values resolve under the root; absolute config values
    are honored as-is (``Path`` join semantics).
    """

    def __init__(
        self,
        config: ScaffoldConfig,
        root: Path,
        workspace: WorkspaceConfig | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        self._config = config
        self._graph = config.graph
        self.root = root.resolve()
        self._workspace = workspace
        self._workspace_root = workspace_root.resolve() if workspace_root is not None else None
        self._layout: AssetLayoutConfig = (
            effective_asset_layout(workspace) if workspace is not None else AssetLayoutConfig()
        )
        # Shared assets only relocate to the workspace root when the policy opts
        # in AND the workspace root is a real, distinct anchor. For a lone repo
        # the workspace root collapses to the project root, so nothing moves.
        self._shared_active = (
            self._layout.layout == "shared_workspace" and self._workspace_root is not None
        )

    @classmethod
    def discover(cls, start: Path | None = None) -> ResolvedPaths:
        """Build a :class:`ResolvedPaths` by loading config + resolving the root."""
        root = resolve_root(start)
        config_path = find_config(start)
        config = load_config(config_path)
        workspace = load_workspace(start)
        workspace_root = resolve_workspace_root(start)
        return cls(config, root, workspace=workspace, workspace_root=workspace_root)

    def _join(self, value: str) -> Path:
        return self.root / value

    def _shared_asset(self, graph_field: str, shared_value: str) -> Path:
        """Resolve a reusable process asset, honoring the shared/project split.

        In ``shared_workspace`` mode a reusable process asset resolves at the
        workspace root -- UNLESS the project has customized the corresponding
        ``graph.*`` field away from its default, which remains an explicit
        project-local escape hatch. Otherwise (``project_local`` or a lone repo)
        it resolves under the project root exactly as before.
        """
        graph_value: str = getattr(self._graph, graph_field)
        default = GraphConfig.model_fields[graph_field].default
        if self._shared_active and self._workspace_root is not None and graph_value == default:
            return self._workspace_root / shared_value
        return self.root / graph_value

    # -- Directories --------------------------------------------------------
    @cached_property
    def plans_dir(self) -> Path:
        return self._join(self._graph.plans_dir)

    @cached_property
    def contracts_dir(self) -> Path:
        return self._join(self._graph.contracts_dir)

    @cached_property
    def studies_dir(self) -> Path:
        return self._join(self._graph.studies_dir)

    @cached_property
    def adrs_dir(self) -> Path:
        return self._join(self._graph.adrs_dir)

    @cached_property
    def spikes_dir(self) -> Path:
        return self._join(self._graph.spikes_dir)

    @cached_property
    def standards_dir(self) -> Path:
        return self._shared_asset("standards_dir", self._layout.shared.standards_dir)

    @cached_property
    def prompts_dir(self) -> Path:
        return self._shared_asset("prompts_dir", self._layout.shared.prompts_dir)

    @cached_property
    def templates_dir(self) -> Path:
        return self._shared_asset("templates_dir", self._layout.shared.templates_dir)

    @cached_property
    def security_dir(self) -> Path:
        return self._shared_asset("security_dir", self._layout.shared.security_dir)

    # -- Shared process files (Plan 234) ------------------------------------
    @cached_property
    def collaboration_protocol_file(self) -> Path:
        if self._shared_active and self._workspace_root is not None:
            return self._workspace_root / self._layout.shared.collaboration_protocol_file
        return self.root / "docs/ai/collaboration_protocol.md"

    @cached_property
    def commands_file(self) -> Path:
        if self._shared_active and self._workspace_root is not None:
            return self._workspace_root / self._layout.shared.commands_file
        return self.root / "docs/ai/commands.md"

    # -- Files --------------------------------------------------------------
    @cached_property
    def learnings_file(self) -> Path:
        return self._join(self._graph.learnings_file)

    @cached_property
    def workflow_state_file(self) -> Path:
        return self._join(self._graph.workflow_state_file)

    @cached_property
    def backlog_file(self) -> Path:
        return self._join(self._graph.backlog_file)

    @cached_property
    def backlog_archive_file(self) -> Path:
        return self._join(self._graph.backlog_archive_file)

    @cached_property
    def plan_completion_log_file(self) -> Path:
        return self._join(self._graph.plan_completion_log_file)

    @cached_property
    def db_path(self) -> Path:
        """The *configured* graph database path, joined to this root.

        A view of the config value, not the live location: since Step B4 the
        authoritative resolver is :func:`resolve_db_path`, which also consults
        the environment override and the platform state directory. An unset
        ``db_path`` reads as the historical in-tree path here.
        """
        return self._join(self._graph.db_path or _DEFAULT_DB_PATH)

    # -- Collaboration ergonomics (Plan 226) --------------------------------
    @cached_property
    def workflow_fragments_dir(self) -> Path:
        return self._join(self._config.collab.workflow_fragments_dir)

    @cached_property
    def backlog_items_dir(self) -> Path:
        return self._join(self._config.collab.backlog_items_dir)

    @cached_property
    def claims_dir(self) -> Path:
        return self._join(self._config.collab.claims_dir)
