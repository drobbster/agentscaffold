"""Whether a source file has tests -- graph first, then disk.

Review tools used to query ``File`` rows whose path contains ``test`` and the
source stem. ``tests/`` is often not indexed, so a complete plan looked
untested. Disk fallback uses the call's project root (``default_start``), the
same root ``diff_plan_vs_code`` already uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.active_root import default_start
from agentscaffold.graph.query_compat import ql, sql_escape

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend


def source_stem(fpath: str) -> str:
    return Path(fpath).stem


def graph_has_test(store: GraphBackend, fpath: str) -> bool:
    stem = sql_escape(source_stem(fpath))
    rows = ql(
        store,
        sql=(
            'SELECT path AS "f.path" FROM File'
            f" WHERE CONTAINS(path, 'test') AND CONTAINS(path, '{stem}') LIMIT 1"
        ),
    )
    return bool(rows)


def disk_has_test(fpath: str, root: Path | None = None) -> bool:
    base = Path(root) if root is not None else default_start()
    pattern = f"test_{source_stem(fpath)}.py"
    search_roots = [p for p in (base / "tests", base / "test") if p.is_dir()]
    if not search_roots:
        return False
    for search in search_roots:
        for hit in search.rglob(pattern):
            if hit.is_file():
                return True
    return False


def source_has_tests(
    store: Any,
    fpath: str,
    root: Path | None = None,
) -> bool:
    """True if the graph or the project disk has a ``test_<stem>.py``."""
    if graph_has_test(store, fpath):
        return True
    return disk_has_test(fpath, root)
