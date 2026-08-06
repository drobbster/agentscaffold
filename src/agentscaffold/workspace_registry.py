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

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from agentscaffold.config import ConfigError, derive_project_name, validate_project_name
from agentscaffold.config_home import resolve_home_dir
from agentscaffold.path_flavour import (
    match_depth,
    normalise_for_match,
    parse_recorded_path,
    path_contains,
    paths_equal,
)
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

#: Lock directory guarding the registry read-modify-write cycle, alongside the
#: registry file itself.
REGISTRY_LOCK_NAME = ".registry.lock"

#: Registry updates are small and quick; a wait this long means a real holder or
#: a crashed one, and either way the user deserves to be told rather than hung.
DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS = 10.0
DEFAULT_REGISTRY_LOCK_POLL_SECONDS = 0.05

#: A lock older than this is presumed abandoned by a killed process. Age is the
#: only portable signal: a recorded pid is meaningless across containers and
#: outright wrong after pid reuse.
DEFAULT_REGISTRY_LOCK_STALE_SECONDS = 300.0


class RegistryError(ConfigError):
    """Raised when the registry cannot be read, written, or updated coherently.

    Subclasses :class:`~agentscaffold.config.ConfigError` because the registry is
    configuration; callers already catching ``ConfigError`` keep working. There
    is no common exception base in this package, so composing over the existing
    hierarchy is the available option rather than inventing a parallel one.
    """


