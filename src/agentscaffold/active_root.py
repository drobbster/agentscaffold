"""The active project root for the current call (Plan 249, Step A7b).

Path resolution in AgentScaffold starts from "wherever we are" -- ``find_config``
and friends walk up from the current working directory when no explicit start is
given. For the CLI that is exactly right: the user's cwd *is* the question.

The MCP server has no such thing. One server process answers calls about several
projects, so it used to make the question true by calling ``os.chdir`` to the
resolved project before each call. That works only because dispatch is
serialised -- the working directory is process-global, so two calls about
different projects cannot be in flight at once. It also meant the multi-workspace
handle pool built at Step A6 was unreachable: correct, tested, and with no way to
have two projects active for it to pool.

This module makes the active root a property of the *call* instead of the
process. A context variable is per-thread and per-task, so concurrent dispatches
each resolve their own project, and nothing outside the call is mutated.

The rule is small enough to state completely:

- An explicit ``start`` argument always wins. Callers that know where they are
  are never second-guessed.
- Otherwise the active root is used, if one is set.
- Otherwise ``Path.cwd()``, exactly as before.

So this is inert for the CLI and for every existing caller: with no active root
set, ``default_start()`` is ``Path.cwd()`` and behavior is unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

#: The project root the current call is about, or None outside any scoped call.
#: A ContextVar rather than a module global so that threads and asyncio tasks do
#: not see each other's value -- which is the entire point of replacing chdir.
_ACTIVE_ROOT: ContextVar[Path | None] = ContextVar("agentscaffold_active_root", default=None)


def get_active_root() -> Path | None:
    """Return the project root scoped to this call, or None if unscoped."""
    return _ACTIVE_ROOT.get()


@contextmanager
def active_root(root: Path | str) -> Iterator[Path]:
    """Scope path resolution to *root* for the duration of the block.

    Nests, and restores the previous value on exit including on exception. The
    root is resolved once on entry so that later cwd changes (or a deleted cwd)
    cannot retarget an in-flight call.
    """
    resolved = Path(root).resolve()
    token = _ACTIVE_ROOT.set(resolved)
    try:
        yield resolved
    finally:
        _ACTIVE_ROOT.reset(token)


def default_start() -> Path:
    """The directory path resolution starts from when no start is given.

    Every ``(start or Path.cwd())`` chokepoint routes through here, which is what
    lets one line in the MCP dispatcher redirect a whole call's path resolution
    without touching process state.
    """
    root = _ACTIVE_ROOT.get()
    if root is not None:
        return root
    return Path.cwd()
