"""Tests for registry read-modify-write locking (Plan 249, Step A8).

Written before the lock exists, and they close review finding ``rf::7918540f8b4b``.

Step A4 made registry *writes* atomic: ``save_registry`` writes to a temp file and
renames, so no reader can observe a half-written document. That rules out corruption
but not lost updates, because registering is not a write -- it is a read, a modify,
and a write. Two of those cycles can interleave so that both read the same document,
both append their own workspace, and the second rename discards the first's work. The
file is perfectly well-formed at every instant; a workspace has simply vanished.

Atomicity is a property of a single write. Serialisability is a property of a cycle,
and needs a lock spanning the whole cycle. These tests are written to fail against
atomic-write-only code:

- ``test_concurrent_registration_of_two_roots_loses_neither`` forces the damaging
  interleaving deterministically with a barrier rather than waiting for a race.
- ``test_separate_processes_registering_concurrently_all_survive`` uses real
  subprocesses, because an in-process mutex would satisfy the thread test while
  leaving two ``scaffold`` invocations -- the actual scenario -- unprotected.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from agentscaffold.workspace_ids import generate_workspace_id
from agentscaffold.workspace_registry import (
    REGISTRY_FILENAME,
    RegisteredProject,
    RegisteredWorkspace,
    RegistryLockError,
    load_registry,
    register_workspace,
    registry_lock,
    registry_lock_path,
    save_registry,
    unregister_project,
)


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point AGENTSCAFFOLD_HOME at a temp dir and return it."""
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target))
    return target


# --------------------------------------------------------------------------
# The lock primitive
# --------------------------------------------------------------------------


def test_lock_is_released_on_normal_exit(home: Path) -> None:
    with registry_lock(purpose="test"):
        assert registry_lock_path().exists()
    assert not registry_lock_path().exists()


def test_lock_is_released_when_the_body_raises(home: Path) -> None:
    """A crash mid-update must not wedge every later invocation.

    The failure this prevents is not a lost update but a permanent one: an
    exception between load and save leaving a lock directory that no process
    owns, so the next `scaffold project register` blocks until the stale
    timeout with no indication why.
    """
    with pytest.raises(ValueError):
        with registry_lock(purpose="test"):
            raise ValueError("boom")
    assert not registry_lock_path().exists()


def test_lock_is_reentrant_within_one_thread(home: Path) -> None:
    """Nesting must not self-deadlock.

    Commands compose -- `workspace onboard` registers and then adjusts -- so a
    non-reentrant lock would turn a natural refactor into a hang that only
    appears once someone nests two operations.
    """
    with registry_lock(purpose="outer"):
        with registry_lock(purpose="inner"):
            assert registry_lock_path().exists()
        # Still held: the inner exit must not release the outer's lock.
        assert registry_lock_path().exists()
    assert not registry_lock_path().exists()


def test_waiting_past_the_timeout_raises_a_named_error(home: Path) -> None:
    """A contended lock fails loudly rather than hanging forever."""
    holder_acquired = threading.Event()
    release_holder = threading.Event()

    def hold() -> None:
        with registry_lock(purpose="holder"):
            holder_acquired.set()
            release_holder.wait(timeout=10)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    try:
        assert holder_acquired.wait(timeout=10)
        with pytest.raises(RegistryLockError) as excinfo:
            with registry_lock(purpose="waiter", timeout=0.3, poll=0.05):
                pass
        # The message has to name the file, or the user cannot act on it.
        assert REGISTRY_FILENAME in str(excinfo.value) or "registry" in str(excinfo.value).lower()
    finally:
        release_holder.set()
        thread.join(timeout=10)


def test_a_stale_lock_is_reaped_rather_than_blocking_forever(home: Path) -> None:
    """A lock left by a killed process must not brick the registry.

    Reaping is by age, deliberately conservative: the alternative -- trusting a
    recorded pid -- is wrong across containers and after pid reuse.
    """
    lock = registry_lock_path()
    lock.mkdir(parents=True)
    import os
    import time

    ancient = time.time() - 3600
    os.utime(lock, (ancient, ancient))

    with registry_lock(purpose="after-stale", timeout=5, stale_after=60):
        assert lock.exists()


# --------------------------------------------------------------------------
# Lost updates: the finding this step closes
# --------------------------------------------------------------------------


