"""Plan 244: MCP / open_graph reads during AgentScaffold write lock."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


def _seed_graph(db: Path) -> None:
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.duckpgq_schema import init_schema

    store = DuckPGQBackend(db)
    init_schema(store._conn)
    store.create_node(
        "File",
        {"id": "f1", "path": "src/a.py", "language": "python"},
    )
    store.close()


def test_graph_write_lock_held_helper(tmp_path: Path) -> None:
    from agentscaffold.graph.locks import graph_write_lock, graph_write_lock_held

    db = tmp_path / "g.duckdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.touch()
    assert graph_write_lock_held(db) is False
    with graph_write_lock(db, purpose="test", timeout=1.0):
        assert graph_write_lock_held(db) is True
    assert graph_write_lock_held(db) is False


def test_read_only_open_skips_write_lock_wait(tmp_path: Path) -> None:
    """open_graph(read_only=True) succeeds while the AgentScaffold write lock is held."""
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import GraphLockError, open_graph
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.locks import graph_write_lock

    db = tmp_path / "g.duckdb"
    _seed_graph(db)
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(db)))

    ready = threading.Event()
    done = threading.Event()

    def writer() -> None:
        with graph_write_lock(db, purpose="index", timeout=2.0):
            w = DuckPGQBackend(db)
            ready.set()
            done.wait(timeout=10)
            w.close()

    t = threading.Thread(target=writer)
    t.start()
    assert ready.wait(5)

    t0 = time.perf_counter()
    with pytest.raises(GraphLockError):
        open_graph(cfg, lock_timeout=0.15)
    assert time.perf_counter() - t0 < 1.0

    t0 = time.perf_counter()
    reader = open_graph(cfg, read_only=True)
    elapsed = time.perf_counter() - t0
    try:
        stats = reader.get_stats()
        assert stats["files"] == 1
        assert getattr(reader, "_read_only", False) is True
    finally:
        reader.close()
    assert elapsed < 2.0

    done.set()
    t.join(timeout=5)


def test_read_only_backend_rejects_mutations(tmp_path: Path) -> None:
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import open_graph

    db = tmp_path / "g.duckdb"
    _seed_graph(db)
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(db)))
    store = open_graph(cfg, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="read-preferring"):
            store.create_node("File", {"id": "x", "path": "x.py", "language": "python"})
    finally:
        store.close()


def test_dispatch_stats_during_write_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """scaffold_stats returns data while a same-process writer holds the lock."""
    import agentscaffold.config as config_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
    from agentscaffold.graph.locks import graph_write_lock

    db = tmp_path / ".scaffold" / "graph.duckdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    _seed_graph(db)
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(db)))

    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: tmp_path)
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: cfg)
    monkeypatch.chdir(tmp_path)

    ready = threading.Event()
    done = threading.Event()

    def writer() -> None:
        with graph_write_lock(db, purpose="index", timeout=2.0):
            w = DuckPGQBackend(db)
            ready.set()
            done.wait(timeout=10)
            w.close()

    # Warm the dispatch path before timing anything. The first call in a process
    # pays a one-off lazy-import cost -- measured at ~4.2s cold against ~0.05s
    # once warm -- which swamps the thing this test is actually about. Timing it
    # cold meant the assertion below passed or failed on whether some earlier
    # test in the session happened to have warmed the imports, which is why it
    # was intermittent in isolation and stable in a full run.
    server_mod._dispatch_tool("scaffold_stats", {})

    t = threading.Thread(target=writer)
    t.start()
    assert ready.wait(5)

    t0 = time.perf_counter()
    result = server_mod._dispatch_tool("scaffold_stats", {})
    elapsed = time.perf_counter() - t0

    done.set()
    t.join(timeout=5)

    assert "graph_locked" not in result
    assert result.get("files") == 1
    assert result.get("meta", {}).get("read_during_refresh") is True
    assert elapsed < 3.0


def test_write_tool_still_waits_on_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write tools still surface graph_locked when the exclusive lock is held."""
    import agentscaffold.config as config_mod
    import agentscaffold.graph as graph_mod
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.config import GraphConfig, ScaffoldConfig
    from agentscaffold.graph import GraphLockError

    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(tmp_path / "g.duckdb")))
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: tmp_path)
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(graph_mod, "graph_available", lambda config=None: True)
    monkeypatch.setattr(server_mod.time, "sleep", lambda _s: None)

    calls = {"n": 0}

    def _raise_lock(config=None, **kwargs):
        calls["n"] += 1
        assert kwargs.get("read_only") is False
        raise GraphLockError("write still running")

    monkeypatch.setattr(graph_mod, "open_graph", _raise_lock)

    result = server_mod._dispatch_tool("scaffold_record_finding", {"plan_number": 1, "text": "x"})

    assert calls["n"] == 3
    assert result.get("graph_locked") is True
