"""User-level workspace registry and call-time project resolution (Plan 249).

Before this module, one MCP server process was bound to one directory by a ``cd``
in its ``mcp.json`` entry, so a monorepo needed one server per project and the
process could not read outside its root. The registry replaces that: it records
which workspace roots exist and which projects they contain, so a single server
can resolve the target project per call.

The registry lives at ``<home>/registry.yaml``, where ``<home>`` comes from the
existing :func:`agentscaffold.config_home.resolve_home_dir` -- this module does
not introduce a second home-resolution path.

Two behaviours here are load-bearing and easy to get subtly wrong:

Resolution matches on **path components**, not raw string prefixes, so a
registered ``/repo`` cannot swallow a sibling ``/repo-two``.

An unmatched path resolves to ``None`` so the caller can raise a structured
``ambiguous_project`` error. There is deliberately no fallback to a default
project: answering plausibly from the wrong project is the failure mode this
design exists to prevent, and it is far harder to notice than a refusal.

See ``docs/ai/contracts/workspace_registry_interface.md`` v1.0 and
``docs/security/threat_model_agentscaffold_multiproject.md``.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from agentscaffold.config import ConfigError, derive_project_name, validate_project_name
from agentscaffold.config_home import resolve_home_dir
from agentscaffold.workspace_ids import generate_workspace_id

logger = logging.getLogger(__name__)

#: Filename of the user-level registry, alongside the home ``scaffold.yaml``.
REGISTRY_FILENAME = "registry.yaml"

#: Current registry schema version. A registry declaring a higher version is
#: rejected rather than partially understood.
REGISTRY_VERSION = 1

#: Registry is user-private: it enumerates the paths of everything the user has
#: registered, and it defines the server's entire read surface.
_REGISTRY_FILE_MODE = 0o600
_REGISTRY_DIR_MODE = 0o700


class RegistryError(ConfigError):
    """Raised when the registry cannot be read, written, or updated coherently.

    Subclasses :class:`~agentscaffold.config.ConfigError` because the registry is
    configuration; callers already catching ``ConfigError`` keep working. There
    is no common exception base in this package, so composing over the existing
    hierarchy is the available option rather than inventing a parallel one.
    """


class RegisteredProject(BaseModel):
    """One project inside a registered workspace.

    Shape-compatible with :class:`agentscaffold.config.ProjectEntry`. ``path`` is
    relative to the workspace root; ``.`` means the root itself.
    """

    name: str
    path: str


class RegisteredWorkspace(BaseModel):
    """A registered workspace root and the projects it contains."""

    id: str
    root: str
    projects: list[RegisteredProject] = Field(default_factory=list)

    def project_root(self, project: RegisteredProject) -> Path:
        """Return the absolute root of *project* within this workspace."""
        return (Path(self.root) / project.path).resolve()


class Registry(BaseModel):
    """The full registry document."""

    version: int = REGISTRY_VERSION
    workspaces: list[RegisteredWorkspace] = Field(default_factory=list)

    def project_names(self) -> list[str]:
        return [p.name for w in self.workspaces for p in w.projects]

    def find_workspace_by_root(self, root: Path) -> RegisteredWorkspace | None:
        target = str(Path(root).resolve())
        for workspace in self.workspaces:
            if workspace.root == target:
                return workspace
        return None


@dataclass(frozen=True)
class ResolvedProject:
    """The single project a call resolved to.

    ``workspace_id`` is None for a lone repository resolved directly from the
    startup anchor without ever being registered. That path has to keep working
    untouched for existing single-project users, so callers that key on the
    workspace (the graph handle pool, for one) fall back to ``project_root``.
    """

    name: str
    workspace_id: str | None
    workspace_root: Path
    project_root: Path

    @property
    def pool_key(self) -> str:
        """Stable per-workspace key, defined even for unregistered lone repos."""
        return self.workspace_id or f"path:{self.project_root}"


def registry_path() -> Path:
    """Return the path of the user-level registry file."""
    return resolve_home_dir() / REGISTRY_FILENAME


def load_registry(path: Path | None = None) -> Registry:
    """Load the registry, or an empty one when the file does not exist.

    An absent registry means "nothing registered yet" and is not an error --
    fresh installs and lone repos never create one. A registry that exists but
    cannot be understood *is* an error: treating a corrupt file as empty would
    quietly unregister every project the user has.
    """
    target = path or registry_path()
    if not target.is_file():
        return Registry()

    try:
        with open(target) as fh:
            raw: Any = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise RegistryError(f"Registry at {target} is not valid YAML: {exc}") from exc

    if raw is None:
        return Registry()
    if not isinstance(raw, dict):
        raise RegistryError(f"Registry at {target} must be a mapping, got {type(raw).__name__}.")

    version = raw.get("version", REGISTRY_VERSION)
    if not isinstance(version, int) or version > REGISTRY_VERSION:
        raise RegistryError(
            f"Registry at {target} declares version {version!r}, but this AgentScaffold "
            f"understands version {REGISTRY_VERSION}. Upgrade AgentScaffold rather than "
            "editing the registry."
        )

    try:
        return Registry.model_validate(raw)
    except ValidationError as exc:
        raise RegistryError(f"Registry at {target} is malformed: {exc}") from exc


def save_registry(registry: Registry, path: Path | None = None) -> None:
    """Write the registry atomically.

    Write-temp-then-rename so a concurrent reader observes either the old
    document or the new one, never a half-written file that parses into a
    different meaning than intended.
    """
    target = path or registry_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=_REGISTRY_DIR_MODE)

    payload = yaml.safe_dump(registry.model_dump(mode="json"), sort_keys=False)

    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".registry-", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, _REGISTRY_FILE_MODE)
        os.replace(tmp_name, target)
    except BaseException:
        # Never leave a stray temp file behind on a failed write.
        Path(tmp_name).unlink(missing_ok=True)
        raise

    logger.debug("Wrote registry to %s (%d workspaces)", target, len(registry.workspaces))


def register_workspace(
    root: Path,
    name: str | None = None,
    path: Path | None = None,
) -> RegisteredWorkspace:
    """Register *root* as a workspace containing a single project.

    Re-registering the same root updates it in place and keeps its id, so the
    command is safe to re-run and a workspace never loses the state keyed to its
    id. Duplicate roots would also make longest-prefix resolution ambiguous.

    Registration is only ever explicit. Nothing in the indexing or MCP paths may
    call this as a side effect (threat model, Vector 1).
    """
    resolved_root = Path(root).resolve()
    project_name = derive_project_name(resolved_root, name)

    registry = load_registry(path)
    existing = registry.find_workspace_by_root(resolved_root)

    _reject_name_collision(registry, project_name, resolved_root)

    if existing is not None:
        existing.projects = [RegisteredProject(name=project_name, path=".")]
        entry = existing
    else:
        entry = RegisteredWorkspace(
            id=generate_workspace_id(),
            root=str(resolved_root),
            projects=[RegisteredProject(name=project_name, path=".")],
        )
        registry.workspaces.append(entry)

    save_registry(registry, path)
    return entry


def unregister_project(name: str, path: Path | None = None) -> bool:
    """Remove the project called *name*; return whether anything was removed.

    Removing something absent is a no-op rather than an error, so cleanup and
    teardown scripts stay simple. A workspace left with no projects is dropped.
    """
    registry = load_registry(path)
    remaining: list[RegisteredWorkspace] = []
    removed = False

    for workspace in registry.workspaces:
        kept = [p for p in workspace.projects if p.name != name]
        if len(kept) != len(workspace.projects):
            removed = True
        if kept:
            workspace.projects = kept
            remaining.append(workspace)

    if not removed:
        return False

    registry.workspaces = remaining
    save_registry(registry, path)
    return True


def resolve_project_for_path(
    working_path: Path | str,
    registry: Registry,
) -> ResolvedProject | None:
    """Resolve *working_path* to the most specific registered project, or None.

    Matching is on path components rather than string prefixes, so a registered
    ``/repo`` does not match a sibling ``/repo-two``. When registrations nest,
    the longest matching project root wins, so an inner project is never
    answered from its enclosing workspace.

    Returning None is a real answer, not a failure to try: the caller raises
    ``ambiguous_project`` rather than falling back to a default project.
    """
    target = Path(working_path).resolve()

    best: ResolvedProject | None = None
    best_depth = -1

    for workspace in registry.workspaces:
        workspace_root = Path(workspace.root)
        for project in workspace.projects:
            project_root = workspace.project_root(project)
            if not _contains(project_root, target):
                continue
            depth = len(project_root.parts)
            if depth > best_depth:
                best_depth = depth
                best = ResolvedProject(
                    name=project.name,
                    workspace_id=workspace.id,
                    workspace_root=workspace_root,
                    project_root=project_root,
                )

    return best


def _contains(root: Path, target: Path) -> bool:
    """Return True when *target* is *root* or lies beneath it.

    ``is_relative_to`` compares path components, which is the whole point:
    ``startswith`` would report ``/repo-two`` as living under ``/repo``.
    """
    return target == root or target.is_relative_to(root)


def _reject_name_collision(registry: Registry, name: str, root: Path) -> None:
    """Raise when *name* is already used by a workspace other than *root*.

    Project names qualify node IDs, so a collision is not merely confusing --
    it makes reads unresolvable.
    """
    validate_project_name(name)
    target = str(root)
    for workspace in registry.workspaces:
        if workspace.root == target:
            continue
        for project in workspace.projects:
            if project.name == name:
                raise RegistryError(
                    f"Project name {name!r} is already registered for workspace "
                    f"{workspace.root!r}; names must be unique across the registry. "
                    "Pass --name to choose a different one."
                )
