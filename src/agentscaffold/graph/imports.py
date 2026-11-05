"""Phase 3a: Import resolution processor.

Resolves import statements to target files and creates IMPORTS edges.
Supports Python and TypeScript/JavaScript import patterns.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from agentscaffold.graph.query_compat import ql
from agentscaffold.graph.symbol_table import SymbolTable
from agentscaffold.paths import resolve_node_path

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)


def _is_file(root: Path, rel: str) -> bool:
    path = resolve_node_path(root, rel)
    return path is not None and path.is_file()


try:
    import tree_sitter as ts  # noqa: F401
except ImportError:
    pass

# Pre-compiled patterns for Python import extraction
# Three patterns to handle: single-line from-import, multi-line parenthesized, direct import
_PY_FROM_PAREN_RE = re.compile(
    r"^\s*from\s+([\w.]+)\s+import\s+\(([^)]+)\)",
    re.MULTILINE | re.DOTALL,
)
_PY_FROM_INLINE_RE = re.compile(
    r"^\s*from\s+([\w.]+)\s+import\s+([^\n(]+)",
    re.MULTILINE,
)
_PY_DIRECT_IMPORT_RE = re.compile(
    r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)",
    re.MULTILINE,
)


def process_imports(
    store: GraphBackend,
    root: Path,
    symbol_table: SymbolTable,
    file_paths: set[str] | None = None,
    *,
    prefixes: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Resolve imports and create IMPORTS edges.

    ``prefixes`` maps monorepo module prefixes to directories under *root*
    (Plan 278). Both the full and the incremental path must pass the same
    mapping: the incremental path deletes a file's edges before re-resolving.

    Returns summary with resolved/unresolved counts.
    """
    file_rows = ql(
        store,
        sql='SELECT id AS "f.id", path AS "f.path", language AS "f.language" FROM File',
    )

    resolved = 0
    unresolved = 0

    file_id_map: dict[str, str] = {}
    scope = set(file_paths) if file_paths is not None else None
    scoped_file_ids: list[str] = []
    for row in file_rows:
        file_id_map[row["f.path"]] = row["f.id"]
        if scope is None or row["f.path"] in scope:
            scoped_file_ids.append(row["f.id"])

    if scope is not None:
        _clear_import_edges(store, scoped_file_ids)

    for row in file_rows:
        file_id = row["f.id"]
        file_path = row["f.path"]
        language = row["f.language"]

        if scope is not None and file_path not in scope:
            continue

        full_path = resolve_node_path(root, file_path)
        if full_path is None:
            continue

        try:
            source = full_path.read_text(errors="replace")
        except (OSError, PermissionError):
            continue

        if language == "python":
            r, u = _resolve_python_imports(
                store,
                source,
                file_id,
                file_path,
                file_id_map,
                root,
                prefixes=prefixes,
            )
        elif language in ("typescript", "javascript"):
            r, u = _resolve_ts_imports(
                store,
                source,
                file_id,
                file_path,
                file_id_map,
                root,
            )
        else:
            continue

        resolved += r
        unresolved += u

    return {"resolved": resolved, "unresolved": unresolved}


def _clear_import_edges(store: GraphBackend, file_ids: list[str]) -> None:
    """Delete existing IMPORTS edges owned by *file_ids*."""
    if not file_ids:
        return
    ids_lit = ", ".join("'" + fid.replace("'", "''") + "'" for fid in file_ids)
    store.execute(f"DELETE FROM IMPORTS WHERE src IN ({ids_lit})")


