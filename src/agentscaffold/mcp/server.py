"""MCP server for AgentScaffold knowledge graph.

Exposes graph queries as MCP tools and resources via stdio transport.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Resource, TextContent, Tool

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

_MCP_EXTRAS_MSG = "MCP server requires extra dependencies: pip install agentscaffold[mcp]"


def run_mcp_server() -> None:
    """Start the MCP server on stdio."""
    if not _MCP_AVAILABLE:
        raise ImportError(_MCP_EXTRAS_MSG)

    import asyncio

    asyncio.run(_serve())


async def _serve() -> None:
    """Async entry point for the MCP server."""
    server = Server("agentscaffold")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return _get_tool_definitions()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = _dispatch_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return _get_resource_definitions()

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        return json.dumps(_dispatch_resource(uri), indent=2, default=str)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _get_tool_definitions() -> list:
    """Return MCP tool definitions."""
    if not _MCP_AVAILABLE:
        return []

    return [
        Tool(
            name="scaffold_context",
            description=(
                "Get full context for a symbol: definition, callers, callees, "
                "imports, layer, plan history, contract status, related learnings."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol name to look up"},
                },
                "required": ["symbol"],
            },
        ),
        Tool(
            name="scaffold_impact",
            description=(
                "Analyze blast radius of changing a file or symbol. Shows transitive "
                "consumers, affected layers, and related governance context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_or_symbol": {"type": "string", "description": "File path or symbol name"},
                    "depth": {
                        "type": "integer",
                        "description": "Traversal depth (default 2)",
                        "default": 2,
                    },
                },
                "required": ["file_or_symbol"],
            },
        ),
        Tool(
            name="scaffold_search",
            description=(
                "Search across code definitions using hybrid search "
                "(structural graph + semantic similarity). Supports cypher, "
                "semantic, or hybrid modes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "mode": {
                        "type": "string",
                        "enum": ["cypher", "semantic", "hybrid"],
                        "description": "Search mode (default: hybrid)",
                        "default": "hybrid",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="scaffold_validate",
            description="Run validation checks: layer conformance, contract drift.",
            inputSchema={
                "type": "object",
                "properties": {
                    "check": {
                        "type": "string",
                        "enum": ["layers", "contracts", "staleness"],
                        "description": "Validation check to run",
                    },
                },
                "required": ["check"],
            },
        ),
        Tool(
            name="scaffold_query",
            description="Execute a raw Cypher query against the knowledge graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cypher": {"type": "string", "description": "Cypher query to execute"},
                },
                "required": ["cypher"],
            },
        ),
        Tool(
            name="scaffold_stats",
            description=(
                "Get codebase health overview with file/function/edge "
                "counts and governance summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="scaffold_review_context",
            description=(
                "Generate graph-powered review context for a plan. "
                "Returns brief, adversarial challenges, gap analysis, "
                "post-implementation verification, or retro enrichment "
                "depending on review_type."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {
                        "type": "integer",
                        "description": "Plan number to review",
                    },
                    "review_type": {
                        "type": "string",
                        "enum": ["brief", "challenges", "gaps", "verify", "retro", "all"],
                        "description": "Type of review context to generate",
                    },
                },
                "required": ["plan_number", "review_type"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Resource definitions
# ---------------------------------------------------------------------------


def _get_resource_definitions() -> list:
    """Return MCP resource definitions."""
    if not _MCP_AVAILABLE:
        return []

    return [
        Resource(
            uri="scaffold://project/context",
            name="Project Context",
            description="Project stats, layer map, hot spots, recent plans.",
            mimeType="application/json",
        ),
        Resource(
            uri="scaffold://project/layers",
            name="Architecture Layers",
            description="Architecture layers with file counts.",
            mimeType="application/json",
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call to the appropriate handler."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        return {"error": "No knowledge graph found. Run 'scaffold index' first."}

    store = open_graph(config)
    root = Path.cwd()
    meta = _build_meta(store, root)

    try:
        if name == "scaffold_stats":
            result = store.get_stats()
            result["meta"] = meta
            return result

        elif name == "scaffold_query":
            cypher = arguments.get("cypher", "")
            rows = store.query(cypher)
            return {"results": rows, "count": len(rows), "meta": meta}

        elif name == "scaffold_context":
            return _tool_context(store, arguments, meta)

        elif name == "scaffold_impact":
            return _tool_impact(store, arguments, meta)

        elif name == "scaffold_search":
            return _tool_search(store, arguments, meta)

        elif name == "scaffold_validate":
            return _tool_validate(store, arguments, meta)

        elif name == "scaffold_review_context":
            return _tool_review_context(store, arguments, meta)

        else:
            return {"error": f"Unknown tool: {name}"}

    finally:
        store.close()


def _build_meta(store: Any, root: Path) -> dict[str, Any]:
    """Build metadata block for tool responses."""
    state = store.get_pipeline_state()
    return {
        "graph_indexed_at": state.get("last_indexed"),
        "pipeline_state": state.get("state", "unknown"),
    }


def _tool_context(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_context tool call."""
    symbol = arguments.get("symbol", "")

    # Search across functions, classes, methods
    results = store.query(
        f"MATCH (fn:Function) WHERE fn.name = '{symbol}' "
        "RETURN fn.id, fn.name, fn.filePath, fn.startLine, fn.endLine, fn.signature"
    )
    if not results:
        results = store.query(
            f"MATCH (c:Class) WHERE c.name = '{symbol}' "
            "RETURN c.id, c.name, c.filePath, c.startLine, c.endLine"
        )

    if not results:
        return {"error": f"Symbol '{symbol}' not found in graph.", "meta": meta}

    node = results[0]
    node_id = node.get("fn.id") or node.get("c.id")

    # Find callers
    callers = store.query(
        f"MATCH (caller:Function)-[r:CALLS]->(fn:Function) WHERE fn.id = '{node_id}' "
        "RETURN caller.name, caller.filePath, r.confidence"
    )

    # Find callees
    callees = store.query(
        f"MATCH (fn:Function)-[r:CALLS]->(callee:Function) WHERE fn.id = '{node_id}' "
        "RETURN callee.name, callee.filePath, r.confidence"
    )

    return {
        "symbol": node,
        "callers": callers,
        "callees": callees,
        "caller_count": len(callers),
        "callee_count": len(callees),
        "meta": meta,
    }


