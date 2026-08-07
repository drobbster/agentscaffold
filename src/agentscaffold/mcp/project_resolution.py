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

from agentscaffold.mcp.errors import (
    AmbiguousProjectError,
    RestrictedProjectError,
    UnknownProjectError,
)
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
    restrict_to: set[str] | None = None,
) -> ProjectResolution:
    """Resolve the project a tool call is about.

    Args:
        project: Explicit project name from the tool arguments.
        working_path: The file or directory the agent is working on.
        anchor: The startup anchor (Plan 234). Callers in the server pass
            ``resolve_mcp_start()``; tests inject a path directly.
        registry: Registry to resolve against. Loaded from disk when omitted.
        restrict_to: Optional ``--restrict-to`` allowlist of project names.
            Applied after resolution so no tier can bypass it.

    Raises:
        UnknownProjectError: *project* was given but matches nothing.
        RestrictedProjectError: resolved outside *restrict_to*.
        AmbiguousProjectError: no tier resolved.
    """
    reg = registry if registry is not None else load_registry()
    resolution = _resolve(project=project, working_path=working_path, anchor=anchor, registry=reg)

    if restrict_to and resolution.project.name not in restrict_to:
        raise RestrictedProjectError(
            f"Project '{resolution.project.name}' is outside this server's allowlist.",
            candidates=sorted(restrict_to),
        )
    return resolution


def _resolve(
    *,
    project: str | None,
    working_path: str | Path | None,
    anchor: Path | None,
    registry: Registry,
) -> ProjectResolution:
    """Run the precedence chain. See :func:`resolve_project` for the contract."""
    if project:
        resolved = _by_name(registry, project)
        if resolved is None:
            raise UnknownProjectError(
                f"Unknown project '{project}'.",
                candidates=_candidates(registry),
            )
        return ProjectResolution(resolved, ResolutionSource.EXPLICIT)

    if working_path:
        # Registry first, then the on-disk walk-up. Plan 234 shipped
        # multi-project routing via workspace.yaml with no registry involved, so
        # a registry-only tier 2 would break every workspace already relying on
        # it. The registry is a cross-workspace index layered over on-disk
        # resolution, not a replacement for it.
        resolved = _by_path(registry, working_path) or _on_disk_root(working_path)
        if resolved is not None:
            return ProjectResolution(resolved, ResolutionSource.WORKING_PATH)
        # Deliberately falls through. The contract says the first tier that
        # *matches* wins, and an unregistered path is not a statement of intent
        # the way an explicit name is -- the anchor may still resolve the call.

    if anchor is not None:
        # With an empty registry there is nothing the call could mean *other*
        # than the anchor, so accept it whatever it looks like. Demanding a
        # project marker there would turn "no graph found here" -- a clear,
        # actionable error -- into "ambiguous project", which is neither true
        # nor useful. Once projects are registered the anchor has competition,
        # so it must look like a real root to win.
        resolved = _by_path(registry, anchor) or _unregistered_root(
            anchor, require_marker=bool(registry.workspaces)
        )
        if resolved is not None:
            return ProjectResolution(resolved, ResolutionSource.STARTUP_ANCHOR)

    sole = _sole_project(registry)
    if sole is not None:
        return ProjectResolution(sole, ResolutionSource.SOLE_PROJECT)

    raise AmbiguousProjectError(
        "Cannot resolve which project this call is about. "
        "Pass project=<name> or working_path=<file or dir>.",
        candidates=_candidates(registry),
    )


def _on_disk_root(working_path: str | Path) -> ResolvedProject | None:
    """Resolve a path to its owning project root using the on-disk layout.

    Mirrors the pre-registry behaviour: walk up to the nearest ``scaffold.yaml``
    (then ``.git``), which is how ``workspace.yaml`` projects have always been
    routed.
    """
    from agentscaffold.paths import resolve_root

    try:
        candidate = Path(working_path).expanduser()
        if not candidate.is_absolute():
            from agentscaffold.paths import resolve_workspace_root

            candidate = resolve_workspace_root() / candidate
        candidate = candidate.resolve()
        if not candidate.exists():
            return None
        return _unregistered_root(resolve_root(candidate))
    except Exception:  # noqa: BLE001 - resolution is best-effort by design
        return None


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


def _unregistered_root(anchor: Path, *, require_marker: bool = True) -> ResolvedProject | None:
    """Treat an unregistered directory as a project root.

    Keeps the lone-repo case working exactly as before. A single-project user
    with no ``workspace.yaml`` and no registry should never have to register
    anything to use the server, so the anchor resolves directly with its
    directory name standing in for a registry name.

    When *require_marker* is set, the directory must hold a ``scaffold.yaml`` or
    a ``.git`` to qualify. That mirrors :func:`agentscaffold.paths.resolve_root`,
    and checking for ``.git`` too matters: requiring ``scaffold.yaml`` alone
    would reject any graph-bearing repo that never created one -- the
    AgentScaffold package repo among them.

    The caller clears *require_marker* when the registry is empty, because then
    no other project could possibly be meant and refusing would only convert a
    precise "no graph found here" into a misleading ambiguity error.
    """
    try:
        root = anchor.expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if require_marker and not ((root / "scaffold.yaml").is_file() or (root / ".git").exists()):
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
