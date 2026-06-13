"""Phase 3b: Call resolution processor.

Resolves call sites to target functions and creates CALLS edges with
confidence scoring.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agentscaffold.graph.query_compat import ql
from agentscaffold.graph.symbol_table import SymbolTable

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

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

# Resolution reasons that point at a top-level Function (Strategy 1 in
# _resolve_call). METHOD_CALLS edges require a Function destination per the
# schema (Method -> Function), so method callers only emit edges for these.
_FUNCTION_TARGET_REASONS = frozenset({"direct_import", "same_file", "unique_global"})


def process_calls(
    store: GraphBackend,
    root: Path,
    symbol_table: SymbolTable,
) -> dict:
    """Resolve call sites and create CALLS / METHOD_CALLS edges.

    Function callers produce ``CALLS`` edges (Function -> Function); method
    callers produce ``METHOD_CALLS`` edges (Method -> Function). Returns a
    summary with counts by confidence bucket plus a ``method_calls`` count.
    """
    file_rows = ql(
        store,
        sql=(
            'SELECT id AS "f.id", path AS "f.path", language AS "f.language" FROM File '
            "WHERE language IN ('python', 'typescript', 'javascript')"
        ),
    )

    counters = {"total": 0, "high": 0, "medium": 0, "low": 0, "method_calls": 0}

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

        lines = source.splitlines()
        imported_symbols = import_map.get(file_path, {})

        # Functions defined in this file -> CALLS edges
        caller_funcs = ql(
            store,
            sql=(
                'SELECT t.fn_id AS "fn.id", t.fn_name AS "fn.name",'
                ' t.fn_sl AS "fn.startLine", t.fn_el AS "fn.endLine"'
                " FROM GRAPH_TABLE(agentscaffold_graph"
                "   MATCH (f:File)-[e:DEFINES_FUNCTION]->(fn:Function)"
                f"   WHERE f.id = '{file_id}'"
                "   COLUMNS (fn.id AS fn_id, fn.name AS fn_name,"
                "            fn.startLine AS fn_sl, fn.endLine AS fn_el)"
                " ) t"
            ),
        )
        for caller in caller_funcs:
            _process_caller_body(
                store,
                lines,
                caller["fn.id"],
                int(caller["fn.startLine"]),
                int(caller["fn.endLine"]),
                file_path,
                imported_symbols,
                symbol_table,
                edge_table="CALLS",
                src_table="Function",
                counters=counters,
            )

        # Methods defined in this file -> METHOD_CALLS edges
        caller_methods = ql(
            store,
            sql=(
                'SELECT t.m_id AS "m.id", t.m_sl AS "m.startLine", t.m_el AS "m.endLine"'
                " FROM GRAPH_TABLE(agentscaffold_graph"
                "   MATCH (f:File)-[d:DEFINES_CLASS]->(c:Class)-[h:HAS_METHOD]->(m:Method)"
                f"   WHERE f.id = '{file_id}'"
                "   COLUMNS (m.id AS m_id, m.startLine AS m_sl, m.endLine AS m_el)"
                " ) t"
            ),
        )
        for caller in caller_methods:
            _process_caller_body(
                store,
                lines,
                caller["m.id"],
                int(caller["m.startLine"]),
                int(caller["m.endLine"]),
                file_path,
                imported_symbols,
                symbol_table,
                edge_table="METHOD_CALLS",
                src_table="Method",
                counters=counters,
            )

    return {
        "total": counters["total"],
        "high_confidence": counters["high"],
        "medium_confidence": counters["medium"],
        "low_confidence": counters["low"],
        "method_calls": counters["method_calls"],
    }


def _process_caller_body(
    store: GraphBackend,
    lines: list[str],
    caller_id: str,
    start_line: int,
    end_line: int,
    file_path: str,
    imported_symbols: dict[str, str],
    symbol_table: SymbolTable,
    *,
    edge_table: str,
    src_table: str,
    counters: dict[str, int],
) -> None:
    """Extract call sites from one caller body and create resolved edges.

    ``edge_table`` is ``CALLS`` for function callers or ``METHOD_CALLS`` for
    method callers. METHOD_CALLS targets must be Functions (schema constraint),
    so method callers only emit edges for function-target resolutions.
    """
    body = "\n".join(lines[start_line - 1 : end_line])
    seen_targets: set[str] = set()

    for match in _PY_CALL_RE.finditer(body):
        call_name = match.group(1)
        if not call_name or call_name in _PYTHON_BUILTINS:
            continue

        resolution = _resolve_call(call_name, file_path, imported_symbols, symbol_table)
        if resolution is None:
            continue

        target_id, confidence, reason = resolution
        if confidence < MIN_CONFIDENCE:
            continue

        # METHOD_CALLS edges must point at a Function destination.
        if edge_table == "METHOD_CALLS" and reason not in _FUNCTION_TARGET_REASONS:
            continue

        if target_id in seen_targets:
            continue
        seen_targets.add(target_id)

        store.create_edge(
            edge_table,
            src_table,
            caller_id,
            "Function",
            target_id,
            {"confidence": confidence, "reason": reason},
        )

        if edge_table == "METHOD_CALLS":
            counters["method_calls"] += 1
        else:
            counters["total"] += 1
            if confidence >= 0.8:
                counters["high"] += 1
            elif confidence >= 0.5:
                counters["medium"] += 1
            else:
                counters["low"] += 1


def _build_import_map(store: GraphBackend) -> dict[str, dict[str, str]]:
    """Build a map of file_path -> {imported_name: source_file_path}."""
    import_edges = ql(
        store,
        sql=(
            'SELECT t.a_path AS "a.path", t.b_path AS "b.path",'
            ' t.r_names AS "r.importedNames"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            "   MATCH (a:File)-[r:IMPORTS]->(b:File)"
            "   COLUMNS (a.path AS a_path, b.path AS b_path, r.importedNames AS r_names)"
            " ) t"
        ),
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
