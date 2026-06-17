"""Incremental-index scoping tests for Plan 231."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentscaffold.graph import incremental


class _FileStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        del sql, params
        return self.rows


def test_compute_changeset_uses_metadata_prefilter(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "module.py"
    source.write_text("def f():\n    return 1\n")
    stat = source.stat()
    store = _FileStore(
        [
            {
                "f.path": "module.py",
                "f.contentHash": "stale-hash-that-should-not-be-read",
                "f.size": stat.st_size,
                "f.lastModified": str(stat.st_mtime),
            }
        ]
    )
    calls = {"count": 0}

    def _counting_hash(_path: Path) -> str:
        calls["count"] += 1
        return "different"

    monkeypatch.setattr(incremental, "_file_hash", _counting_hash)

    changeset = incremental.compute_changeset(store, tmp_path)

    assert changeset["added"] == []
    assert changeset["modified"] == []
    assert changeset["deleted"] == []
    assert changeset["unchanged"] == 1
    assert calls["count"] == 0


def test_compute_changeset_hashes_when_metadata_differs(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "module.py"
    source.write_text("def f():\n    return 1\n")
    stat = source.stat()
    store = _FileStore(
        [
            {
                "f.path": "module.py",
                "f.contentHash": "stored-hash",
                "f.size": stat.st_size + 1,
                "f.lastModified": str(stat.st_mtime),
            }
        ]
    )

    monkeypatch.setattr(incremental, "_file_hash", lambda _path: "stored-hash")

    changeset = incremental.compute_changeset(store, tmp_path)

    assert changeset["modified"] == []
    assert changeset["unchanged"] == 1


def test_direct_dependents_returns_importers() -> None:
    store = _FileStore([{"src.path": "consumer.py"}, {"src.path": "other.py"}])

    assert incremental.direct_dependents(store, {"provider.py"}) == {"consumer.py", "other.py"}
