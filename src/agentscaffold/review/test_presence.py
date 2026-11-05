"""Whether a source file has tests -- graph first, then disk.

Review tools used to query ``File`` rows whose path contains ``test`` and the
source stem. ``tests/`` is often not indexed, so a complete plan looked
untested. Disk fallback uses the call's project root (``default_start``), the
same root ``diff_plan_vs_code`` already uses.

A file also counts as tested when a test module imports it (B-283-1): through
``IMPORTS`` edges when the tests are indexed, and by parsing the imports of
test modules under ``tests/`` or ``test/`` when they are not.
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.active_root import default_start
from agentscaffold.graph.query_compat import ql, sql_escape
from agentscaffold.paths import resolve_node_path

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

_TEST_NAME_RE = re.compile(r"^test_.+|.+_test$|.+\.(test|spec)$|.+Tests?$")
_TEST_DIRS = ("tests", "test")


def source_stem(fpath: str) -> str:
    return Path(fpath).stem


def is_test_path(path: str) -> bool:
    """True for a test module by its file name, in any language.

    ``conftest.py`` and helper modules under ``tests/`` are not test modules.
    Rust integration tests are any ``.rs`` file under a ``tests`` directory.
    """
    p = Path(path)
    if p.suffix == ".rs" and "tests" in p.parts[:-1]:
        return True
    return bool(_TEST_NAME_RE.match(p.stem))


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


def graph_has_test_importer(store: GraphBackend, fpath: str) -> bool:
    """True if an indexed test module has an ``IMPORTS`` edge to *fpath*."""
    escaped = sql_escape(fpath)
    rows = ql(
        store,
        sql=(
            'SELECT t.a_path AS "a.path"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:File)-[r:IMPORTS]->(b:File)"
            f" WHERE b.path = '{escaped}'"
            " COLUMNS (a.path AS a_path)) t"
        ),
    )
    return any(is_test_path(str(r.get("a.path") or "")) for r in rows or [])


def module_name(root: Path, fpath: str) -> str | None:
    """Dotted Python module name of *fpath*, from the packages above it on disk.

    Walks up while the parent directory has an ``__init__.py``, so ``src/``
    layouts and ``@repo/`` paths resolve to the name a test would import.
    None for non-Python files and unresolvable ``@repo/`` paths.
    """
    if Path(fpath).suffix != ".py":
        return None
    target = resolve_node_path(Path(root), fpath)
    if target is None:
        return None
    parts = list(target.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    start = len(parts) - 1
    while start > 1 and (Path(*parts[:start]) / "__init__.py").is_file():
        start -= 1
    return ".".join(parts[start:]) or None


def _test_modules(search_roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for search in search_roots:
        found.extend(p for p in search.rglob("*.py") if p.is_file() and is_test_path(p.name))
    return sorted(found)


@lru_cache(maxsize=16)
def _parse_imports(key: tuple[tuple[str, int, int], ...]) -> frozenset[str]:
    names: set[str] = set()
    for path_str, _mtime, _size in key:
        try:
            tree = ast.parse(Path(path_str).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
                names.update(f"{node.module}.{a.name}" for a in node.names if a.name != "*")
    return frozenset(names)


def _imported_modules(search_roots: list[Path]) -> frozenset[str]:
    """Modules imported by the test modules, cached until a test file changes."""
    key: list[tuple[str, int, int]] = []
    for path in _test_modules(search_roots):
        try:
            st = path.stat()
        except OSError:
            continue
        key.append((str(path), st.st_mtime_ns, st.st_size))
    return _parse_imports(tuple(key))


def disk_has_test(fpath: str, root: Path | None = None) -> bool:
    base = Path(root) if root is not None else default_start()
    search_roots = [p for p in (base / d for d in _TEST_DIRS) if p.is_dir()]
    if not search_roots:
        return False
    pattern = f"test_{source_stem(fpath)}.py"
    for search in search_roots:
        for hit in search.rglob(pattern):
            if hit.is_file():
                return True
    module = module_name(base, fpath)
    return module is not None and module in _imported_modules(search_roots)


def source_has_tests(
    store: Any,
    fpath: str,
    root: Path | None = None,
) -> bool:
    """True if a ``test_<stem>.py`` exists or a test module imports *fpath*."""
    if graph_has_test(store, fpath):
        return True
    if graph_has_test_importer(store, fpath):
        return True
    return disk_has_test(fpath, root)
