"""Call-time project resolution for the single MCP server (Plan 249, Step A6).

Named ``project_resolution`` rather than ``projects`` because Plan 249 reserves
``mcp/projects.py`` for the ``scaffold_projects`` tool at Step A7.


One server process serves every registered workspace, so each tool call has to
decide for itself which project it is about. The precedence is defined in
``docs/ai/contracts/workspace_registry_interface.md``:

1. an explicit ``project`` argument,
2. ``working_path`` matched against registered roots by longest prefix,
3. the startup anchor retained from Plan 234,
4. the sole registered project.

If none of those resolve, the call fails with :class:`AmbiguousProjectError`. It
does **not** fall back to a default. That refusal is the point of the module: the
previous behaviour silently federated across every project or answered from the
server's launch directory, and an answer that is plausible but scoped to the
wrong project is much harder to catch than an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from agentscaffold.mcp.errors import AmbiguousProjectError, UnknownProjectError
from agentscaffold.workspace_registry import (
    RegisteredProject,
    RegisteredWorkspace,
    Registry,
    ResolvedProject,
    load_registry,
    resolve_project_for_path,
)


class ResolutionSource(str, Enum):
    """Which tier decided. Surfaced in responses so routing is auditable."""

    EXPLICIT = "explicit"
    WORKING_PATH = "working_path"
    STARTUP_ANCHOR = "startup_anchor"
    SOLE_PROJECT = "sole_project"


@dataclass(frozen=True)
class ProjectResolution:
    """A resolved project plus the tier that produced it."""

    project: ResolvedProject
    source: ResolutionSource

    @property
    def root(self) -> Path:
        return self.project.project_root


def resolve_project(
    *,
    project: str | None = None,
    working_path: str | Path | None = None,
    anchor: Path | None = None,
    registry: Registry | None = None,
) -> ProjectResolution:
    """Resolve the project a tool call is about.

    Args:
        project: Explicit project name from the tool arguments.
        working_path: The file or directory the agent is working on.
        anchor: The startup anchor (Plan 234). Callers in the server pass
            ``resolve_mcp_start()``; tests inject a path directly.
        registry: Registry to resolve against. Loaded from disk when omitted.

    Raises:
        UnknownProjectError: *project* was given but matches nothing.
        AmbiguousProjectError: no tier resolved.
    """
    reg = registry if registry is not None else load_registry()

    if project:
        resolved = _by_name(reg, project)
        if resolved is None:
            raise UnknownProjectError(
                f"Unknown project '{project}'.",
                candidates=_candidates(reg),
            )
        return ProjectResolution(resolved, ResolutionSource.EXPLICIT)

    if working_path:
        resolved = _by_path(reg, working_path)
        if resolved is not None:
            return ProjectResolution(resolved, ResolutionSource.WORKING_PATH)
        # Deliberately falls through. The contract says the first tier that
        # *matches* wins, and an unregistered path is not a statement of intent
        # the way an explicit name is -- the anchor may still resolve the call.

    if anchor is not None:
        resolved = _by_path(reg, anchor) or _unregistered_root(anchor)
        if resolved is not None:
            return ProjectResolution(resolved, ResolutionSource.STARTUP_ANCHOR)

    sole = _sole_project(reg)
    if sole is not None:
        return ProjectResolution(sole, ResolutionSource.SOLE_PROJECT)

    raise AmbiguousProjectError(
        "Cannot resolve which project this call is about. "
        "Pass project=<name> or working_path=<file or dir>.",
        candidates=_candidates(reg),
    )


def _candidates(registry: Registry) -> list[str]:
    """Every registered project name, sorted for a stable error payload."""
    return sorted(
        project.name for workspace in registry.workspaces for project in workspace.projects
    )


def _by_name(registry: Registry, name: str) -> ResolvedProject | None:
    for workspace in registry.workspaces:
        for entry in workspace.projects:
            if entry.name == name:
                return _resolved(workspace, entry)
    return None


def _resolved(workspace: RegisteredWorkspace, entry: RegisteredProject) -> ResolvedProject:
    """Build a ResolvedProject, expanding the workspace-relative project path."""
    return ResolvedProject(
        name=entry.name,
        project_root=workspace.project_root(entry),
        workspace_id=workspace.id,
        workspace_root=Path(workspace.root),
    )


def _by_path(registry: Registry, path: str | Path) -> ResolvedProject | None:
    """Longest-prefix match, tolerating paths that do not exist yet."""
    try:
        candidate = Path(path).expanduser()
    except (TypeError, ValueError):
        return None
    return resolve_project_for_path(candidate, registry=registry)


def _unregistered_root(anchor: Path) -> ResolvedProject | None:
    """Treat a real but unregistered project root as resolvable.

    Keeps the lone-repo case working exactly as before. A single-project user
    with no ``workspace.yaml`` and no registry should never have to register
    anything to use the server, so an anchor that is a genuine project root
    resolves directly, with its directory name standing in for a registry name.
    """
    try:
        root = anchor.expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if not (root / "scaffold.yaml").is_file():
        return None
    return ResolvedProject(
        name=root.name,
        project_root=root,
        workspace_id=None,
        workspace_root=root,
    )


def _sole_project(registry: Registry) -> ResolvedProject | None:
    """Return the only registered project, or None if there is not exactly one."""
    found: list[ResolvedProject] = []
    for workspace in registry.workspaces:
        for entry in workspace.projects:
            found.append(_resolved(workspace, entry))
            if len(found) > 1:
                return None
    return found[0] if found else None
