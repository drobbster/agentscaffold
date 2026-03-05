"""Phase 3b: Call resolution processor.

Resolves call sites to target functions and creates CALLS edges with
confidence scoring.
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

# Simple call site extraction via regex (works without tree-sitter for basic cases)
_PY_CALL_RE = re.compile(
    r"(?:^|\s|=|\(|,)"  # preceding context
    r"((?:[a-zA-Z_]\w*\.)*[a-zA-Z_]\w*)"  # dotted name
    r"\s*\(",  # opening paren
    re.MULTILINE,
)

# Minimum confidence to create an edge
MIN_CONFIDENCE = 0.3


def process_calls(
    store: GraphStore,
    root: Path,
    symbol_table: SymbolTable,
) -> dict:
    """Resolve call sites and create CALLS edges.

    Returns summary with counts by confidence bucket.
    """
    file_rows = store.query(
        "MATCH (f:File) WHERE f.language IN ['python', 'typescript', 'javascript'] "
        "RETURN f.id, f.path, f.language"
    )

    total = 0
    high_conf = 0
    medium_conf = 0
    low_conf = 0

    # Build a map of file imports for type-aware resolution
    import_map = _build_import_map(store)

    for row in file_rows:
        file_id = row["f.id"]
        file_path = row["f.path"]

        full_path = root / file_path

        try:
            source = full_path.read_text(errors="replace")
        except (OSError, PermissionError):
            continue

        # Get functions defined in this file
        caller_funcs = store.query(
            "MATCH (f:File)-[:DEFINES_FUNCTION]->(fn:Function) "
            f"WHERE f.id = '{file_id}' RETURN fn.id, fn.name, fn.startLine, fn.endLine"
        )

        # Get the imported names for this file
        imported_symbols = import_map.get(file_path, {})

        for caller in caller_funcs:
            caller_id = caller["fn.id"]
            start_line = int(caller["fn.startLine"])
            end_line = int(caller["fn.endLine"])

            # Extract the function body lines
            lines = source.splitlines()
            body = "\n".join(lines[start_line - 1 : end_line])

            for match in _PY_CALL_RE.finditer(body):
                call_name = match.group(1)
                if not call_name or call_name in _PYTHON_BUILTINS:
                    continue

                resolution = _resolve_call(
                    call_name,
                    file_path,
                    imported_symbols,
                    symbol_table,
                )
                if resolution is None:
                    continue

                target_id, confidence, reason = resolution
                if confidence < MIN_CONFIDENCE:
                    continue

                store.create_edge(
                    "CALLS",
                    "Function",
                    caller_id,
                    "Function",
                    target_id,
                    {"confidence": confidence, "reason": reason},
                )
                total += 1
                if confidence >= 0.8:
                    high_conf += 1
                elif confidence >= 0.5:
                    medium_conf += 1
                else:
                    low_conf += 1

    return {
        "total": total,
        "high_confidence": high_conf,
        "medium_confidence": medium_conf,
        "low_confidence": low_conf,
    }


def _build_import_map(store: GraphStore) -> dict[str, dict[str, str]]:
    """Build a map of file_path -> {imported_name: source_file_path}."""
    import_edges = store.query(
        "MATCH (a:File)-[r:IMPORTS]->(b:File) RETURN a.path, b.path, r.importedNames"
    )
    result: dict[str, dict[str, str]] = {}
    for row in import_edges:
        source_path = row["a.path"]
        target_path = row["b.path"]
        names_str = row.get("r.importedNames", "")

        if source_path not in result:
            result[source_path] = {}

        if names_str and names_str != "*":
            for name in names_str.split(","):
                name = name.strip()
                if name:
                    result[source_path][name] = target_path
        else:
            # Star import or full module import
            module_name = Path(target_path).stem
            result[source_path][module_name] = target_path

    return result


def _resolve_call(
    call_name: str,
    caller_file: str,
    imported_symbols: dict[str, str],
    symbol_table: SymbolTable,
) -> tuple[str, float, str] | None:
    """Resolve a call site to a target function node.

    Returns (target_node_id, confidence, reason) or None.
    """
    parts = call_name.split(".")

    # Strategy 1: Direct imported name (e.g., "fetch_data()")
    if len(parts) == 1:
        name = parts[0]

        # Check if it was imported
        if name in imported_symbols:
            source_file = imported_symbols[name]
            entries = symbol_table.lookup_in_file(source_file)
            for entry in entries:
                if entry.name == name and entry.node_type == "function":
                    return (entry.node_id, 0.9, "direct_import")

        # Check same-file definitions
        same_file = symbol_table.lookup_in_file(caller_file)
        for entry in same_file:
            if entry.name == name and entry.node_type == "function":
                return (entry.node_id, 0.85, "same_file")

        # Fuzzy global lookup
        candidates = symbol_table.lookup_name(name)
        func_candidates = [c for c in candidates if c.node_type == "function"]
        if len(func_candidates) == 1:
            return (func_candidates[0].node_id, 0.5, "unique_global")

    # Strategy 2: Method call (e.g., "self.router.fetch()" or "DataRouter.fetch()")
    elif len(parts) >= 2:
        obj_name = parts[-2]
        method_name = parts[-1]

        # Check if the object was imported as a class
        if obj_name in imported_symbols:
            source_file = imported_symbols[obj_name]
            methods = symbol_table.lookup_class_method(obj_name, method_name)
            for method in methods:
                if method.file_path == source_file:
                    return (method.node_id, 0.85, "imported_class_method")

        # Fuzzy: look for any class with that method
        methods = symbol_table.lookup_class_method(obj_name, method_name)
        if len(methods) == 1:
            return (methods[0].node_id, 0.6, "unique_class_method")
        elif methods:
            return (methods[0].node_id, 0.4, "ambiguous_class_method")

    return None


_PYTHON_BUILTINS = frozenset(
    {
        "print",
        "len",
        "range",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "type",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "super",
        "property",
        "staticmethod",
        "classmethod",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "min",
        "max",
        "sum",
        "abs",
        "round",
        "any",
        "all",
        "next",
        "iter",
        "open",
        "id",
        "hash",
        "repr",
        "format",
        "input",
        "vars",
        "dir",
        "globals",
        "locals",
        "exec",
        "eval",
        "compile",
        "breakpoint",
        "exit",
        "quit",
        "help",
        "copyright",
        "credits",
        "license",
        "object",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
        "RuntimeError",
        "OSError",
        "FileNotFoundError",
        "ImportError",
        "StopIteration",
        "NotImplementedError",
        "SystemExit",
        "AssertionError",
        "NameError",
        "ZeroDivisionError",
    }
)
