"""Phase 3c: Config-reference resolution processor.

Config files wire code dynamically -- e.g. ``configs/strategies/strategy_registry.yaml``
maps ``class: libs.strategies.momentum.MomentumStrategy``. The static call graph only
resolves those dispatch points heuristically, so editing such a class shows no config
consumer. This processor extracts fully-qualified dotted references from config files and
creates ``CONFIG_REFERENCES`` edges (config ``File`` -> target ``File``).

Precision discipline (validated by SPIKE-2026-06-12-config-reference-resolution):
references are extracted ONLY when they appear under an allowlisted key (``class``,
``_target_``, ...). Arbitrary scalars are ignored -- they drop precision to ~85% and
introduce false positives. We resolve against ``File`` nodes already in the graph, so the
ignore set / ``.mypy_cache`` flood is structurally avoided (we never re-walk disk).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agentscaffold.graph.query_compat import ql

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

CONFIG_LANGUAGES: frozenset[str] = frozenset({"yaml", "json", "toml"})

# Keys whose string value is treated as a code reference. Lower-cased for matching.
# Sourced from the P3 spike; deliberately narrow to keep precision high.
ALLOWLIST_KEYS: frozenset[str] = frozenset(
    {
        "class",
        "_target_",
        "target",
        "callable",
        "factory",
        "cls",
        "type",
        "module",
        "import",
        "entrypoint",
        "strategy_class",
        "handler",
        "plugin",
    }
)

CONFIDENCE_FILE_AND_SYMBOL = 0.9
CONFIDENCE_FILE_ONLY = 0.7

# ``key: value`` (YAML), ``"key": "value"`` (JSON), ``key = "value"`` (TOML).
# value must be a dotted path (at least one dot), optionally with a ``:`` entrypoint
# separator (``pkg.mod:Class``). Quotes/commas/trailing space are tolerated.
_REF_LINE_RE = re.compile(
    r"""^\s*['"]?(?P<key>[A-Za-z_][\w-]*)['"]?\s*[:=]\s*"""
    r"""['"]?(?P<val>[A-Za-z_][\w]*(?:[.:][A-Za-z_][\w]*)+)['"]?\s*,?\s*$""",
)


def process_config_references(store: GraphBackend, root: Path) -> dict:
    """Resolve config references and create CONFIG_REFERENCES edges.

    Returns a summary with edge / candidate / config-file counts.
    """
    file_rows = ql(
        store,
        sql='SELECT id AS "f.id", path AS "f.path", language AS "f.language" FROM File',
    )

    path_to_id: dict[str, str] = {}
    config_files: list[tuple[str, str]] = []  # (file_id, path)
    for row in file_rows:
        path_to_id[row["f.path"]] = row["f.id"]
        if row["f.language"] in CONFIG_LANGUAGES:
            config_files.append((row["f.id"], row["f.path"]))

    if not config_files:
        return {"edges": 0, "candidates": 0, "config_files": 0, "resolved": 0}

    defs_by_file, files_by_symbol = _build_symbol_indexes(store)

    # Clear prior edges for the config files we are about to reprocess so that a
    # reference removed from a config no longer lingers as a stale edge.
    config_ids = [fid for fid, _ in config_files]
    _clear_config_edges(store, config_ids)

    edges = 0
    candidates = 0
    resolved = 0
    for file_id, file_path in config_files:
        try:
            source = (root / file_path).read_text(errors="replace")
        except (OSError, PermissionError):
            continue

        seen: set[tuple[str, str]] = set()
        for key, value in _extract_references(source):
            candidates += 1
            target_path, symbol, confidence = _resolve_reference(
                value, path_to_id, defs_by_file, files_by_symbol
            )
            if target_path is None:
                continue
            resolved += 1
            target_id = path_to_id[target_path]
            if target_id == file_id:
                continue  # never self-reference
            edge_key = (target_id, symbol)
            if edge_key in seen:
                continue
            seen.add(edge_key)
            store.create_edge(
                "CONFIG_REFERENCES",
                "File",
                file_id,
                "File",
                target_id,
                {"confidence": confidence, "refKey": key, "symbol": symbol},
            )
            edges += 1

    return {
        "edges": edges,
        "candidates": candidates,
        "config_files": len(config_files),
        "resolved": resolved,
    }


