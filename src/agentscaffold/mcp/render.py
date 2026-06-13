"""Agent-facing rendering helpers for MCP composite tools.

The DuckPGQ query layer aliases columns as ``"alias.field"`` (for example
``"caller.name"`` or ``"a.path"``). Those prefixes are an implementation detail
of the graph queries and leak as noise into agent-visible JSON. The helpers here
strip the prefixes and render compact markdown summaries so an agent can read
code relationships directly instead of parsing nested, dot-qualified dicts.
"""

from __future__ import annotations

from typing import Any


def clean_key(key: str) -> str:
    """Strip a single ``alias.`` prefix from a query column key.

    ``"caller.name"`` -> ``"name"``; already-clean keys are returned unchanged.
    """
    return key.split(".", 1)[-1] if "." in key else key


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *row* with ``alias.`` prefixes stripped from keys."""
    return {clean_key(k): v for k, v in row.items()}


def clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply :func:`clean_row` to every row in *rows*."""
    return [clean_row(r) for r in rows]


def _loc(row: dict[str, Any]) -> str:
    """Render a ``path:line`` location string from a cleaned row."""
    path = row.get("filePath") or row.get("path") or ""
    start = row.get("startLine")
    return f"{path}:{start}" if path and start else path


def _bullet_list(
    rows: list[dict[str, Any]], limit: int = 25, show_confidence: bool = False
) -> list[str]:
    """Render rows as markdown bullets of ``name (path)``.

    When *show_confidence* is True, rows whose ``confidence`` is below the
    heuristic threshold are annotated so the agent can tell a guessed edge from
    a resolved one. High-confidence rows are left unannotated to avoid noise.
    """
    from agentscaffold.mcp.coverage import is_heuristic_confidence

    lines: list[str] = []
    for row in rows[:limit]:
        name = row.get("name") or row.get("path") or "?"
        path = row.get("filePath") or row.get("path") or ""
        suffix = f"  ({path})" if path and path != name else ""
        annotation = ""
        if show_confidence and is_heuristic_confidence(row.get("confidence")):
            annotation = f"  [confidence {float(row['confidence']):.2f}, heuristic]"
        lines.append(f"- `{name}`{suffix}{annotation}")
    if len(rows) > limit:
        lines.append(f"- ... and {len(rows) - limit} more")
    if not rows:
        lines.append("- none recorded")
    return lines


def _config_consumer_list(rows: list[dict[str, Any]], limit: int = 25) -> list[str]:
    """Render CONFIG_REFERENCES consumers as ``path (key: symbol) [confidence]``."""
    lines: list[str] = []
    for row in rows[:limit]:
        path = row.get("path") or "?"
        symbol = row.get("symbol") or ""
        key = row.get("refKey") or ""
        conf = row.get("confidence")
        if symbol:
            ref = f"  ({key}: {symbol})" if key else f"  ({symbol})"
        else:
            ref = f"  ({key})" if key else ""
        conf_s = f"  [confidence {float(conf):.2f}]" if isinstance(conf, int | float) else ""
        lines.append(f"- `{path}`{ref}{conf_s}")
    if len(rows) > limit:
        lines.append(f"- ... and {len(rows) - limit} more")
    if not rows:
        lines.append("- none recorded")
    return lines


def _section_header(label: str, rows: list[dict[str, Any]]) -> str:
    """Build a ``### label (N)`` header, noting heuristic edges when present."""
    from agentscaffold.mcp.coverage import count_heuristic

    heuristic = count_heuristic(rows)
    if heuristic:
        return f"\n### {label} ({len(rows)}, {heuristic} heuristic)"
    return f"\n### {label} ({len(rows)})"


def _caveat_note(caveat: str | None) -> list[str]:
    """Render a coverage caveat as a markdown blockquote note (or nothing)."""
    if not caveat:
        return []
    return ["", f"> Coverage note: {caveat}"]


def format_context_markdown(
    symbol: dict[str, Any],
    callers: list[dict[str, Any]],
    callees: list[dict[str, Any]],
    method_callers: list[dict[str, Any]] | None = None,
    caveat: str | None = None,
    config_consumers: list[dict[str, Any]] | None = None,
) -> str:
    """Render a markdown summary of a symbol and its call relationships."""
    method_callers = method_callers or []
    name = symbol.get("name", "?")
    lines: list[str] = [f"## `{name}`"]

    loc = _loc(symbol)
    if loc:
        lines.append(f"Defined in `{loc}`")
    sig = symbol.get("signature")
    if sig:
        lines.append(f"\nSignature: `{sig}`")

    lines.append(_section_header("Callers", callers))
    lines.extend(_bullet_list(callers, show_confidence=True))

    if method_callers:
        lines.append(_section_header("Method callers", method_callers))
        lines.extend(_bullet_list(method_callers, show_confidence=True))

    lines.append(_section_header("Callees", callees))
    lines.extend(_bullet_list(callees, show_confidence=True))

    if config_consumers:
        lines.append(f"\n### Config references ({len(config_consumers)})")
        lines.extend(_config_consumer_list(config_consumers))

    lines.extend(_caveat_note(caveat))

    return "\n".join(lines)


def format_impact_markdown(
    target: str,
    importers_by_level: list[list[dict[str, Any]]],
    callers: list[dict[str, Any]],
    method_callers: list[dict[str, Any]] | None = None,
    caveat: str | None = None,
    config_consumers: list[dict[str, Any]] | None = None,
) -> str:
    """Render a markdown blast-radius summary for a file/symbol."""
    method_callers = method_callers or []
    total_importers = sum(len(level) for level in importers_by_level)
    depth = len(importers_by_level)

    lines: list[str] = [f"## Impact: `{target}`"]
    lines.append(f"\n### Importing files ({total_importers} across {depth} hop(s))")
    if total_importers == 0:
        lines.append("- none recorded")
    else:
        for i, level in enumerate(importers_by_level, start=1):
            if not level:
                continue
            lines.append(f"\nDepth {i} ({len(level)}):")
            lines.extend(_bullet_list(level))

    lines.append(_section_header("Functions calling into this file", callers))
    lines.extend(_bullet_list(callers, show_confidence=True))

    if method_callers:
        lines.append(_section_header("Methods calling into this file", method_callers))
        lines.extend(_bullet_list(method_callers, show_confidence=True))

    if config_consumers:
        lines.append(f"\n### Config files referencing this file ({len(config_consumers)})")
        lines.extend(_config_consumer_list(config_consumers))

    lines.extend(_caveat_note(caveat))

    return "\n".join(lines)
