"""Phase 2: Tree-sitter parsing processor.

Parses source files to extract function, class, method, and interface
definitions. Populates the symbol table for later resolution.
"""

from __future__ import annotations

import logging
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.graph.queries import get_queries, supported_languages
from agentscaffold.graph.query_compat import ql
from agentscaffold.graph.symbol_table import SymbolEntry, SymbolTable

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

_PROGRESS_INTERVAL = 50

try:
    import tree_sitter as ts
    from tree_sitter import Language, Parser, Query, QueryCursor
except ImportError:
    ts = None  # type: ignore[assignment]

_GRAMMAR_MODULES: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "java": "tree_sitter_java",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
}


_LANGUAGE_FUNC_MAP: dict[str, str] = {
    "typescript": "language_typescript",
}


@cache
def _load_language(language: str) -> Language | None:
    """Load a tree-sitter Language object for the given language.

    Cached per language: the grammar is immutable, so the Language object is
    built once and reused across every file instead of being reconstructed on
    each call (previously once per parsed file).
    """
    if ts is None:
        return None

    mod_name = _GRAMMAR_MODULES.get(language)
    if mod_name is None:
        return None

    try:
        import importlib

        mod = importlib.import_module(mod_name)
        func_name = _LANGUAGE_FUNC_MAP.get(language, "language")
        lang_func = getattr(mod, func_name, None)
        if lang_func is None:
            logger.warning("No %s() in %s", func_name, mod_name)
            return None
        return Language(lang_func())
    except Exception as exc:
        logger.warning("Failed to load tree-sitter grammar for %s: %s", language, exc)
        return None


def _get_parser(language: str) -> Parser | None:
    """Create a tree-sitter parser for the given language."""
    lang = _load_language(language)
    if lang is None:
        return None
    return Parser(lang)


def _get_ts_language(language: str) -> Language | None:
    """Get the tree-sitter Language object for query compilation."""
    return _load_language(language)


def _file_to_module(file_path: str) -> str:
    """Convert a file path to a Python-style module path."""
    result = file_path.replace("/", ".")
    for suffix in (".py", ".ts", ".tsx", ".js", ".jsx"):
        result = result.removesuffix(suffix)
    return result