class RegistryLockError(RegistryError):
    """Raised when the registry lock cannot be acquired within the timeout.

    Distinct from a malformed or unreadable registry because the remedy is
    different: wait, or clear a lock left by a process that died.
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

    def project_match_root(self, project: RegisteredProject) -> PurePath:
        """Return *project*'s root in the flavour it was recorded in.

        Distinct from :meth:`project_root`, which returns a host ``Path`` for
        callers that will open files. This one is for comparison only and never
        touches the filesystem, so a root recorded on another operating system
        stays intact instead of being mangled into the host's flavour.
        """
        root = parse_recorded_path(self.root)
        if project.path in ("", "."):
            return normalise_for_match(root)
        return normalise_for_match(root / project.path)


class Registry(BaseModel):
    """The full registry document."""

    version: int = REGISTRY_VERSION
    workspaces: list[RegisteredWorkspace] = Field(default_factory=list)

    def project_names(self) -> list[str]:
        return [p.name for w in self.workspaces for p in w.projects]

    def find_workspace_by_root(self, root: Path) -> RegisteredWorkspace | None:
        """Find a registered workspace by root, comparing paths not strings.

        String equality is wrong on Windows, where ``C:\\Repo`` and ``c:\\repo``
        are one directory: comparing the recorded text would let the same
        workspace be registered twice, and every later read of it would then be
        ambiguous.
        """
        for workspace in self.workspaces:
            if paths_equal(workspace.root, root):
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


def registry_lock_path(path: Path | None = None) -> Path:
    """Return the lock directory guarding the registry at *path*."""
    target = path or registry_path()
    return target.parent / REGISTRY_LOCK_NAME


#: Depth of lock ownership per (thread, lock path), so nesting is reentrant.
#: Thread-local rather than global because the lock is genuinely held per thread:
#: a second thread must block, not inherit the first thread's ownership.
_lock_state = threading.local()


def _lock_depths() -> dict[str, int]:
    depths: dict[str, int] | None = getattr(_lock_state, "depths", None)
    if depths is None:
        depths = {}
        _lock_state.depths = depths
    return depths


@contextmanager
def registry_lock(
    *,
    purpose: str,
    path: Path | None = None,
    timeout: float = DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS,
    poll: float = DEFAULT_REGISTRY_LOCK_POLL_SECONDS,
    stale_after: float = DEFAULT_REGISTRY_LOCK_STALE_SECONDS,
) -> Iterator[Path]:
    """Hold an exclusive lock across a registry read-modify-write cycle.

    Step A4 made registry writes atomic, which rules out a reader seeing a
    half-written file. It does not rule out a lost update: registering reads the
    document, appends to it, and writes it back, and two of those cycles can
    interleave so that the second write discards the first's workspace. The file
    is well-formed throughout -- a workspace has simply disappeared. Atomicity is
    a property of one write; this is a property of the cycle, so the lock has to
    span the cycle (review finding ``rf::7918540f8b4b``).

    The lock is a directory because ``mkdir`` is atomic across processes on
    common local filesystems, and processes are the real case: two ``scaffold``
    invocations, not two threads. An in-process mutex would look correct in a
    threaded test and protect nothing in practice.

    Reentrant within a thread, so composing operations cannot self-deadlock.
    """
    lock = registry_lock_path(path)
    key = str(lock)
    depths = _lock_depths()

    if depths.get(key, 0) > 0:
        depths[key] += 1
        try:
            yield lock
        finally:
            depths[key] -= 1
        return

    lock.parent.mkdir(parents=True, exist_ok=True, mode=_REGISTRY_DIR_MODE)

    deadline = time.monotonic() + timeout
    while True:
        _reap_stale_lock(lock, stale_after=stale_after)
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RegistryLockError(
                    f"Timed out after {timeout:g}s waiting for the registry lock at {lock}. "
                    "Another scaffold process is probably updating the registry; if none is "
                    f"running, remove {lock} and retry."
                ) from None
            time.sleep(poll)

    _write_lock_owner(lock, purpose)
    depths[key] = 1
    try:
        yield lock
    finally:
        depths[key] -= 1
        _release_lock(lock)


def _write_lock_owner(lock: Path, purpose: str) -> None:
    """Record best-effort diagnostics. Ownership is the directory, not this file."""
    payload = {"pid": os.getpid(), "purpose": purpose, "created_at": time.time()}
    try:
        (lock / "owner.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def _release_lock(lock: Path) -> None:
    try:
        owner = lock / "owner.json"
        if owner.exists():
            owner.unlink()
        lock.rmdir()
    except OSError:
        logger.warning("Could not release registry lock at %s", lock, exc_info=True)


def _reap_stale_lock(lock: Path, *, stale_after: float) -> None:
    """Remove a lock left behind by a killed process, judged by age alone."""
    if not lock.exists():
        return
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return
    if age <= stale_after:
        return
    logger.warning("Reaping stale registry lock at %s (age %.0fs)", lock, age)
    _release_lock(lock)


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
    projects: Sequence[tuple[str, str]] | None = None,
) -> RegisteredWorkspace:
    """Register *root* as a workspace and record the projects it contains.

    With *projects* omitted the root is registered as a single project at ``.``,
    which is the lone-repo case and what ``scaffold project register`` does. A
    multi-project workspace passes ``(name, relative_path)`` pairs so one
    workspace entry covers all of them -- the grouping matters because pooled
    graph state is keyed per workspace, not per project.

    Re-registering the same root updates it in place and keeps its id, so the
    command is safe to re-run and a workspace never loses the state keyed to its
    id. Duplicate roots would also make longest-prefix resolution ambiguous.

    Registration is only ever explicit. Nothing in the indexing or MCP paths may
    call this as a side effect (threat model, Vector 1).

    The whole read-modify-write cycle runs under the registry lock, so two
    concurrent registrations serialise instead of one silently discarding the
    other. Taking the lock here rather than asking callers to is deliberate: a
    lock you have to remember to take is a convention, not a guarantee.
    """
    resolved_root = Path(root).resolve()

    if projects is None:
        entries = [RegisteredProject(name=derive_project_name(resolved_root, name), path=".")]
    else:
        entries = [RegisteredProject(name=n, path=p) for n, p in projects]
        if not entries:
            raise RegistryError(f"Refusing to register {resolved_root} with no projects.")

    purpose = ",".join(p.name for p in entries)
    with registry_lock(purpose=f"register:{purpose}", path=path):
        registry = load_registry(path)
        existing = registry.find_workspace_by_root(resolved_root)

        for entry_project in entries:
            _reject_name_collision(registry, entry_project.name, resolved_root)

        if existing is not None:
            existing.projects = entries
            entry = existing
        else:
            entry = RegisteredWorkspace(
                id=generate_workspace_id(),
                root=str(resolved_root),
                projects=entries,
            )
            registry.workspaces.append(entry)

        save_registry(registry, path)
        return entry


def unregister_project(name: str, path: Path | None = None) -> bool:
    """Remove the project called *name*; return whether anything was removed.

    Removing something absent is a no-op rather than an error, so cleanup and
    teardown scripts stay simple. A workspace left with no projects is dropped.

    Locked for the same reason as registration: removal is also a read, a
    modify, and a write, and interleaving one with a concurrent registration
    would resurrect the removed project or drop the new one.
    """
    with registry_lock(purpose=f"unregister:{name}", path=path):
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
    target = normalise_for_match(working_path)

    best: ResolvedProject | None = None
    best_depth = -1

    for workspace in registry.workspaces:
        for project in workspace.projects:
            match_root = workspace.project_match_root(project)
            if not path_contains(match_root, target):
                continue
            depth = match_depth(match_root)
            if depth > best_depth:
                best_depth = depth
                best = ResolvedProject(
                    name=project.name,
                    workspace_id=workspace.id,
                    workspace_root=Path(workspace.root),
                    project_root=Path(str(match_root)),
                )

    return best


def _reject_name_collision(registry: Registry, name: str, root: Path) -> None:
    """Raise when *name* is already used by a workspace other than *root*.

    Project names qualify node IDs, so a collision is not merely confusing --
    it makes reads unresolvable.
    """
    validate_project_name(name)
    for workspace in registry.workspaces:
        # Same-directory registrations are an update, not a collision. Compared
        # as paths so a Windows re-registration under different casing is
        # recognised as the same workspace rather than rejected as a clash.
        if paths_equal(workspace.root, root):
            continue
        for project in workspace.projects:
            if project.name == name:
                raise RegistryError(
                    f"Project name {name!r} is already registered for workspace "
                    f"{workspace.root!r}; names must be unique across the registry. "
                    "Pass --name to choose a different one."
                )
