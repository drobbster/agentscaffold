"""No-op incremental must not hold the write lock during the disk walk (Plan 267)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.graph import index
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.locks import graph_write_lock_held
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.paths import INDEX_LAST_RESULT_FILE

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def indexed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(repo / ".scaffold" / "graph.db")))
    run_pipeline(repo, config=cfg, quiet=True)
    return repo


def test_noop_walk_happens_before_backend_open_and_never_takes_write_lock(
    indexed_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = indexed_repo / ".scaffold" / "graph.db"
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(db_path)))
    order: list[str] = []

    orig_init = DuckPGQBackend.__init__

    def tracking_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("open")
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(DuckPGQBackend, "__init__", tracking_init)

    from agentscaffold.graph import structure as structure_mod

    orig_scan = structure_mod.scan_indexable_files

    def tracking_scan(*args, **kwargs):  # type: ignore[no-untyped-def]
        order.append("walk")
        assert not graph_write_lock_held(db_path)
        assert "open" not in order
        return orig_scan(*args, **kwargs)

    monkeypatch.setattr(structure_mod, "scan_indexable_files", tracking_scan)

    summary = index(path=indexed_repo, config=cfg, incremental=True, quiet=True)

    assert summary.get("noop") is True
    assert order[0] == "walk"
    assert not graph_write_lock_held(db_path)
    last_result = db_path.parent / INDEX_LAST_RESULT_FILE
    assert last_result.read_text().strip() == "noop"


def test_real_edit_still_takes_write_lock_and_is_not_noop(
    indexed_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = indexed_repo / ".scaffold" / "graph.db"
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(db_path)))
    locked: list[bool] = []

    orig_lock = DuckPGQBackend.__init__

    def tracking_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        locked.append(graph_write_lock_held(db_path))
        orig_lock(self, *args, **kwargs)

    monkeypatch.setattr(DuckPGQBackend, "__init__", tracking_init)

    py = next(indexed_repo.rglob("*.py"))
    py.write_text(py.read_text() + "\n# plan-267\n")
    summary = index(path=indexed_repo, config=cfg, incremental=True, quiet=True)

    assert summary.get("noop") is not True
    assert any(locked)
    assert (db_path.parent / INDEX_LAST_RESULT_FILE).read_text().strip() == "changed"
    assert not graph_write_lock_held(db_path)
