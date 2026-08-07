"""Tests for the explicit active-root context (Plan 249, Step A7b).

Dispatch used to reach the resolved project by ``os.chdir``. That works only
because tool calls are serialised: the working directory is process-global, so
two calls for different projects cannot be in flight at once. It is also why the
multi-workspace handle pool built at Step A6 was correct, tested, and unreachable
-- there was no way to have two projects active simultaneously for it to pool.

Replacing it with a context variable makes the active project a property of the
call rather than of the process. The decisive test is the one that could not be
written before: two threads dispatching against different projects, each reading
its own.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


def _project(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(f"project:\n  name: {name}\n")
    return root


# ---------------------------------------------------------------------------
# The context primitive
# ---------------------------------------------------------------------------


def test_context_supplies_the_root_when_no_start_is_given(tmp_path: Path) -> None:
    from agentscaffold.active_root import active_root
    from agentscaffold.paths import resolve_root

    alpha = _project(tmp_path / "alpha", "alpha")

    with active_root(alpha):
        assert resolve_root() == alpha.resolve()


def test_explicit_start_still_beats_the_context(tmp_path: Path) -> None:
    """The context is a default, not an override; callers that know still win."""
    from agentscaffold.active_root import active_root
    from agentscaffold.paths import resolve_root

    alpha = _project(tmp_path / "alpha", "alpha")
    beta = _project(tmp_path / "beta", "beta")

    with active_root(alpha):
        assert resolve_root(beta) == beta.resolve()


def test_context_is_restored_on_exit_including_on_error(tmp_path: Path) -> None:
    from agentscaffold.active_root import active_root, get_active_root

    alpha = _project(tmp_path / "alpha", "alpha")

    assert get_active_root() is None
    with pytest.raises(RuntimeError):
        with active_root(alpha):
            assert get_active_root() == alpha.resolve()
            raise RuntimeError("boom")
    assert get_active_root() is None


def test_contexts_nest(tmp_path: Path) -> None:
    from agentscaffold.active_root import active_root, get_active_root

    alpha = _project(tmp_path / "alpha", "alpha")
    beta = _project(tmp_path / "beta", "beta")

    with active_root(alpha):
        with active_root(beta):
            assert get_active_root() == beta.resolve()
        assert get_active_root() == alpha.resolve()


def test_falls_back_to_cwd_when_no_context_is_set(tmp_path: Path) -> None:
    """Everything outside the MCP server still resolves exactly as before."""
    from agentscaffold.paths import resolve_root

    alpha = _project(tmp_path / "alpha", "alpha")
    original = os.getcwd()
    os.chdir(alpha)
    try:
        assert resolve_root() == alpha.resolve()
    finally:
        os.chdir(original)


def test_config_lookup_honours_the_context(tmp_path: Path) -> None:
    """find_config is one of the four cwd chokepoints the context has to cover."""
    from agentscaffold.active_root import active_root
    from agentscaffold.config import find_config

    alpha = _project(tmp_path / "alpha", "alpha")

    with active_root(alpha):
        assert find_config() == (alpha / "scaffold.yaml").resolve()


def test_workspace_lookup_honours_the_context(tmp_path: Path) -> None:
    from agentscaffold.active_root import active_root
    from agentscaffold.config import find_workspace_config

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text("projects:\n  - name: alpha\n    path: alpha\n")
    alpha = _project(ws / "alpha", "alpha")

    with active_root(alpha):
        assert find_workspace_config() == (ws / "workspace.yaml").resolve()


def test_threads_hold_independent_active_roots(tmp_path: Path) -> None:
    """The property chdir cannot have: two projects active at the same instant."""
    from agentscaffold.active_root import active_root
    from agentscaffold.paths import resolve_root

    alpha = _project(tmp_path / "alpha", "alpha")
    beta = _project(tmp_path / "beta", "beta")
    both_inside = threading.Barrier(2, timeout=5)
    seen: dict[str, Path] = {}

    def run(name: str, root: Path) -> None:
        with active_root(root):
            both_inside.wait()  # hold both contexts open simultaneously
            seen[name] = resolve_root()

    threads = [
        threading.Thread(target=run, args=("alpha", alpha)),
        threading.Thread(target=run, args=("beta", beta)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert seen == {"alpha": alpha.resolve(), "beta": beta.resolve()}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target))
    return target


def test_dispatch_does_not_change_the_working_directory(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool call must not mutate process-global state on the caller's behalf.

    This is what made concurrent dispatch unsafe, and what leaked a deleted cwd
    into unrelated suites when a test's tmp_path was cleaned up (see A6b).
    """
    import agentscaffold.config as config_mod
    import agentscaffold.graph as graph_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.mcp.server import _dispatch_tool

    alpha = _project(tmp_path / "alpha", "alpha")
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: alpha)
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: ScaffoldConfig())
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)
    monkeypatch.setattr(
        graph_mod, "open_graph", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    )

    before = os.getcwd()
    _dispatch_tool("scaffold_orient", {})

    assert os.getcwd() == before


def test_concurrent_dispatches_each_read_their_own_project(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test that could not exist under chdir, and the reason A7b exists.

    Both calls are held open at the same instant. Under the previous design the
    second chdir would have retargeted the first call's reads.
    """
    import agentscaffold.config as config_mod
    import agentscaffold.graph as graph_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.mcp.server import _dispatch_tool
    from agentscaffold.paths import resolve_root

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text(
        "projects:\n  - name: alpha\n    path: alpha\n  - name: beta\n    path: beta\n"
    )
    for name in ("alpha", "beta"):
        _project(ws / name, name)

    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: ws / "alpha")
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: ScaffoldConfig())
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)

    both_inside = threading.Barrier(2, timeout=5)
    seen: dict[str, Path] = {}

    def _open(*args, **kwargs):
        # Resolve the way a scoped read would, while the sibling call is also
        # mid-flight, then bail. Dispatch turns the raise into an error dict.
        root = resolve_root()
        both_inside.wait()
        seen[root.name] = root
        raise RuntimeError("stub: graph open not supported in this test")

    monkeypatch.setattr(graph_mod, "open_graph", _open)

    threads = [
        threading.Thread(
            target=_dispatch_tool,
            args=("scaffold_orient", {"working_path": str(ws / name)}),
        )
        for name in ("alpha", "beta")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert seen == {
        "alpha": (ws / "alpha").resolve(),
        "beta": (ws / "beta").resolve(),
    }
