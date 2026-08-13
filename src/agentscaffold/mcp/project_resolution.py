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
        working_path = _absolutise(working_path, registry)
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
            anchor, require_marker=bool(registry.workspaces), registry=registry
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


def _absolutise(working_path: str | Path, registry: Registry) -> str | Path:
    """Interpret a relative *working_path* against the registered roots.

    Returned unchanged when absolute, or when no single registered root explains
    it.

    A relative path is the natural thing for an agent to send -- it is what the
    editor shows -- and it is the one form this process cannot interpret locally.
    The server's own directory is a launch artefact with no relationship to the
    caller's workspace, so joining a fragment onto it yields a path that either
    does not exist (the call silently falls back to the anchor) or exists and
    belongs to something unrelated (worse). The registered roots are the only
    frame of reference the server actually has.

    One on-disk match is required. Several means the fragment names a real path in
    more than one workspace, and choosing between them would be exactly the guess
    ADR-026 removes; leaving it unresolved lets the call refuse, and the response
    meta reports the path as unmatched either way.
    """
    path = Path(working_path).expanduser()
    if path.is_absolute():
        return working_path

    matches: list[Path] = []
    for workspace in registry.workspaces:
        bases = [Path(workspace.root)]
        bases.extend(workspace.project_root(entry) for entry in workspace.projects)
        for base in bases:
            try:
                candidate = (base / path).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate.exists() and candidate not in matches:
                matches.append(candidate)

    if len(matches) == 1:
        return matches[0]
    return working_path


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


def _unregistered_root(
    anchor: Path, *, require_marker: bool = True, registry: Registry | None = None
) -> ResolvedProject | None:
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

    A marker is necessary but not sufficient (ADR-026). Given a *registry*, a
    directory with registered project roots beneath it is declined however much
    it looks like a repo, because it is a place that *contains* projects rather
    than being one -- a home directory holding a dotfiles ``.git``, or an
    enclosing repo the root walk-up happened to reach. Marker checks cannot tell
    those apart from a real project, and answering from one is how a plausible
    reply ends up describing an entirely different codebase.
    """
    try:
        root = anchor.expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if require_marker and not ((root / "scaffold.yaml").is_file() or (root / ".git").exists()):
        return None
    if registry is not None and _contains_registered_projects(root, registry):
        return None
    return ResolvedProject(
        name=_synthesised_name(root),
        project_root=root,
        workspace_id=None,
        workspace_root=root,
    )


def _synthesised_name(root: Path) -> str:
    """The name to answer under for a project that is not in the registry.

    A ``workspace.yaml`` in *root* that names the project living at *root* wins
    over the directory basename. The graph scopes its rows by the manifest name,
    so synthesising a basename that disagrees with it produces the most confusing
    outcome available: resolution succeeds, the response looks right, and every
    scoped read comes back empty because it is filtering on a name nothing was
    ever written under.

    Falls back to :func:`derive_project_name`, which normalises whitespace and
    validates -- and to the raw basename if even that is rejected, since a
    resolution path is the wrong place to start failing calls over a directory
    name that has worked until now.
    """
    from agentscaffold.config import derive_project_name

    declared = _manifest_project_name(root)
    if declared is not None:
        return declared
    try:
        return derive_project_name(root)
    except Exception:  # noqa: BLE001 - an exotic basename must not fail the call
        return root.name


def _manifest_project_name(root: Path) -> str | None:
    """The name *root*'s own manifest gives to the project living at *root*.

    Deliberately reads only ``root/workspace.yaml`` and never walks up: an
    ancestor's manifest describes a different directory, and borrowing a name from
    it would attribute this project to its neighbour.
    """
    manifest = root / "workspace.yaml"
    if not manifest.is_file():
        return None
    try:
        from agentscaffold.config import load_workspace_manifest

        workspace = load_workspace_manifest(manifest)
        for entry in workspace.projects:
            if (root / entry.path).resolve() == root:
                return entry.name
    except Exception:  # noqa: BLE001 - a malformed manifest falls back to the basename
        return None
    return None


def _contains_registered_projects(root: Path, registry: Registry) -> bool:
    """Whether any registered project root lies strictly beneath *root*.

    Strictly: a directory that *is* a registered project root is that project,
    and would have been matched by :func:`_by_path` before this is reached.
    Comparison goes through the path-flavour helpers so a recorded Windows or WSL
    root is not measured against a POSIX one.
    """
    from agentscaffold.path_flavour import path_contains, paths_equal

    for workspace in registry.workspaces:
        for entry in workspace.projects:
            candidate = workspace.project_root(entry)
            if paths_equal(candidate, root):
                continue
            if path_contains(root, candidate):
                return True
    return False


def _sole_project(registry: Registry) -> ResolvedProject | None:
    """Return the only registered project, or None if there is not exactly one."""
    found: list[ResolvedProject] = []
    for workspace in registry.workspaces:
        for entry in workspace.projects:
            found.append(_resolved(workspace, entry))
            if len(found) > 1:
                return None
    return found[0] if found else None
