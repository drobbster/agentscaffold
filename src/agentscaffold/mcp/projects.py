"""The ``scaffold_projects`` tool (Plan 249, Step A7).

Once one server process serves every registered workspace, an agent needs a way
to ask what it is allowed to ask about. Without it, discovering the available
projects means guessing names until one stops returning ``unknown_project``, and
an ``ambiguous_project`` refusal lists candidates but says nothing about which
project the agent is currently in.

So this reports both halves: the projects that exist, and how the current call
resolved to one of them. The resolution source is included deliberately -- a call
answered from the startup anchor and a call answered from an explicit
``working_path`` look identical in every other response, and that is exactly the
confusion this plan exists to remove.
"""

from __future__ import annotations

from typing import Any

from agentscaffold.mcp.project_resolution import ProjectResolution
from agentscaffold.workspace_registry import Registry, load_registry, registry_path


def build_projects_payload(
    resolution: ProjectResolution | None,
    *,
    registry: Registry | None = None,
    restrict_to: set[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the visible projects and how this call resolved.

    Args:
        resolution: How the current call resolved, or None if it could not.
        registry: Registry to report. Loaded from disk when omitted.
        restrict_to: Active ``--restrict-to`` allowlist, if any.
        meta: Standard tool meta block.
    """
    reg = registry if registry is not None else load_registry()
    allowed = set(restrict_to or ())

    projects: list[dict[str, Any]] = []
    for workspace in reg.workspaces:
        for entry in workspace.projects:
            projects.append(
                {
                    "name": entry.name,
                    "workspace_id": workspace.id,
                    "workspace_root": str(workspace.root),
                    "project_root": str(workspace.project_root(entry)),
                    "registered": True,
                    # Only meaningful when an allowlist is active; a bare False
                    # on every row would read as "denied" rather than "n/a".
                    **({"allowed": entry.name in allowed} if allowed else {}),
                }
            )

    # A project resolved from the startup anchor without ever being registered
    # is real and answerable, so it belongs in the list even though the registry
    # has never heard of it. Omitting it would make the tool contradict itself:
    # reporting an active project absent from the projects it lists.
    active: dict[str, Any] | None = None
    if resolution is not None:
        active = {
            "name": resolution.project.name,
            "source": resolution.source.value,
            "project_root": str(resolution.project.project_root),
        }
        if not any(p["name"] == resolution.project.name for p in projects):
            projects.append(
                {
                    "name": resolution.project.name,
                    "workspace_id": resolution.project.workspace_id,
                    "workspace_root": str(resolution.project.workspace_root),
                    "project_root": str(resolution.project.project_root),
                    "registered": False,
                }
            )

    payload: dict[str, Any] = {
        "projects": sorted(projects, key=lambda p: p["name"]),
        "count": len(projects),
        "active_project": active,
        "registry_path": str(registry_path()),
        "registry_exists": registry_path().is_file(),
        "meta": meta or {},
    }
    if allowed:
        payload["restricted_to"] = sorted(allowed)
    if not projects:
        payload["why_empty"] = (
            "No projects are registered and no project could be resolved from the "
            "startup anchor. Register one with 'scaffold project register <root>', "
            "or pass working_path on the call."
        )
    return payload