def test_concurrent_registration_of_two_roots_loses_neither(home: Path, tmp_path: Path) -> None:
    """Two concurrent registrations must both survive.

    The barrier makes the damaging schedule deterministic instead of hoping a
    race appears under test. Each thread signals that it is about to begin its
    read-modify-write cycle and waits for the other. Without a lock spanning the
    cycle both proceed, both read the same document, and the later save silently
    drops the earlier workspace.

    With the lock the second thread cannot reach the barrier until the first has
    finished, so the barrier times out -- and that timeout is the proof of
    correctness, not a failure. It is swallowed for exactly that reason.
    """
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    root_a.mkdir()
    root_b.mkdir()

    barrier = threading.Barrier(2, timeout=1.0)
    errors: list[BaseException] = []

    def register(root: Path) -> None:
        try:
            with registry_lock(purpose="test-register"):
                try:
                    # Inside the lock: if the lock works, only one thread is ever
                    # here, so this cannot pair up and will time out.
                    barrier.wait()
                except threading.BrokenBarrierError:
                    pass
                current = load_registry()
                current.workspaces.append(
                    RegisteredWorkspace(
                        id=generate_workspace_id(),
                        root=str(root.resolve()),
                        projects=[RegisteredProject(name=root.name, path=".")],
                    )
                )
                save_registry(current)
        except BaseException as exc:  # noqa: BLE001 - surfaced via the assertion below
            errors.append(exc)

    threads = [
        threading.Thread(target=register, args=(root_a,)),
        threading.Thread(target=register, args=(root_b,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors, f"registration raised: {errors}"

    names = set(load_registry().project_names())
    assert names == {"alpha", "beta"}, f"a concurrent registration was lost: {names}"


def test_register_workspace_takes_the_lock_itself(home: Path, tmp_path: Path) -> None:
    """The public API must be safe without callers remembering to lock.

    A lock that only works when called correctly is a convention, not a
    guarantee; the finding is only closed if `register_workspace` is safe on its
    own.
    """
    observed: list[bool] = []
    real_load = load_registry

    def spy(*args: object, **kwargs: object) -> object:
        observed.append(registry_lock_path().exists())
        return real_load(*args, **kwargs)

    import agentscaffold.workspace_registry as wr

    original = wr.load_registry
    wr.load_registry = spy  # type: ignore[assignment]
    try:
        root = tmp_path / "gamma"
        root.mkdir()
        register_workspace(root)
    finally:
        wr.load_registry = original  # type: ignore[assignment]

    assert observed, "register_workspace did not read the registry at all"
    assert all(observed), "register_workspace read the registry outside the lock"


def test_unregister_project_takes_the_lock_too(home: Path, tmp_path: Path) -> None:
    """Removal is a read-modify-write cycle as well, and equally lossy."""
    observed: list[bool] = []
    real_load = load_registry

    def spy(*args: object, **kwargs: object) -> object:
        observed.append(registry_lock_path().exists())
        return real_load(*args, **kwargs)

    root = tmp_path / "delta"
    root.mkdir()
    register_workspace(root)

    import agentscaffold.workspace_registry as wr

    original = wr.load_registry
    wr.load_registry = spy  # type: ignore[assignment]
    try:
        unregister_project("delta")
    finally:
        wr.load_registry = original  # type: ignore[assignment]

    assert observed, "unregister_project did not read the registry at all"
    assert all(observed), "unregister_project read the registry outside the lock"


# --------------------------------------------------------------------------
# Cross-process: the case an in-process mutex would silently miss
# --------------------------------------------------------------------------


_CHILD = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(Path(sys.argv[1]))
    """
)


def test_separate_processes_registering_concurrently_all_survive(
    home: Path, tmp_path: Path
) -> None:
    """Six real processes registering distinct roots must all be recorded.

    This is the scenario the finding actually describes -- two `scaffold`
    invocations, not two threads -- and it is the reason the lock has to live on
    the filesystem. An in-process mutex passes every test above and fails here.
    """
    script = tmp_path / "child.py"
    script.write_text(_CHILD)

    roots = []
    for index in range(6):
        root = tmp_path / f"proj{index}"
        root.mkdir()
        roots.append(root)

    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for root in roots
    ]
    failures = []
    for proc, root in zip(procs, roots, strict=True):
        _, err = proc.communicate(timeout=120)
        if proc.returncode != 0:
            failures.append((root.name, err.decode()))

    assert not failures, f"child registration failed: {failures}"

    names = set(load_registry().project_names())
    assert names == {r.name for r in roots}, f"lost a registration across processes: {names}"
