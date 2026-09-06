"""Directory-pruning walk must not descend into ignored trees (Plan 267)."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.graph.incremental import compute_changeset
from agentscaffold.graph.structure import (
    DEFAULT_IGNORE,
    collect_ignore_patterns,
    scan_indexable_files,
    walk_indexable,
)


class _FileStore:
    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        del sql, params
        return []


def _tree_with_ignored_decoy(tmp_path: Path, decoy_files: int = 200) -> Path:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "foo.py").write_text("x = 1\n")
    (tmp_path / "module.py").write_text("y = 2\n")
    (tmp_path / "venv_utils").mkdir()
    (tmp_path / "venv_utils" / "ok.py").write_text("z = 3\n")
    venv = tmp_path / ".venv" / "lib" / "site-packages" / "pkg"
    venv.mkdir(parents=True)
    for i in range(decoy_files):
        (venv / f"decoy_{i}.py").write_text("ignored = True\n")
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    (tmp_path / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1\n")
    return tmp_path


def test_scan_does_not_visit_files_under_ignored_trees(tmp_path: Path) -> None:
    root = _tree_with_ignored_decoy(tmp_path)
    visited: list[str] = []
    files = scan_indexable_files(
        root,
        collect_ignore_patterns(root),
        on_visit=visited.append,
    )

    assert "module.py" in files
    assert "src/pkg/foo.py" in files
    assert "venv_utils/ok.py" in files
    assert not any(path.startswith(".venv/") for path in files)
    assert not any(path.startswith("node_modules/") for path in files)
    assert not any(path.startswith(".venv/") for path in visited)
    assert not any(path.startswith("node_modules/") for path in visited)


def test_walk_prunes_gitignore_and_graph_ignore(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("a = 1\n")
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "hidden.py").write_text("b = 2\n")
    (tmp_path / ".gitignore").write_text("secret/\n")

    class _Cfg:
        ignore = ["extra_drop"]

    (tmp_path / "extra_drop").mkdir()
    (tmp_path / "extra_drop" / "x.py").write_text("c = 3\n")

    visited: list[str] = []
    files = scan_indexable_files(
        tmp_path,
        collect_ignore_patterns(tmp_path, _Cfg()),
        on_visit=visited.append,
    )
    assert "keep.py" in files
    assert not any(path.startswith("secret/") for path in files)
    assert not any(path.startswith("extra_drop/") for path in files)
    assert not any(path.startswith("secret/") for path in visited)
    assert not any(path.startswith("extra_drop/") for path in visited)


def test_compute_changeset_uses_pruning_walk(tmp_path: Path) -> None:
    root = _tree_with_ignored_decoy(tmp_path)
    visited: list[str] = []
    walk_indexable(root, DEFAULT_IGNORE, on_visit=visited.append)
    cs = compute_changeset(_FileStore(), root)
    assert "module.py" in cs["added"]
    assert not any(path.startswith(".venv/") for path in cs["added"])
    assert not any(path.startswith(".venv/") for path in visited)
