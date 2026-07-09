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

import os
import re
from functools import cached_property
from pathlib import Path

from agentscaffold.config import (
    ProjectEntry,
    ScaffoldConfig,
    WorkspaceConfig,
    derive_project_name,
    find_config,
    find_workspace_config,
    load_config,
    load_workspace_manifest,
)

#: Matches an unexpanded ``${VAR}`` placeholder left behind by expandvars when
#: the referenced environment variable is not set.
_UNRESOLVED_ENV_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")

#: Environment variable that overrides ``graph.db_path`` entirely (Plan 223).
#: Lets the same committed ``scaffold.yaml`` point the cache at a durable mounted
#: volume on a persistent box and a scratch path on an ephemeral devbox.
DB_PATH_ENV_VAR = "AGENTSCAFFOLD_DB_PATH"


def _git_root(start: Path | None = None) -> Path | None:
    """Return the nearest ancestor containing a ``.git`` entry, or None."""
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


_DEFAULT_DB_PATH = ".scaffold/graph.duckdb"


def resolve_db_path(config: ScaffoldConfig | None, start: Path | None = None) -> Path:
    """Resolve the graph database path for durable/ephemeral environments.

    Resolution order (Plan 221 + 223):
    1. The ``AGENTSCAFFOLD_DB_PATH`` environment variable, if set, overrides
       everything (durable-volume vs scratch-path selection per machine).
    2. Otherwise ``config.graph.db_path`` (or the default).

    The chosen value then has ``${VAR}``/``$VAR`` environment placeholders and a
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
        raw = _DEFAULT_DB_PATH
        if config is not None and hasattr(config, "graph"):
            raw = config.graph.db_path or _DEFAULT_DB_PATH

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
    return (start or Path.cwd()).resolve()


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

    def __init__(self, config: ScaffoldConfig, root: Path) -> None:
        self._config = config
        self._graph = config.graph
        self.root = root.resolve()

    @classmethod
    def discover(cls, start: Path | None = None) -> ResolvedPaths:
        """Build a :class:`ResolvedPaths` by loading config + resolving the root."""
        root = resolve_root(start)
        config_path = find_config(start)
        config = load_config(config_path)
        return cls(config, root)

    def _join(self, value: str) -> Path:
        return self.root / value

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
        return self._join(self._graph.standards_dir)

    @cached_property
    def prompts_dir(self) -> Path:
        return self._join(self._graph.prompts_dir)

    @cached_property
    def templates_dir(self) -> Path:
        return self._join(self._graph.templates_dir)

    @cached_property
    def security_dir(self) -> Path:
        return self._join(self._graph.security_dir)

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
        """Resolved graph database path (relative values join to the root)."""
        return self._join(self._graph.db_path)

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