def _extract_text(node: Any, source: bytes) -> str:
    """Extract the text content of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _is_exported_python(node: Any, source: bytes) -> bool:
    """Check if a Python definition is likely exported (not prefixed with _)."""
    for child in node.children:
        if child.type == "identifier":
            name = _extract_text(child, source)
            return not name.startswith("_")
    return True


def _count_params(params_node: Any) -> int:
    """Count the number of parameters in a parameter list node."""
    if params_node is None:
        return 0
    count = 0
    for child in params_node.children:
        if child.type in (
            "identifier",
            "typed_parameter",
            "default_parameter",
            "typed_default_parameter",
            "list_splat_pattern",
            "dictionary_splat_pattern",
            "required_parameter",
            "optional_parameter",
        ):
            count += 1
    return count


def _build_signature_python(name: str, params_node: Any, source: bytes) -> str:
    """Build a Python function signature string."""
    if params_node is None:
        return f"{name}()"
    params_text = _extract_text(params_node, source)
    return f"{name}{params_text}"


def _query_captures(lang: Any, query_str: str, root_node: Any) -> dict[str, list[Any]] | None:
    """Run a tree-sitter query via QueryCursor (v0.25+ API).

    Returns a dict mapping capture names to lists of Nodes.
    Returns None if the query fails to compile.
    """
    if ts is None:
        return None
    try:
        q = Query(lang, query_str)
        cursor = QueryCursor(q)
        return cursor.captures(root_node)
    except Exception as exc:
        logger.debug("Tree-sitter query failed: %s", exc)
        return None


def _query_matches(lang: Any, query_str: str, root_node: Any) -> list[dict[str, Any]] | None:
    """Run a tree-sitter query and return properly paired matches.

    Returns a list of dicts, one per match. Each dict maps capture names
    to the first captured Node for that match. This avoids the alignment
    issues of captures() where parallel lists can become misaligned.
    """
    if ts is None:
        return None
    try:
        q = Query(lang, query_str)
        cursor = QueryCursor(q)
        results = []
        for _pattern_idx, captures in cursor.matches(root_node):
            match: dict[str, Any] = {}
            for name, nodes in captures.items():
                if nodes:
                    match[name] = nodes[0]
            if match:
                results.append(match)
        return results
    except Exception as exc:
        logger.debug("Tree-sitter query failed: %s", exc)
        return None


def process_parsing(
    store: GraphBackend,
    root: Path,
    symbol_table: SymbolTable,
    *,
    file_paths: set[str] | None = None,
) -> dict:
    """Parse indexed files and extract definitions.

    Args:
        file_paths: If provided, only parse these relative paths.
                    If None, parse all files in the graph.

    Returns a summary dict with counts.
    """
    file_rows = ql(
        store,
        sql='SELECT id AS "f.id", path AS "f.path", language AS "f.language" FROM File',
    )

    if file_paths is not None:
        file_rows = [r for r in file_rows if r["f.path"] in file_paths]

    func_count = 0
    class_count = 0
    method_count = 0
    interface_count = 0
    files_parsed = 0
    files_skipped = 0

    parsers: dict[str, Any] = {}
    parseable_rows = [r for r in file_rows if r["f.language"] in supported_languages()]
    total_files = len(parseable_rows)

    for idx, row in enumerate(parseable_rows):
        file_id = row["f.id"]
        file_path = row["f.path"]
        language = row["f.language"]

        if total_files > _PROGRESS_INTERVAL and (idx + 1) % _PROGRESS_INTERVAL == 0:
            pct = (idx + 1) / total_files * 100
            sys.stdout.write(f"\r  parsing {idx + 1}/{total_files} ({pct:.0f}%)")
            sys.stdout.flush()

        if language not in parsers:
            parser = _get_parser(language)
            if parser is None:
                continue
            parsers[language] = parser

        parser = parsers[language]
        full_path = root / file_path

        try:
            source = full_path.read_bytes()
        except (OSError, PermissionError) as exc:
            logger.warning("Cannot read %s: %s", file_path, exc)
            store.add_parsing_warning(
                f"pw::{file_path}::read",
                file_path,
                "parsing",
                f"Cannot read file: {exc}",
            )
            files_skipped += 1
            continue

        try:
            tree = parser.parse(source)
        except Exception as exc:
            logger.warning("Parse error in %s: %s", file_path, exc)
            store.add_parsing_warning(
                f"pw::{file_path}::parse",
                file_path,
                "parsing",
                f"Tree-sitter parse error: {exc}",
            )
            files_skipped += 1
            continue

        files_parsed += 1
        lang_obj = _get_ts_language(language)
        if lang_obj is None:
            continue

        queries = get_queries(language)
        if queries is None:
            continue

        # Extract functions
        if "functions" in queries:
            fc = _extract_functions(
                store,
                lang_obj,
                queries["functions"],
                tree,
                source,
                file_id,
                file_path,
                language,
                symbol_table,
                root,
            )
            func_count += fc

        # Extract classes
        if "classes" in queries:
            cc = _extract_classes(
                store,
                lang_obj,
                queries["classes"],
                tree,
                source,
                file_id,
                file_path,
                language,
                symbol_table,
                root,
            )
            class_count += cc

        # Extract methods
        if "methods" in queries:
            mc = _extract_methods(
                store,
                lang_obj,
                queries["methods"],
                tree,
                source,
                file_id,
                file_path,
                language,
                symbol_table,
                root,
            )
            method_count += mc

        # Extract interfaces (TS only)
        if "interfaces" in queries:
            ic = _extract_interfaces(
                store,
                lang_obj,
                queries["interfaces"],
                tree,
                source,
                file_id,
                file_path,
                symbol_table,
                root,
            )
            interface_count += ic

    if total_files > _PROGRESS_INTERVAL:
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()

    return {
        "files_parsed": files_parsed,
        "files_skipped": files_skipped,
        "functions": func_count,
        "classes": class_count,
        "methods": method_count,
        "interfaces": interface_count,
    }


def _extract_functions(
    store: GraphBackend,
    lang: Any,
    query_str: str,
    tree: Any,
    source: bytes,
    file_id: str,
    file_path: str,
    language: str,
    symbol_table: SymbolTable,
    root: Path,
) -> int:
    """Extract function definitions and create nodes."""
    matches = _query_matches(lang, query_str, tree.root_node)
    if not matches:
        return 0

    count = 0
    seen: set[str] = set()
    for match in matches:
        name_node = match.get("name")
        if name_node is None:
            continue

        name = _extract_text(name_node, source)
        start_line = name_node.start_point[0] + 1
        func_id = f"func::{file_path}::{name}::{start_line}"

        if func_id in seen:
            continue
        seen.add(func_id)

        def_node = match.get("definition", name_node)
        end_line = def_node.end_point[0] + 1
        params_node = match.get("params")
        param_count = _count_params(params_node)

        is_exported = not name.startswith("_") if language == "python" else True
        if language == "python":
            signature = _build_signature_python(name, params_node, source)
        else:
            signature = name

        store.create_node(
            "Function",
            {
                "id": func_id,
                "name": name,
                "filePath": file_path,
                "startLine": start_line,
                "endLine": end_line,
                "isExported": is_exported,
                "paramCount": param_count,
                "signature": signature,
            },
        )
        store.create_edge("DEFINES_FUNCTION", "File", file_id, "Function", func_id)

        module_path = _file_to_module(file_path)
        qualified = f"{module_path}.{name}"

        symbol_table.add(
            SymbolEntry(
                name=name,
                qualified_name=qualified,
                file_path=file_path,
                file_id=file_id,
                node_id=func_id,
                node_type="function",
                is_exported=is_exported,
                start_line=start_line,
            )
        )
        count += 1

    return count


def _extract_classes(
    store: GraphBackend,
    lang: Any,
    query_str: str,
    tree: Any,
    source: bytes,
    file_id: str,
    file_path: str,
    language: str,
    symbol_table: SymbolTable,
    root: Path,
) -> int:
    """Extract class definitions and create nodes."""
    matches = _query_matches(lang, query_str, tree.root_node)
    if not matches:
        return 0

    count = 0
    seen: set[str] = set()
    for match in matches:
        name_node = match.get("name")
        if name_node is None:
            continue

        name = _extract_text(name_node, source)
        start_line = name_node.start_point[0] + 1
        class_id = f"class::{file_path}::{name}::{start_line}"

        if class_id in seen:
            continue
        seen.add(class_id)

        def_node = match.get("definition", name_node)
        end_line = def_node.end_point[0] + 1
        is_exported = not name.startswith("_") if language == "python" else True

        store.create_node(
            "Class",
            {
                "id": class_id,
                "name": name,
                "filePath": file_path,
                "startLine": start_line,
                "endLine": end_line,
                "isExported": is_exported,
            },
        )
        store.create_edge("DEFINES_CLASS", "File", file_id, "Class", class_id)

        module_path = _file_to_module(file_path)
        qualified = f"{module_path}.{name}"

        symbol_table.add(
            SymbolEntry(
                name=name,
                qualified_name=qualified,
                file_path=file_path,
                file_id=file_id,
                node_id=class_id,
                node_type="class",
                is_exported=is_exported,
                start_line=start_line,
            )
        )
        if language == "python":
            for base_name in _extract_base_names(match.get("bases"), source):
                store.create_edge(
                    "EXTENDS",
                    "Class",
                    class_id,
                    "Class",
                    f"external::{base_name}",
                    {"resolved": False, "baseName": base_name},
                )
        count += 1

    return count


_SKIP_BASE_CHILD_TYPES = frozenset(
    {
        "(",
        ")",
        ",",
        "comment",
        "keyword_argument",
    }
)


def _extract_base_names(bases_node: Any, source: bytes) -> list[str]:
    """Return textual base names from a tree-sitter ``argument_list``.

    Skips punctuation and ``keyword_argument`` children (``metaclass=...``).
    Subscripts (``Generic[T]``) and starred bases are kept as text so they can
    be recorded unresolved rather than dropped or mistaken for a Class name.
    """
    if bases_node is None:
        return []
    names: list[str] = []
    for child in bases_node.children:
        if child.type in _SKIP_BASE_CHILD_TYPES:
            continue
        text = _extract_text(child, source).strip()
        if text:
            names.append(text)
    return names


def _import_alias_pair(raw: str) -> tuple[str, str]:
    """Return ``(local_name, exported_name)`` for an importedNames token."""
    parts = raw.split()
    if len(parts) >= 3 and parts[-2] == "as":
        return parts[-1], parts[0]
    return raw, raw


def _extends_import_map(
    store: GraphBackend,
) -> dict[str, dict[str, tuple[str, str]]]:
    """Map ``file -> local_name -> (source_file, exported_name)``."""
    from agentscaffold.graph.calls import _build_import_map

    raw = _build_import_map(store)
    result: dict[str, dict[str, tuple[str, str]]] = {}
    for file_path, names in raw.items():
        local: dict[str, tuple[str, str]] = {}
        for imported, target in names.items():
            local_name, exported = _import_alias_pair(imported)
            local[local_name] = (target, exported)
        result[file_path] = local
    return result


def _resolve_base(
    base_name: str,
    subclass_file: str,
    imported_symbols: dict[str, tuple[str, str]],
    symbol_table: SymbolTable,
) -> str | None:
    """Resolve a base name to an in-repo Class node id, or None.

    Order matches ``calls._resolve_call``: imported name, same-file, then a
    unique global class. Subscript heads (``Generic[T]``) skip the unique
    fallback so ``Generic`` is not attached to a coincidental in-repo class.
    """
    if base_name.startswith("*"):
        return None
    has_subscript = "[" in base_name
    head = base_name.split("[", 1)[0]

    if "." in head:
        prefix, name = head.rsplit(".", 1)
        if prefix in imported_symbols:
            source_file, _exported = imported_symbols[prefix]
            for entry in symbol_table.lookup_in_file(source_file):
                if entry.name == name and entry.node_type == "class":
                    return entry.node_id
        qualified = symbol_table.lookup_qualified(head)
        if qualified is not None and qualified.node_type == "class":
            return qualified.node_id
        return None

    if head in imported_symbols:
        source_file, exported = imported_symbols[head]
        for entry in symbol_table.lookup_in_file(source_file):
            if entry.name == exported and entry.node_type == "class":
                return entry.node_id

    for entry in symbol_table.lookup_in_file(subclass_file):
        if entry.name == head and entry.node_type == "class":
            return entry.node_id

    if has_subscript:
        return None

    candidates = [entry for entry in symbol_table.lookup_name(head) if entry.node_type == "class"]
    if len(candidates) == 1:
        return candidates[0].node_id
    return None


def process_extends(store: GraphBackend, symbol_table: SymbolTable) -> dict[str, int]:
    """Upgrade unresolved EXTENDS edges whose bases resolve to in-repo classes.

    Parsing emits every Python base as ``resolved=false`` with a synthetic
    ``external::<name>`` destination. This pass runs after imports so the
    import map exists. Unresolved edges are left in place.
    """
    rows = store.query(
        "SELECT e.src AS src, e.dst AS dst, e.baseName AS baseName, "
        "c.filePath AS filePath FROM EXTENDS e "
        "INNER JOIN Class c ON c.id = e.src "
        "WHERE e.resolved = false OR e.resolved IS NULL"
    )
    import_map = _extends_import_map(store)
    upgraded = 0
    leftover = 0
    for row in rows:
        base_name = row.get("baseName") or ""
        subclass_file = row.get("filePath") or ""
        imported = import_map.get(subclass_file, {})
        target = _resolve_base(base_name, subclass_file, imported, symbol_table)
        if target is None:
            leftover += 1
            continue
        src = row["src"]
        old_dst = row["dst"]
        # UPDATE rather than create_edge: INSERT ... SELECT ? drops Python True
        # on BOOLEAN columns (the bind keeps the DEFAULT false).
        store.execute(
            "UPDATE EXTENDS SET dst = ?, resolved = true WHERE src = ? AND dst = ?",
            {"dst": target, "src": src, "old_dst": old_dst},
        )
        upgraded += 1
    # Durable marker is dst pointing at a Class id. The BOOLEAN can reset on
    # connection close (DuckPGQ reload); CHECKPOINT keeps src/dst, not always
    # the flag. Callers should treat ``dst LIKE '%class::%'`` as resolved.
    try:
        store.execute("CHECKPOINT")
    except Exception:
        pass
    return {"resolved": upgraded, "unresolved": leftover}


def _extract_methods(
    store: GraphBackend,
    lang: Any,
    query_str: str,
    tree: Any,
    source: bytes,
    file_id: str,
    file_path: str,
    language: str,
    symbol_table: SymbolTable,
    root: Path,
) -> int:
    """Extract method definitions within classes.

    Uses a two-pass approach: first captures class ranges, then captures all
    function definitions and assigns each to its enclosing class by line range.
    This avoids tree-sitter's sibling capture limitation where only the first
    function_definition per block is returned in nested patterns.
    """
    # Pass 1: get class ranges using matches() for proper pairing
    class_matches = _query_matches(lang, query_str, tree.root_node)
    if not class_matches:
        return 0

    # (name, name_start_line_1indexed, body_start_0indexed, body_end_0indexed)
    class_ranges: list[tuple[str, int, int, int]] = []
    for match in class_matches:
        cn_node = match.get("class_name")
        cd_node = match.get("class_def", cn_node)
        if cn_node is None:
            continue
        cname = _extract_text(cn_node, source)
        name_line = cn_node.start_point[0] + 1
        class_ranges.append((cname, name_line, cd_node.start_point[0], cd_node.end_point[0]))

    if not class_ranges:
        return 0

    # Pass 2: get all function definitions using matches()
    from agentscaffold.graph.queries import INNER_METHOD_QUERIES

    inner_query = INNER_METHOD_QUERIES.get(language)
    if inner_query is None:
        return 0
    func_matches = _query_matches(lang, inner_query, tree.root_node)
    if not func_matches:
        return 0

    count = 0
    for match in func_matches:
        mn_node = match.get("method_name")
        if mn_node is None:
            continue

        method_name = _extract_text(mn_node, source)
        start_line = mn_node.start_point[0] + 1
        m_node = match.get("method", mn_node)
        end_line = m_node.end_point[0] + 1
        params_node = match.get("params")

        # Assign to the innermost enclosing class by line range
        func_line = mn_node.start_point[0]
        class_name = "Unknown"
        class_start_line = 0
        for cname, cname_line, cstart, cend in class_ranges:
            if cstart <= func_line <= cend:
                class_name = cname
                class_start_line = cname_line

        if class_name == "Unknown":
            continue

        is_exported = not method_name.startswith("_") if language == "python" else True
        if language == "python":
            signature = _build_signature_python(method_name, params_node, source)
        else:
            signature = method_name

        method_id = f"method::{file_path}::{class_name}.{method_name}::{start_line}"

        store.create_node(
            "Method",
            {
                "id": method_id,
                "name": method_name,
                "className": class_name,
                "filePath": file_path,
                "startLine": start_line,
                "endLine": end_line,
                "isExported": is_exported,
                "signature": signature,
            },
        )

        class_id = f"class::{file_path}::{class_name}::{class_start_line}"
        store.create_edge("HAS_METHOD", "Class", class_id, "Method", method_id)

        module_path = _file_to_module(file_path)
        qualified = f"{module_path}.{class_name}.{method_name}"

        symbol_table.add(
            SymbolEntry(
                name=method_name,
                qualified_name=qualified,
                file_path=file_path,
                file_id=file_id,
                node_id=method_id,
                node_type="method",
                is_exported=is_exported,
                class_name=class_name,
                start_line=start_line,
            )
        )
        count += 1

    return count


def _extract_interfaces(
    store: GraphBackend,
    lang: Any,
    query_str: str,
    tree: Any,
    source: bytes,
    file_id: str,
    file_path: str,
    symbol_table: SymbolTable,
    root: Path,
) -> int:
    """Extract TypeScript interface definitions."""
    matches = _query_matches(lang, query_str, tree.root_node)
    if not matches:
        return 0

    count = 0
    seen: set[str] = set()
    for match in matches:
        name_node = match.get("name")
        if name_node is None:
            continue

        name = _extract_text(name_node, source)
        start_line = name_node.start_point[0] + 1
        iface_id = f"interface::{file_path}::{name}::{start_line}"

        if iface_id in seen:
            continue
        seen.add(iface_id)

        def_node = match.get("definition", name_node)
        end_line = def_node.end_point[0] + 1

        store.create_node(
            "Interface",
            {
                "id": iface_id,
                "name": name,
                "filePath": file_path,
                "startLine": start_line,
                "endLine": end_line,
            },
        )
        store.create_edge("DEFINES_INTERFACE", "File", file_id, "Interface", iface_id)

        module_path = _file_to_module(file_path)
        qualified = f"{module_path}.{name}"

        symbol_table.add(
            SymbolEntry(
                name=name,
                qualified_name=qualified,
                file_path=file_path,
                file_id=file_id,
                node_id=iface_id,
                node_type="interface",
                is_exported=True,
                start_line=start_line,
            )
        )
        count += 1

    return count