def _clear_config_edges(store: GraphBackend, config_ids: list[str]) -> None:
    """Delete existing CONFIG_REFERENCES edges originating from *config_ids*."""
    if not config_ids:
        return
    ids_lit = ", ".join("'" + cid.replace("'", "''") + "'" for cid in config_ids)
    try:
        store.execute(f"DELETE FROM CONFIG_REFERENCES WHERE src IN ({ids_lit})")
    except Exception as exc:  # pragma: no cover - backend-specific
        logger.debug("Could not clear config edges: %s", exc)


def _build_symbol_indexes(
    store: GraphBackend,
) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """Build ``filePath -> {symbol names}`` and ``symbol name -> [filePaths]``.

    Covers Class and Function definitions (the symbols configs reference). The
    name->files index supports package ``__init__`` re-export resolution.
    """
    defs_by_file: dict[str, set[str]] = {}
    files_by_symbol: dict[str, list[str]] = {}

    for table, name_col in (("Class", "name"), ("Function", "name")):
        for row in ql(
            store,
            sql=f'SELECT {name_col} AS "n", filePath AS "fp" FROM {table}',
        ):
            name = row["n"]
            fpath = row["fp"]
            if not name or not fpath:
                continue
            defs_by_file.setdefault(fpath, set()).add(name)
            files_by_symbol.setdefault(name, []).append(fpath)

    return defs_by_file, files_by_symbol


def _extract_references(source: str) -> list[tuple[str, str]]:
    """Extract ``(key, value)`` references under allowlisted keys from text.

    Works line-by-line so it is parser-free across YAML/JSON/TOML. Only keys in
    ``ALLOWLIST_KEYS`` (case-insensitive) with a dotted-path value are returned.
    """
    refs: list[tuple[str, str]] = []
    for line in source.splitlines():
        match = _REF_LINE_RE.match(line)
        if not match:
            continue
        key = match.group("key")
        if key.lower() not in ALLOWLIST_KEYS:
            continue
        refs.append((key, match.group("val")))
    return refs


def _module_to_path(parts: list[str], path_to_id: dict[str, str]) -> str | None:
    """Resolve dotted module *parts* to an indexed File path, or None.

    Tries ``a/b/c.py`` then ``a/b/c/__init__.py``, with common source-prefix
    fallbacks. Only paths that exist as File nodes are returned.
    """
    base = "/".join(parts)
    candidates = [f"{base}.py", f"{base}/__init__.py"]
    for prefix in ("src/", "lib/", "libs/"):
        candidates.append(f"{prefix}{base}.py")
        candidates.append(f"{prefix}{base}/__init__.py")
    for candidate in candidates:
        if candidate in path_to_id:
            return candidate
    return None


def _resolve_reference(
    value: str,
    path_to_id: dict[str, str],
    defs_by_file: dict[str, set[str]],
    files_by_symbol: dict[str, list[str]],
) -> tuple[str | None, str, float]:
    """Resolve a dotted reference to ``(target_path, symbol, confidence)``.

    Returns ``(None, "", 0.0)`` when nothing resolves. ``symbol`` is the trailing
    Class/Function name when it resolved in the target file, else ``""``.
    """
    normalized = value.replace(":", ".")
    parts = [p for p in normalized.split(".") if p]
    if len(parts) < 2:
        return None, "", 0.0

    # Case 1: the full path is itself a module/file (file-only reference).
    full_path = _module_to_path(parts, path_to_id)
    if full_path is not None:
        return full_path, "", CONFIDENCE_FILE_ONLY

    # Case 2: trailing part is a symbol; the rest is the module.
    symbol = parts[-1]
    module_path = _module_to_path(parts[:-1], path_to_id)
    if module_path is not None:
        if symbol in defs_by_file.get(module_path, set()):
            return module_path, symbol, CONFIDENCE_FILE_AND_SYMBOL
        # Symbol not defined in that file (e.g. re-exported via package __init__).
        owners = files_by_symbol.get(symbol, [])
        if len(owners) == 1:
            return owners[0], symbol, CONFIDENCE_FILE_AND_SYMBOL
        # Module resolved but symbol could not be pinned: file-only edge.
        return module_path, "", CONFIDENCE_FILE_ONLY

    # Case 3: module did not resolve, but the symbol is uniquely defined somewhere.
    owners = files_by_symbol.get(symbol, [])
    if len(owners) == 1:
        return owners[0], symbol, CONFIDENCE_FILE_AND_SYMBOL

    return None, "", 0.0