def _resolve_python_imports(
    store: GraphBackend,
    source: str,
    file_id: str,
    file_path: str,
    file_id_map: dict[str, str],
    root: Path,
    *,
    prefixes: Mapping[str, str] | None = None,
) -> tuple[int, int]:
    """Resolve Python import statements.

    Handles three patterns:
    - from X import (A, B, C)  (multi-line parenthesized)
    - from X import A, B, C    (single-line)
    - import X, Y              (direct)
    """
    resolved = 0
    unresolved = 0
    seen_edges: set[tuple[str, str]] = set()

    def _resolve(module: str, names: str) -> None:
        nonlocal resolved, unresolved
        resolution = _resolve_python_module(module, file_path, root, prefixes=prefixes)
        if resolution and resolution[0] in file_id_map:
            target_path, strategy = resolution
            target_id = file_id_map[target_path]
            edge_key = (file_id, target_id)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                _create_import_edge(store, file_id, target_id, names, strategy)
            resolved += 1
        else:
            unresolved += 1

    # Multi-line parenthesized: from X import (\n  A,\n  B\n)
    for match in _PY_FROM_PAREN_RE.finditer(source):
        module = match.group(1)
        names_raw = match.group(2)
        names = ", ".join(n.strip() for n in names_raw.replace("\n", ",").split(",") if n.strip())
        _resolve(module, names)

    # Single-line: from X import A, B, C
    for match in _PY_FROM_INLINE_RE.finditer(source):
        module = match.group(1)
        names = match.group(2).strip().rstrip("\\")
        _resolve(module, names.strip())

    # Direct: import X, import X, Y
    for match in _PY_DIRECT_IMPORT_RE.finditer(source):
        for mod in match.group(1).split(","):
            mod = mod.strip()
            if mod:
                _resolve(mod, mod.split(".")[-1])

    return resolved, unresolved


def _python_module_to_path(
    module: str,
    source_file: str,
    root: Path,
    *,
    prefixes: Mapping[str, str] | None = None,
) -> str | None:
    """Convert a Python module path to a file path, or None when unresolved."""
    resolution = _resolve_python_module(module, source_file, root, prefixes=prefixes)
    return resolution[0] if resolution else None


def _resolve_python_module(
    module: str,
    source_file: str,
    root: Path,
    *,
    prefixes: Mapping[str, str] | None = None,
) -> tuple[str, str] | None:
    """Resolve a Python module to ``(path, strategy)``.

    Strategies, in order: ``direct`` (module.py), ``package`` (__init__.py),
    ``prefix`` (a monorepo module prefix stripped, Plan 278), ``source_relative``
    (from the importing file's directory), ``src_prefix`` (src/, lib/, libs/).
    Relative imports use ``relative`` alone.
    """
    # A relative import resolves within one package and nowhere else. Handled
    # first and returned unconditionally, because the strategies below are for
    # absolute module names: letting `.core` fall through to them matches a
    # top-level core.py belonging to nobody, which is a worse answer than no
    # answer for a tool that reports blast radius.
    if module.startswith("."):
        path = _relative_module_to_path(module, source_file, root)
        return (path, "relative") if path else None

    parts = module.split(".")

    # Strategy 1: direct file
    candidate = "/".join(parts) + ".py"
    if _is_file(root, candidate):
        return candidate, "direct"

    # Strategy 2: package __init__
    candidate = "/".join(parts) + "/__init__.py"
    if _is_file(root, candidate):
        return candidate, "package"

    # Strategy 2b: monorepo module prefix. After the exact-path strategies, so a
    # file that really sits at the dotted path keeps winning.
    if prefixes:
        path = _prefixed_module_to_path(module, root, prefixes)
        if path:
            return path, "prefix"

    # Strategy 3: relative from source file's directory
    source_dir = str(Path(source_file).parent)
    if source_dir != ".":
        relative_candidate = source_dir + "/" + "/".join(parts) + ".py"
        if _is_file(root, relative_candidate):
            return relative_candidate, "source_relative"

        relative_candidate = source_dir + "/" + "/".join(parts) + "/__init__.py"
        if _is_file(root, relative_candidate):
            return relative_candidate, "source_relative"

    # Strategy 4: strip common prefixes (src/, lib/, libs/)
    for prefix in ("src/", "lib/", "libs/"):
        candidate = prefix + "/".join(parts) + ".py"
        if _is_file(root, candidate):
            return candidate, "src_prefix"
        candidate = prefix + "/".join(parts) + "/__init__.py"
        if _is_file(root, candidate):
            return candidate, "src_prefix"

    return None


