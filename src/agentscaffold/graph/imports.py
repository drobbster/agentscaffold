"""Phase 3a: Import resolution processor.

Resolves import statements to target files and creates IMPORTS edges.
Supports Python and TypeScript/JavaScript import patterns.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agentscaffold.graph.symbol_table import SymbolTable

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)

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
    store: GraphStore,
    root: Path,
    symbol_table: SymbolTable,
) -> dict:
    """Resolve imports and create IMPORTS edges.

    Returns summary with resolved/unresolved counts.
    """
    file_rows = store.query("MATCH (f:File) RETURN f.id, f.path, f.language")

    resolved = 0
    unresolved = 0

    file_id_map: dict[str, str] = {}
    for row in file_rows:
        file_id_map[row["f.path"]] = row["f.id"]

    for row in file_rows:
        file_id = row["f.id"]
        file_path = row["f.path"]
        language = row["f.language"]

        full_path = root / file_path

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


def _resolve_python_imports(
    store: GraphStore,
    source: str,
    file_id: str,
    file_path: str,
    file_id_map: dict[str, str],
    root: Path,
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

    def _resolve_from(module: str, names: str) -> None:
        nonlocal resolved, unresolved
        target_path = _python_module_to_path(module, file_path, root)
        if target_path and target_path in file_id_map:
            target_id = file_id_map[target_path]
            edge_key = (file_id, target_id)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                _create_import_edge(store, file_id, target_id, names.strip())
            resolved += 1
        else:
            unresolved += 1

    # Multi-line parenthesized: from X import (\n  A,\n  B\n)
    for match in _PY_FROM_PAREN_RE.finditer(source):
        module = match.group(1)
        names_raw = match.group(2)
        names = ", ".join(n.strip() for n in names_raw.replace("\n", ",").split(",") if n.strip())
        _resolve_from(module, names)

    # Single-line: from X import A, B, C
    for match in _PY_FROM_INLINE_RE.finditer(source):
        module = match.group(1)
        names = match.group(2).strip().rstrip("\\")
        _resolve_from(module, names)

    # Direct: import X, import X, Y
    for match in _PY_DIRECT_IMPORT_RE.finditer(source):
        for mod in match.group(1).split(","):
            mod = mod.strip()
            if not mod:
                continue
            target_path = _python_module_to_path(mod, file_path, root)
            if target_path and target_path in file_id_map:
                target_id = file_id_map[target_path]
                edge_key = (file_id, target_id)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    _create_import_edge(store, file_id, target_id, mod.split(".")[-1])
                resolved += 1
            else:
                unresolved += 1

    return resolved, unresolved


def _python_module_to_path(
    module: str,
    source_file: str,
    root: Path,
) -> str | None:
    """Convert a Python module path to a file path.

    Tries multiple resolution strategies:
    1. Direct file match (module.py)
    2. Package init (__init__.py)
    3. Relative import resolution
    """
    parts = module.split(".")

    # Strategy 1: direct file
    candidate = "/".join(parts) + ".py"
    if (root / candidate).is_file():
        return candidate

    # Strategy 2: package __init__
    candidate = "/".join(parts) + "/__init__.py"
    if (root / candidate).is_file():
        return "/".join(parts) + "/__init__.py"

    # Strategy 3: relative from source file's directory
    source_dir = str(Path(source_file).parent)
    if source_dir != ".":
        relative_candidate = source_dir + "/" + "/".join(parts) + ".py"
        if (root / relative_candidate).is_file():
            return relative_candidate

        relative_candidate = source_dir + "/" + "/".join(parts) + "/__init__.py"
        if (root / relative_candidate).is_file():
            return relative_candidate

    # Strategy 4: strip common prefixes (src/, lib/, libs/)
    for prefix in ("src/", "lib/", "libs/"):
        candidate = prefix + "/".join(parts) + ".py"
        if (root / candidate).is_file():
            return candidate
        candidate = prefix + "/".join(parts) + "/__init__.py"
        if (root / candidate).is_file():
            return candidate

    return None


def _resolve_ts_imports(
    store: GraphStore,
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
            _create_import_edge(store, file_id, target_id, specifier.split("/")[-1])
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
        if (root / candidate).is_file():
            return candidate

    # Already has extension
    if (root / base).is_file():
        return base

    return None


def _create_import_edge(
    store: GraphStore,
    from_id: str,
    to_id: str,
    imported_names: str,
) -> None:
    """Create an IMPORTS edge between two File nodes."""
    store.create_edge(
        "IMPORTS",
        "File",
        from_id,
        "File",
        to_id,
        {"importedNames": imported_names},
    )