def _tool_impact(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_impact tool call."""
    target = arguments.get("file_or_symbol", "")
    _depth = arguments.get("depth", 2)  # noqa: F841 -- reserved for multi-hop traversal

    file_id = f"file::{target}"

    # Find direct importers
    importers = store.query(
        f"MATCH (a:File)-[:IMPORTS]->(b:File) WHERE b.id = '{file_id}' RETURN a.path, a.language"
    )

    # Find functions in this file and their callers
    callers = store.query(
        "MATCH (caller:Function)-[r:CALLS]->(fn:Function)-[:DEFINES_FUNCTION]-(f:File) "
        f"WHERE f.id = '{file_id}' "
        "RETURN DISTINCT caller.filePath, caller.name, r.confidence"
    )

    return {
        "target": target,
        "direct_importers": importers,
        "importer_count": len(importers),
        "callers_into_file": callers,
        "caller_count": len(callers),
        "meta": meta,
    }


def _tool_search(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_search tool call (hybrid search)."""
    from agentscaffold.graph.search import format_search_results, hybrid_search

    query_text = arguments.get("query", "")
    mode = arguments.get("mode", "hybrid")
    top_k = arguments.get("top_k", 10)

    results = hybrid_search(store, query_text, mode=mode, top_k=top_k)

    return {
        "results": [
            {
                "node_id": r.node_id,
                "name": r.name,
                "path": r.path,
                "type": r.node_type,
                "score": r.score,
                "source": r.source,
            }
            for r in results
        ],
        "count": len(results),
        "markdown": format_search_results(results),
        "meta": meta,
    }


def _tool_validate(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_validate tool call."""
    check = arguments.get("check", "")

    if check == "staleness":
        from agentscaffold.graph.verify import verify_graph

        report = verify_graph(store, Path.cwd())
        return {"report": report, "meta": meta}

    if check == "contracts":
        from agentscaffold.graph.verify import check_contract_drift

        report = check_contract_drift(store)
        return {"report": report, "meta": meta}

    return {"error": f"Check '{check}' not yet implemented.", "meta": meta}


def _tool_review_context(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_review_context tool call (Dialectic Engine)."""
    plan_number = arguments.get("plan_number")
    review_type = arguments.get("review_type", "brief")

    if plan_number is None:
        return {"error": "plan_number is required.", "meta": meta}

    result: dict[str, Any] = {"plan_number": plan_number, "meta": meta}

    if review_type in ("brief", "all"):
        from agentscaffold.review.brief import format_brief_markdown, generate_brief

        brief = generate_brief(store, plan_number)
        result["brief"] = brief
        result["brief_markdown"] = format_brief_markdown(brief)

    if review_type in ("challenges", "all"):
        from agentscaffold.review.challenges import (
            format_challenges_markdown,
            generate_challenges,
        )

        challenges = generate_challenges(store, plan_number)
        result["challenges"] = [
            {"category": c.category, "text": c.text, "severity": c.severity} for c in challenges
        ]
        result["challenges_markdown"] = format_challenges_markdown(challenges)

    if review_type in ("gaps", "all"):
        from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps

        gaps = generate_gaps(store, plan_number)
        result["gaps"] = [
            {"category": g.category, "text": g.text, "severity": g.severity} for g in gaps
        ]
        result["gaps_markdown"] = format_gaps_markdown(gaps)

    if review_type in ("verify", "all"):
        from agentscaffold.review.verify import (
            format_verification_markdown,
            verify_implementation,
        )

        items = verify_implementation(store, plan_number)
        result["verification"] = [
            {"check": i.check, "status": i.status, "detail": i.detail} for i in items
        ]
        result["verification_markdown"] = format_verification_markdown(items)

    if review_type in ("retro", "all"):
        from agentscaffold.review.feedback import (
            format_retro_markdown,
            generate_retro_enrichment,
        )

        insights = generate_retro_enrichment(store, plan_number)
        result["retro_insights"] = [{"category": i.category, "text": i.text} for i in insights]
        result["retro_markdown"] = format_retro_markdown(insights)

    return result


# ---------------------------------------------------------------------------
# Resource dispatch
# ---------------------------------------------------------------------------


def _dispatch_resource(uri: str) -> dict[str, Any]:
    """Dispatch a resource read to the appropriate handler."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        return {"error": "No knowledge graph found."}

    store = open_graph(config)

    try:
        if uri == "scaffold://project/context":
            stats = store.get_stats()
            return stats

        elif uri == "scaffold://project/layers":
            layers = store.query(
                "MATCH (l:ArchitectureLayer) RETURN l.number, l.name, l.pathPatterns "
                "ORDER BY l.number"
            )
            return {"layers": layers}

        return {"error": f"Unknown resource: {uri}"}

    finally:
        store.close()