def _prefixed_module_to_path(module: str, root: Path, prefixes: Mapping[str, str]) -> str | None:
    """Strip the longest matching module prefix and probe its mapped directory.

    A prefix matches whole dotted segments only: ``company.team_x`` matches
    ``company.team_x.foo`` but not ``company.team_xx``. The module equal to a
    prefix is the root package of its directory.
    """
    for prefix in sorted(prefixes, key=len, reverse=True):
        if module == prefix:
            rest: list[str] = []
        elif module.startswith(prefix + "."):
            rest = module[len(prefix) + 1 :].split(".")
        else:
            continue

        directory = prefixes[prefix].strip("/")
        base = [] if directory in ("", ".") else [directory]
        candidates = (
            ["/".join([*base, "__init__.py"])]
            if not rest
            else ["/".join([*base, *rest]) + ".py", "/".join([*base, *rest, "__init__.py"])]
        )
        for candidate in candidates:
            if _is_file(root, candidate):
                return candidate
    return None


def _relative_module_to_path(
    module: str,
    source_file: str,
    root: Path,
) -> str | None:
    """Resolve a PEP 328 relative import against the importing file's package.

    The leading dots are a count, not punctuation to be stripped. One dot means
    the importing file's own package; each additional dot ascends one level. So
    ``..core`` from ``src/pkg/sub/mod.py`` is ``src/pkg/core.py`` -- discarding
    the dots instead would name ``src/pkg/sub/core.py``, a different file that
    may well exist.

    Resolution is confined to the directory the dots land on. A relative import
    naming a module that is not there is unresolved, never something similarly
    named elsewhere in the tree.
    """
    dot_count = len(module) - len(module.lstrip("."))
    remainder = module[dot_count:]

    # The package containing the importer. For a regular module that is its
    # directory; for __init__.py the directory *is* the module's own package,
    # so the same expression is right for both.
    base_parts = list(Path(source_file).parent.parts)
    if base_parts == ["."]:
        base_parts = []

    levels_up = dot_count - 1
    if levels_up > len(base_parts):
        # Ascending above the repository root. Nothing here can satisfy it.
        return None
    if levels_up:
        base_parts = base_parts[:-levels_up]

    parts = [part for part in remainder.split(".") if part]

    # `from . import name` carries no module after the dots; the dependency is
    # on the package itself.
    if not parts:
        candidate = "/".join([*base_parts, "__init__.py"])
        return candidate if _is_file(root, candidate) else None

    stem = "/".join([*base_parts, *parts])
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if _is_file(root, candidate):
            return candidate

    return None


def _resolve_ts_imports(
    store: GraphBackend,
    source: str,
    file_id: str,
    file_path: str,
    file_id_map: dict[str, str],
    root: Path,
) -> tuple[int, int]:
    """Resolve TypeScript/JavaScript import statements."""
    resolved = 0
    unresolved = 0

    import_re = re.compile(
        r"""(?:import|from)\s+['"]([^'"]+)['"]""" r"""|import\s+.*?\s+from\s+['"]([^'"]+)['"]""",
    )

    for match in import_re.finditer(source):
        specifier = match.group(1) or match.group(2)
        if not specifier:
            continue

        # Skip bare module specifiers (npm packages)
        if not specifier.startswith(".") and not specifier.startswith("/"):
            continue

        target_path = _ts_specifier_to_path(specifier, file_path, root)
        if target_path and target_path in file_id_map:
            target_id = file_id_map[target_path]
            _create_import_edge(store, file_id, target_id, specifier.split("/")[-1], "relative")
            resolved += 1
        else:
            unresolved += 1

    return resolved, unresolved


def _ts_specifier_to_path(
    specifier: str,
    source_file: str,
    root: Path,
) -> str | None:
    """Resolve a relative TS/JS import specifier to a file path."""
    source_dir = str(Path(source_file).parent)
    if source_dir == ".":
        base = specifier.lstrip("./")
    else:
        base = source_dir + "/" + specifier.lstrip("./")

    # Normalize .. paths
    base = str(Path(base))

    extensions = [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"]
    for ext in extensions:
        candidate = base + ext
        if _is_file(root, candidate):
            return candidate

    # Already has extension
    if _is_file(root, base):
        return base

    return None


def _create_import_edge(
    store: GraphBackend,
    from_id: str,
    to_id: str,
    imported_names: str,
    strategy: str,
) -> None:
    """Create an IMPORTS edge between two File nodes, recording how it resolved."""
    store.create_edge(
        "IMPORTS",
        "File",
        from_id,
        "File",
        to_id,
        {"importedNames": imported_names, "strategy": strategy},
    )
