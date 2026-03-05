"""Phase 2: Tree-sitter parsing processor.

Parses source files to extract function, class, method, and interface
definitions. Populates the symbol table for later resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.graph.queries import get_queries, supported_languages
from agentscaffold.graph.symbol_table import SymbolEntry, SymbolTable

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)

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

    for row in file_rows:
        file_id = row["f.id"]
        file_path = row["f.path"]
        language = row["f.language"]

        if language not in supported_languages():
            continue

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
    captures = _query_captures(lang, query_str, tree.root_node)
    if captures is None:
        return 0

    count = 0
    names = captures.get("name", [])
    params = captures.get("params", [])
    defs = captures.get("definition", [])

    for i, name_node in enumerate(names):
        name = _extract_text(name_node, source)
        start_line = name_node.start_point[0] + 1
        def_node = defs[i] if i < len(defs) else name_node
        end_line = def_node.end_point[0] + 1
        params_node = params[i] if i < len(params) else None
        param_count = _count_params(params_node)

        is_exported = not name.startswith("_") if language == "python" else True
        if language == "python":
            signature = _build_signature_python(name, params_node, source)
        else:
            signature = name

        func_id = f"func::{file_path}::{name}::{start_line}"

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
    captures = _query_captures(lang, query_str, tree.root_node)
    if captures is None:
        return 0

    count = 0
    names = captures.get("name", [])
    defs = captures.get("definition", [])

    for i, name_node in enumerate(names):
        name = _extract_text(name_node, source)
        start_line = name_node.start_point[0] + 1
        def_node = defs[i] if i < len(defs) else name_node
        end_line = def_node.end_point[0] + 1
        is_exported = not name.startswith("_") if language == "python" else True

        class_id = f"class::{file_path}::{name}"

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
    """Extract method definitions within classes."""
    captures = _query_captures(lang, query_str, tree.root_node)
    if captures is None:
        return 0

    count = 0
    class_names = captures.get("class_name", [])
    method_names = captures.get("method_name", [])
    params = captures.get("params", [])
    methods = captures.get("method", [])

    for i, method_name_node in enumerate(method_names):
        method_name = _extract_text(method_name_node, source)
        class_name = _extract_text(class_names[i], source) if i < len(class_names) else "Unknown"
        start_line = method_name_node.start_point[0] + 1
        method_node = methods[i] if i < len(methods) else method_name_node
        end_line = method_node.end_point[0] + 1
        params_node = params[i] if i < len(params) else None

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

        class_id = f"class::{file_path}::{class_name}"
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
    captures = _query_captures(lang, query_str, tree.root_node)
    if captures is None:
        return 0

    count = 0
    names = captures.get("name", [])
    defs = captures.get("definition", [])

    for i, name_node in enumerate(names):
        name = _extract_text(name_node, source)
        start_line = name_node.start_point[0] + 1
        def_node = defs[i] if i < len(defs) else name_node
        end_line = def_node.end_point[0] + 1

        iface_id = f"interface::{file_path}::{name}"

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
