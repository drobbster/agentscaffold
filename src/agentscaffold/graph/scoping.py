"""Project scoping for the shared knowledge graph (Plan 225, Step 4).

A single graph cache can hold many projects (a multi-project workspace). This
module is the one place that decides *which* project a read or write belongs to
and turns that decision into SQL predicates -- for both plain ``SELECT``s and
``GRAPH_TABLE MATCH`` queries -- so no callsite hand-rolls its own filter.

Fail-closed by construction: in a multi-project workspace the default scope is
the **current project** (resolved from the working directory). Federation
across all projects is never the default; a caller must ask for it explicitly
(``all_projects=True``). In a single-project workspace every predicate is a
no-op, so a lone repo behaves exactly as before.

Identity: ``{project}::{raw_id}``. Raw IDs already contain ``::`` (e.g.
``plan::224``), so :func:`qualify_id` / :func:`unqualify_id` split on the FIRST
delimiter only, and project names are validated to exclude it (config layer).
The ``project`` column -- not the prefix -- is the authoritative scoping key;
prefix parsing is a convenience.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentscaffold.config import PROJECT_DELIMITER, WorkspaceConfig
from agentscaffold.paths import load_workspace, resolve_root, resolve_workspace_root


class ScopingError(Exception):
    """Raised when a project scope cannot be resolved (fail-closed)."""


# ---------------------------------------------------------------------------
# ID qualification
# ---------------------------------------------------------------------------


def qualify_id(project: str, raw_id: str) -> str:
    """Project-qualify a raw node ID: ``{project}::{raw_id}`` (multi-project only)."""
    return f"{project}{PROJECT_DELIMITER}{raw_id}"


def unqualify_id(qualified_id: str, known_projects: set[str] | None = None) -> tuple[str, str]:
    """Split a (possibly) project-qualified ID into ``(project, raw_id)``.

    Splits on the FIRST delimiter only. When *known_projects* is given, a head
    that is not a known project name is treated as unqualified (returns
    ``("", qualified_id)``) -- this disambiguates an unprefixed single-project ID
    like ``plan::224`` from a prefixed ``alpha::plan::224``. Without it the split
    is best-effort and should only be used on IDs known to be qualified.
    """
    head, sep, raw = qualified_id.partition(PROJECT_DELIMITER)
    if not sep:
        return ("", qualified_id)
    if known_projects is not None and head not in known_projects:
        return ("", qualified_id)
    return (head, raw)


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """A resolved read/write scope over the shared graph.

    - single-project (``multi`` False): predicates are no-ops.
    - current/targeted (``multi`` True, ``project`` set): filter to that project.
    - federated (``multi`` True, ``project`` None): no filter, but reads should
      surface per-row provenance.
    """

    project: str | None
    multi: bool

    @property
    def is_federated(self) -> bool:
        return self.multi and self.project is None

    @property
    def is_noop(self) -> bool:
        """True when no predicate should be emitted (single-project or federated)."""
        return not self.multi or self.project is None


def current_project_name(start: Path | None = None) -> str:
    """Resolve the current project's name from the working directory (fail-closed).

    Single-project: the lone project's name. Multi-project: match the nearest
    project root (:func:`resolve_root`) to a workspace entry by resolved path;
    raise :class:`ScopingError` if the cwd is not inside any registered project.
    """
    workspace = load_workspace(start)
    if not workspace.is_multi_project:
        return workspace.projects[0].name

    root = resolve_root(start).resolve()
    ws_root = resolve_workspace_root(start)
    for entry in workspace.projects:
        entry_path = Path(entry.path)
        if not entry_path.is_absolute():
            entry_path = ws_root / entry_path
        if entry_path.resolve() == root:
            return entry.name
    raise ScopingError(
        f"Working directory {root} is not inside any registered project of the "
        f"workspace at {ws_root} (projects: {workspace.project_names()}). "
        "Run from within a project, or pass --project explicitly."
    )


def resolve_scope(
    project: str | None = None,
    all_projects: bool = False,
    start: Path | None = None,
    workspace: WorkspaceConfig | None = None,
) -> Scope:
    """Resolve a :class:`Scope` from CLI-style inputs (fail-closed to current).

    Precedence: single-project workspace -> no-op scope; ``all_projects`` ->
    federated; explicit ``project`` -> targeted (validated against the
    workspace); otherwise the current project.
    """
    workspace = workspace if workspace is not None else load_workspace(start)
    if not workspace.is_multi_project:
        return Scope(project=None, multi=False)
    if all_projects:
        return Scope(project=None, multi=True)
    if project is not None:
        if workspace.find_by_name(project) is None:
            raise ScopingError(
                f"Unknown project {project!r}; workspace has {workspace.project_names()}."
            )
        return Scope(project=project, multi=True)
    return Scope(project=current_project_name(start), multi=True)


# ---------------------------------------------------------------------------
# Predicate builders
# ---------------------------------------------------------------------------


def sql_predicate(scope: Scope, column: str = "project") -> tuple[str, list[str]]:
    """Plain-SQL project predicate for a scope.

    Returns ``(fragment, params)`` where *fragment* is a bare boolean condition
    (e.g. ``"project = ?"``) suitable to AND into a WHERE clause, or ``("", [])``
    for a no-op (single-project or federated) scope. The caller composes the
    WHERE/AND; this never emits the keyword so it is safe to combine.
    """
    if scope.is_noop:
        return ("", [])
    return (f"{column} = ?", [scope.project])  # type: ignore[list-item]


def graph_predicate(scope: Scope, alias: str) -> tuple[str, list[str]]:
    """``GRAPH_TABLE MATCH`` project predicate, qualified by a bound-vertex *alias*.

    Same contract as :func:`sql_predicate` but references ``{alias}.project`` so
    it can be ANDed into a MATCH ... WHERE clause.
    """
    if scope.is_noop:
        return ("", [])
    return (f"{alias}.project = ?", [scope.project])  # type: ignore[list-item]
