"""Reclaim state left behind by workspaces that are gone (Plan 249, Step B8).

Two things accumulate once state lives outside the working tree. Registry
entries outlive the repositories they point at, and state directories outlive
the workspaces they were keyed to -- a deleted checkout takes its `.git` with it
but has no way to reach into `~/.local/state` on its way out.

The asymmetry that shapes this module: an unnecessary state directory costs disk
space, and a wrongly deleted one costs a full re-index of a corpus that may have
taken minutes to build and is not in version control. So the question gc asks is
not "can I show this is still needed" but "can I *prove* this is not".

That proof needs evidence a directory name alone cannot carry. A state directory
is named for a workspace id, and an id can legitimately belong to a workspace
nobody registered, because the manifest is the source of truth and the registry
is a convenience. Absence from the registry is therefore not evidence. Each
state directory instead records the root it was created for, and orphanhood is
proven from that record: the root is gone, or it now resolves to a different id.
A directory without that record is reported and kept, which is the direction to
be wrong in.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from agentscaffold.paths import (
    STATE_PROVENANCE_FILENAME,
    read_state_provenance,
    resolve_user_state_dir,
    resolve_workspace_state_id,
)


@dataclass
class GcPlan:
    """What gc would do, computed identically whether or not it will do it."""

    orphaned_state: list[tuple[Path, str]] = field(default_factory=list)
    stale_registry: list[tuple[str, str]] = field(default_factory=list)
    unverifiable_state: list[Path] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        return bool(self.orphaned_state or self.stale_registry)


def _state_directories() -> list[Path]:
    root = resolve_user_state_dir()
    if not root.is_dir():
        return []
    return sorted(child for child in root.iterdir() if child.is_dir())


def _classify_state_dir(directory: Path) -> tuple[str, str] | None:
    """Return ``(verdict, reason)`` for one state directory.

    ``verdict`` is ``"orphaned"``, ``"live"``, or ``"unverifiable"``.
    """
    provenance = read_state_provenance(directory)
    if provenance is None:
        return ("unverifiable", "no record of which workspace this belongs to")

    root = Path(provenance.get("root", ""))
    if not root.is_dir():
        return ("orphaned", f"its workspace root {root} no longer exists")

    current = resolve_workspace_state_id(root)
    if current is None:
        # The root is still there but no longer carries an id, so it resolves
        # to an in-tree graph. Nothing reads this directory any more.
        return ("orphaned", f"{root} is no longer registered and reads an in-tree graph")
    if current != directory.name:
        return ("orphaned", f"{root} now resolves to {current}")
    return ("live", f"in use by {root}")


def plan_gc() -> GcPlan:
    """Compute what is safe to remove, without removing anything."""
    from agentscaffold.workspace_registry import load_registry

    plan = GcPlan()

    for directory in _state_directories():
        classified = _classify_state_dir(directory)
        if classified is None:  # pragma: no cover - defensive
            continue
        verdict, reason = classified
        if verdict == "orphaned":
            plan.orphaned_state.append((directory, reason))
        elif verdict == "unverifiable":
            plan.unverifiable_state.append(directory)

    try:
        registry = load_registry()
    except Exception:  # pragma: no cover - unreadable registry is doctor's problem
        return plan

    for workspace in registry.workspaces:
        if not Path(workspace.root).is_dir():
            plan.stale_registry.append((workspace.id, workspace.root))

    return plan


def apply_gc(plan: GcPlan) -> GcPlan:
    """Carry out *plan*. Only ever called behind an explicit ``--apply``."""
    from agentscaffold.workspace_registry import load_registry, save_registry

    for directory, _reason in plan.orphaned_state:
        shutil.rmtree(directory, ignore_errors=True)

    if plan.stale_registry:
        stale_ids = {workspace_id for workspace_id, _root in plan.stale_registry}
        registry = load_registry()
        registry.workspaces = [w for w in registry.workspaces if w.id not in stale_ids]
        save_registry(registry)

    return plan


__all__ = ["GcPlan", "STATE_PROVENANCE_FILENAME", "apply_gc", "plan_gc"]
