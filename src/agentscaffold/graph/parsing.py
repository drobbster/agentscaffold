"""Phase 2: Tree-sitter parsing processor.

Parses source files to extract function, class, method, and interface
definitions. Populates the symbol table for later resolution.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.graph.queries import get_queries, supported_languages
from agentscaffold.graph.symbol_table import SymbolEntry, SymbolTable

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore

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
    "c": "language_c",
    "cpp": "language_cpp",
}


def _load_language(language: str) -> Language | None:
    """Load a tree-sitter Language object for the given language."""
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
    store: GraphStore,
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
    file_rows = store.query("MATCH (f:File) RETURN f.id, f.path, f.language")

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
    store: GraphStore,
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
    store: GraphStore,
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
        count += 1

    return count


def _extract_methods(
    store: GraphStore,
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
    store: GraphStore,
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
