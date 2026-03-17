"""MCP server for AgentScaffold knowledge graph.

Exposes graph queries as MCP tools and resources via stdio transport.
Composite tools and their intent metadata are the single source of truth
for semantic mapping -- platform rule files are generated from these.
"""

from __future__ import annotations

import json
import logging
import re
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

# ---------------------------------------------------------------------------
# Intent metadata: single source of truth for semantic mapping.
# Platform rule generators (cursor, windsurf, claude) read from this dict.
# ---------------------------------------------------------------------------

TOOL_INTENTS: dict[str, list[str]] = {
    "scaffold_prepare_review": [
        "review plan X",
        "critique plan X",
        "devil's advocate on plan X",
        "prepare plan X for review",
        "let's review plan X",
        "following the collab protocol for plan X",
        "pre-reviews for plan X",
        "all three reviews for plan X",
        "pressure-test plan X",
        "stress test plan X",
        "challenge this plan before coding",
    ],
    "scaffold_prepare_implementation": [
        "implement plan X",
        "start plan X",
        "execute plan X",
        "begin implementation of plan X",
        "what do I need to implement plan X",
        "prep for implementing plan X",
        "approved to go on plan X",
        "begin implementation per collab protocol",
        "start building plan X",
        "begin building plan X",
        "ready to build plan X",
    ],
    "scaffold_compare_plans": [
        "does plan X conflict with plan Y",
        "overlap between plans",
        "check plan X vs plan Y",
        "compare plans X and Y",
        "any overlapping concerns between plan X and Y",
        "do plans X and Y overlap",
        "check for conflicts between X and Y",
        "do these plans step on each other",
        "are these plans stepping on each other",
    ],
    "scaffold_staleness_check": [
        "is plan X stale",
        "is this plan still valid",
        "is plan X still valid",
        "staleness review on plan X",
        "has anything changed since plan X",
        "does plan X need updating",
        "check if plan X needs refactoring",
        "has this plan gone out of date",
        "is this plan out of date",
    ],
    "scaffold_prepare_rewrite": [
        "rewrite plan X",
        "update plan X",
        "expand plan X",
        "refresh plan X with current state",
        "revise plan X",
        "update plan X to use Y",
    ],
    "scaffold_prepare_retro": [
        "retro on plan X",
        "retrospective for plan X",
        "post-implementation review",
        "quant architect review on plan X",
        "post implementation review and retro for plan X",
        "share the review and retro",
        "post implementation retrospective",
        "let's do the post-implementation retrospective",
    ],
    "scaffold_orient": [
        "where did we leave off",
        "what's the current state",
        "what's blocked",
        "what are the next steps",
        "session start",
        "where are we",
        "what should I work on now",
        "what are the next priorities",
        "latest blockers and what's next",
        "current blockers and next steps",
    ],
    "scaffold_find_studies": [
        "any studies on X",
        "experiments related to X",
        "what did we test for X",
        "show me studies about X",
        "prior experiments about X",
        "any prior experiments about X",
    ],
    "scaffold_prior_experiments": [
        "has this been tested",
        "prior experiments for plan X",
        "any evidence for this approach",
        "what experiments relate to plan X",
    ],
    "scaffold_find_adrs": [
        "any ADRs about X",
        "what architectural decisions cover X",
        "show me ADRs related to storage",
        "which ADR governs X",
        "what ADR blocks plan X",
        "the ADR blocking them",
        "which architecture decision governs X",
        "what architecture decision governs X",
    ],
    "scaffold_decision_context": [
        "what's the decision history for plan X",
        "was there a spike for plan X",
        "what ADR governs plan X",
        "show me the full decision chain for plan X",
        "what was the original intent for plan X",
        "trace the decisions for plan X",
        "trace the rationale chain for plan X",
        "why was this plan decided this way",
    ],
    "scaffold_record_finding": [
        "record finding",
        "log finding",
        "note a finding",
        "discovered issue in plan",
        "review found an issue",
        "I found an issue in plan X",
        "log this review finding",
        "capture this finding",
    ],
    "scaffold_resolve_finding": [
        "mark finding resolved",
        "close finding",
        "fix has been addressed",
        "resolved finding",
        "finding has been closed",
        "mark this issue as resolved",
        "resolve this finding",
        "finding is resolved",
    ],
}

_ROUTING_STOPWORDS = {
    "a",
    "an",
    "the",
    "for",
    "to",
    "of",
    "on",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "with",
    "this",
    "that",
    "these",
    "those",
    "what",
    "how",
    "can",
    "do",
    "does",
    "did",
    "let",
    "lets",
    "we",
    "i",
    "x",
    "plan",
}

_ROUTING_NORMALIZERS: list[tuple[str, str]] = [
    (r"\bpressure[\s-]*test\b", "critique"),
    (r"\bstress[\s-]*test\b", "critique"),
    (r"\bstart building\b", "implement"),
    (r"\bbegin building\b", "implement"),
    (r"\bpost[\s-]*implementation\b", "post implementation"),
    (r"\bout of date\b", "stale"),
    (r"\brationale chain\b", "decision chain"),
    (r"\barchitecture decision\b", "adr"),
    (r"\bprior experiments\b", "studies"),
    (r"\bstep on each other\b", "conflict"),
    (r"\bblockers\b", "blocked"),
    (r"\bcollisions?\b", "conflict"),
    (r"\blineage\b", "decision chain"),
    (r"\bhas .* changed enough\b", "stale"),
    # Finding-record disambiguation: "review found/discovered X" describes a finding result,
    # not a request to run a review.  Normalize to "record finding" so the exact substring
    # check in route_tool_from_prompt returns scaffold_record_finding immediately.
    (r"\breview found\b", "record finding"),
    (r"\breview discovered\b", "record finding"),
    # Past-tense "has been fixed" expresses resolution, not the act of recording.
    (r"\bhas been fixed\b", "resolved finding"),
]

_TOOL_SIGNAL_TOKENS: dict[str, set[str]] = {
    "scaffold_prepare_review": {"review", "critique", "challenge", "assumption", "pre", "coding"},
    "scaffold_prepare_implementation": {"implement", "build", "start", "begin", "execute"},
    "scaffold_compare_plans": {"compare", "conflict", "overlap", "against", "versus"},
    "scaffold_staleness_check": {"stale", "valid", "changed", "refresh", "update"},
    "scaffold_prepare_rewrite": {"rewrite", "revise", "update", "expand", "refresh"},
    "scaffold_prepare_retro": {"retro", "retrospective", "post", "implementation", "review"},
    "scaffold_orient": {"state", "blocked", "next", "priorities", "where"},
    "scaffold_find_studies": {"study", "studies", "experiment", "experiments", "tested"},
    "scaffold_prior_experiments": {"prior", "experiments", "evidence", "tested"},
    "scaffold_find_adrs": {"adr", "architecture", "decision", "governs"},
    "scaffold_decision_context": {"decision", "history", "chain", "spike", "intent", "adr"},
    "scaffold_record_finding": {"record", "log", "finding", "discovered", "issue", "capture"},
    "scaffold_resolve_finding": {"resolve", "resolved", "close", "fixed", "addressed"},
}


def _normalize_intent_text(text: str) -> str:
    """Normalize free text for robust intent matching."""
    normalized = text.lower()
    for pattern, replacement in _ROUTING_NORMALIZERS:
        normalized = re.sub(pattern, replacement, normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _intent_content_tokens(text: str) -> set[str]:
    tokens = _normalize_intent_text(text).split()
    return {t for t in tokens if t not in _ROUTING_STOPWORDS and len(t) > 2}


def route_tool_from_prompt(prompt: str) -> str | None:
    """Route a user prompt to the best matching tool intent."""
    prompt_norm = _normalize_intent_text(prompt)
    prompt_tokens = _intent_content_tokens(prompt)

    best_tool: str | None = None
    best_score = 0.0

    for tool, intents in TOOL_INTENTS.items():
        tool_signal = _TOOL_SIGNAL_TOKENS.get(tool, set())
        signal_overlap = 0.0
        if tool_signal:
            signal_overlap = len(prompt_tokens & tool_signal) / len(tool_signal)

        for intent in intents:
            intent_norm = _normalize_intent_text(intent)
            if intent_norm and intent_norm in prompt_norm:
                return tool

            intent_tokens = _intent_content_tokens(intent)
            if not intent_tokens:
                continue

            overlap = len(intent_tokens & prompt_tokens)
            if overlap == 0:
                continue
            phrase_score = overlap / len(intent_tokens)
            # Weighted score favors direct intent phrase overlap, then tool-level signal overlap.
            score = 0.75 * phrase_score + 0.25 * signal_overlap

            if score > best_score:
                best_score = score
                best_tool = tool

    # Confidence band tuned to preserve precision while improving paraphrase recall.
    return best_tool if best_score >= 0.5 else None


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
                "(structural graph + semantic similarity). Supports keyword, "
                "semantic, or hybrid modes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "mode": {
                        "type": "string",
                        "enum": ["keyword", "semantic", "hybrid"],
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
            description="Execute a raw SQL query against the knowledge graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query to execute"},
                },
                "required": ["sql"],
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
        # --- Composite tools ---
        Tool(
            name="scaffold_prepare_review",
            description=(
                "Prepare full review context for a plan in one call. Use when the user "
                "asks to review, critique, prepare, or do devil's advocate on a plan. "
                "Returns dependency brief, gap analysis, adversarial challenges, "
                "governing ADRs, validation spikes, and related studies."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_prepare_implementation",
            description=(
                "Prepare implementation context for a plan. Use when the user asks to "
                "implement, start, or execute a plan. Returns dependency brief, per-file "
                "blast radius, contract obligations, consumer audit, and dependency status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                    "gate_transition": {
                        "type": "boolean",
                        "description": (
                            "When true, treat call as a strict lifecycle gate transition. "
                            "If freshness gate is enabled and graph is stale, "
                            "transition is deferred."
                        ),
                    },
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_compare_plans",
            description=(
                "Compare two plans for conflicts, shared files, and supersession. "
                "Use when the user asks to compare plans or check for overlap."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_a": {"type": "integer", "description": "First plan number"},
                    "plan_b": {"type": "integer", "description": "Second plan number"},
                },
                "required": ["plan_a", "plan_b"],
            },
        ),
        Tool(
            name="scaffold_staleness_check",
            description=(
                "Check if a plan is stale: overlapping completed plans, missing files, "
                "changed dependencies, contradicting studies. Use when the user asks "
                "if a plan is still valid or stale."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_prepare_rewrite",
            description=(
                "Prepare context for rewriting a stale plan. Superset of staleness check "
                "plus current dependency landscape and new contracts/plans since the plan "
                "was written. Use when the user asks to rewrite, update, or refresh a plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_prepare_retro",
            description=(
                "Prepare retrospective context for a completed plan. Returns verification "
                "results, retro enrichment, modification frequency, and related studies. "
                "Use when the user asks for a retrospective or post-implementation review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_orient",
            description=(
                "Get session orientation: codebase stats, recent plans, hot files, "
                "recent studies, active ADRs, and live workflow state (blockers, next "
                "steps, in-progress plans). Use at session start or when the user asks "
                "where we left off, what's blocked, or what the current state is."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="scaffold_find_studies",
            description=(
                "Search studies by topic keyword or outcome. Use when the user asks "
                "about studies, experiments, or A/B tests on a topic."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Keyword to search in tags/title"},
                    "outcome": {
                        "type": "string",
                        "description": "Filter by outcome (e.g. baseline_preferred)",
                    },
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="scaffold_prior_experiments",
            description=(
                "Find prior experiments related to a plan: directly referenced studies, "
                "tag-matched studies, and file-overlap studies. Use when the user asks "
                "if something has been tested or what experiments relate to a plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_find_adrs",
            description=(
                "Search ADRs by topic keyword or status. Use when the user asks about "
                "architectural decisions, ADRs, or what governs a particular area."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Keyword to search in ADR titles"},
                    "status": {
                        "type": "string",
                        "description": "Filter by ADR status (e.g. Accepted)",
                    },
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="scaffold_decision_context",
            description=(
                "Get the full decision chain for a plan: governing ADRs, validation "
                "spikes, supporting studies, related experiments, and dependency status. "
                "Use when the user asks about decision history, prior validation, or "
                "what ADR governs a plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_record_finding",
            description=(
                "Record a review finding in the knowledge graph. Creates a ReviewFinding "
                "node linked to the relevant plan, files, and functions. Use this when "
                "you identify an issue, concern, or improvement during a code review. "
                "Findings persist across sessions and surface in future reviews."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {
                        "type": "integer",
                        "description": "Plan number this finding relates to",
                    },
                    "review_type": {
                        "type": "string",
                        "description": (
                            "Review type (e.g. 'quant_architect', 'security', 'devils_advocate')"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Finding category (e.g. 'correctness', 'performance', 'risk')"
                        ),
                    },
                    "finding": {
                        "type": "string",
                        "description": "Human-readable description of the finding",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Severity level (default: medium)",
                        "default": "medium",
                    },
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths related to this finding",
                    },
                    "function_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Function node IDs related to this finding",
                    },
                },
                "required": ["plan_number", "review_type", "category", "finding"],
            },
        ),
        Tool(
            name="scaffold_resolve_finding",
            description=(
                "Mark a ReviewFinding as resolved. Use this when an issue identified "
                "during a prior review has been addressed. The finding remains in the "
                "graph with status='resolved' for audit trail purposes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "finding_id": {
                        "type": "string",
                        "description": (
                            "The ID of the finding to resolve (from scaffold_record_finding)"
                        ),
                    },
                    "resolution": {
                        "type": "string",
                        "description": "Description of how the finding was resolved",
                    },
                },
                "required": ["finding_id", "resolution"],
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
    freshness_meta: dict[str, Any] = {}
    try:
        from agentscaffold.mcp.freshness import (
            evaluate_freshness,
            maybe_schedule_async_refresh,
            refresh_runtime_state,
        )

        freshness_meta = evaluate_freshness(root, config)
        freshness_meta.update(refresh_runtime_state(root, config))

        if freshness_meta.get("freshness_status") in {"stale", "unknown"}:
            schedule = maybe_schedule_async_refresh(
                root,
                config,
                tool_name=name,
                reason=str(freshness_meta.get("freshness_reason", "stale_or_unknown")),
            )
            freshness_meta.update(schedule)
        else:
            freshness_meta.setdefault("refresh_triggered", False)
    except Exception as exc:  # pragma: no cover - defensive fallback
        freshness_meta = {
            "freshness_status": "unknown",
            "freshness_reason": f"freshness_oracle_error:{exc}",
            "refresh_triggered": False,
            "refresh_state": "failed",
        }

    meta = _build_meta(store, root, freshness_meta)

    if config.freshness.gate_strict and bool(arguments.get("gate_transition")):
        if freshness_meta.get("freshness_status") in {"stale", "unknown", "refreshing"}:
            return {
                "error": "Gate transition deferred until graph freshness is restored.",
                "gate_deferred": True,
                "meta": meta,
            }

    try:
        if name == "scaffold_stats":
            result = store.get_stats()
            result["meta"] = meta
            return result

        elif name == "scaffold_query":
            sql = arguments.get("sql", "")
            if not sql:
                return {"error": "Missing 'sql' parameter.", "meta": meta}
            rows = store.query(sql)
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

        elif name == "scaffold_prepare_review":
            return _tool_prepare_review(store, arguments, meta, root, config)

        elif name == "scaffold_prepare_implementation":
            return _tool_prepare_implementation(store, arguments, meta, root)

        elif name == "scaffold_compare_plans":
            return _tool_compare_plans(store, arguments, meta)

        elif name == "scaffold_staleness_check":
            return _tool_staleness_check(store, arguments, meta)

        elif name == "scaffold_prepare_rewrite":
            return _tool_prepare_rewrite(store, arguments, meta)

        elif name == "scaffold_prepare_retro":
            return _tool_prepare_retro(store, arguments, meta)

        elif name == "scaffold_orient":
            return _tool_orient(store, meta, root, config)

        elif name == "scaffold_find_studies":
            return _tool_find_studies(store, arguments, meta)

        elif name == "scaffold_prior_experiments":
            return _tool_prior_experiments(store, arguments, meta)

        elif name == "scaffold_find_adrs":
            return _tool_find_adrs(store, arguments, meta)

        elif name == "scaffold_decision_context":
            return _tool_decision_context(store, arguments, meta)

        elif name == "scaffold_record_finding":
            return _tool_record_finding(store, arguments, meta)

        elif name == "scaffold_resolve_finding":
            return _tool_resolve_finding(store, arguments, meta)

        else:
            return {"error": f"Unknown tool: {name}"}

    finally:
        store.close()


def _build_meta(
    store: Any,
    root: Path,
    freshness_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build metadata block for tool responses."""
    state = store.get_pipeline_state()
    meta = {
        "graph_indexed_at": state.get("last_indexed"),
        "pipeline_state": state.get("state", "unknown"),
    }
    if freshness_meta:
        meta.update(freshness_meta)
    return meta


def _tool_context(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_context tool call."""
    from agentscaffold.graph.query_compat import ql

    symbol = arguments.get("symbol", "")

    # Search across functions, classes, methods
    results = ql(
        store,
        sql=(
            f'SELECT id AS "fn.id", name AS "fn.name", filePath AS "fn.filePath", '
            f'startLine AS "fn.startLine", endLine AS "fn.endLine", signature AS "fn.signature" '
            f"FROM Function WHERE name = '{symbol}'"
        ),
    )
    if not results:
        results = ql(
            store,
            sql=(
                f'SELECT id AS "c.id", name AS "c.name", filePath AS "c.filePath", '
                f'startLine AS "c.startLine", endLine AS "c.endLine" '
                f"FROM Class WHERE name = '{symbol}'"
            ),
        )

    if not results:
        return {"error": f"Symbol '{symbol}' not found in graph.", "meta": meta}

    node = results[0]
    node_id = node.get("fn.id") or node.get("c.id")

    # Find callers
    callers = ql(
        store,
        sql=(
            f'SELECT t.caller_name AS "caller.name", t.caller_fp AS "caller.filePath", '
            f't.r_conf AS "r.confidence" '
            f"FROM GRAPH_TABLE(agentscaffold_graph "
            f"MATCH (caller:Function)-[r:CALLS]->(fn:Function) "
            f"WHERE fn.id = '{node_id}' "
            f"COLUMNS (caller.name AS caller_name, "
            f"caller.filePath AS caller_fp, "
            f"r.confidence AS r_conf)) t"
        ),
    )

    # Find callees
    callees = ql(
        store,
        sql=(
            f'SELECT t.callee_name AS "callee.name", '
            f't.callee_fp AS "callee.filePath", '
            f't.r_conf AS "r.confidence" '
            f"FROM GRAPH_TABLE(agentscaffold_graph "
            f"MATCH (fn:Function)-[r:CALLS]->(callee:Function) "
            f"WHERE fn.id = '{node_id}' "
            f"COLUMNS (callee.name AS callee_name, "
            f"callee.filePath AS callee_fp, "
            f"r.confidence AS r_conf)) t"
        ),
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
    from agentscaffold.graph.query_compat import ql

    target = arguments.get("file_or_symbol", "")
    _depth = arguments.get("depth", 2)  # noqa: F841 -- reserved for multi-hop traversal

    file_id = f"file::{target}"

    # Find direct importers
    importers = ql(
        store,
        sql=(
            f'SELECT t.a_path AS "a.path", t.a_lang AS "a.language" '
            f"FROM GRAPH_TABLE(agentscaffold_graph "
            f"MATCH (a:File)-[e:IMPORTS]->(b:File) "
            f"WHERE b.id = '{file_id}' "
            f"COLUMNS (a.path AS a_path, a.language AS a_lang)) t"
        ),
    )

    # Find functions in this file and their callers
    callers = ql(
        store,
        sql=(
            f'SELECT DISTINCT t.caller_fp AS "caller.filePath", t.caller_name AS "caller.name", '
            f't.r_conf AS "r.confidence" '
            f"FROM GRAPH_TABLE(agentscaffold_graph "
            f"MATCH (caller:Function)-[r:CALLS]->(fn:Function)<-[e:DEFINES_FUNCTION]-(f:File) "
            f"WHERE f.id = '{file_id}' "
            f"COLUMNS (caller.filePath AS caller_fp, "
            f"caller.name AS caller_name, "
            f"r.confidence AS r_conf)) t"
        ),
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
# Composite tool handlers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low")


def _sev_key(row: dict) -> int:
    sev = (row.get("rf.severity") or "medium").lower()
    try:
        return _SEVERITY_ORDER.index(sev)
    except ValueError:
        return len(_SEVERITY_ORDER)


def _file_matches_domain_pattern(fpath: str, pattern: str) -> bool:
    """Check if a file path matches a domain file_patterns glob entry."""
    import fnmatch  # noqa: PLC0415

    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return fpath.startswith(prefix + "/") or fpath == prefix
    return fnmatch.fnmatch(fpath, pattern)


def _build_reviewer_hints(root: Path, impacted_paths: list[str]) -> list[str]:
    """Derive rule file hints from impacted files and domain manifests."""
    from agentscaffold.domain_packs.loader import (  # noqa: PLC0415
        _get_available_packs,
        _load_manifest,
    )

    hints: list[str] = []

    agentscaffold_rule = root / ".cursor" / "rules" / "agentscaffold.md"
    if agentscaffold_rule.is_file():
        hints.append(".cursor/rules/agentscaffold.md")

    matched_standards: set[str] = set()
    for pack in _get_available_packs():
        try:
            manifest = _load_manifest(pack)
        except FileNotFoundError:
            continue
        patterns = manifest.get("file_patterns", [])
        if not patterns:
            continue
        for fpath in impacted_paths:
            if any(_file_matches_domain_pattern(fpath, p) for p in patterns):
                matched_standards.update(manifest.get("standards", []))
                break

    for std in sorted(matched_standards):
        std_path = root / "docs" / "ai" / "standards" / f"{std}.md"
        if std_path.is_file():
            hints.append(f"docs/ai/standards/{std}.md")

    return hints


def _tool_prepare_review(
    store: Any, arguments: dict[str, Any], meta: dict, root: Path, config: Any
) -> dict[str, Any]:
    """Composite: full review context for a plan."""
    from agentscaffold.graph.findings import get_open_findings  # noqa: PLC0415
    from agentscaffold.review.brief import format_brief_markdown, generate_brief
    from agentscaffold.review.challenges import format_challenges_markdown, generate_challenges
    from agentscaffold.review.gaps import format_gaps_markdown, generate_gaps
    from agentscaffold.review.queries import (
        get_adrs_for_plan,
        get_plan_dependencies,
        get_spikes_for_plan,
        get_studies_for_plan,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    brief = generate_brief(store, pn)
    challenges = generate_challenges(store, pn)
    gaps = generate_gaps(store, pn)

    # Collect impacted paths from the brief (avoids a redundant graph query)
    impacted_paths = [fp["path"] for fp in brief.get("file_profiles", []) if fp.get("path")]

    # Open findings: plan-scoped first, then file-scoped (deduplicated)
    plan_findings = get_open_findings(store, plan_number=pn, limit=20)
    seen_ids: set[str] = {r.get("rf.id", "") for r in plan_findings}
    file_findings: list[dict] = []
    for fpath in impacted_paths[:10]:
        for row in get_open_findings(store, file_path=fpath, limit=5):
            fid = row.get("rf.id", "")
            if fid not in seen_ids:
                seen_ids.add(fid)
                file_findings.append(row)
    all_findings = sorted(plan_findings + file_findings, key=_sev_key)[:20]

    reviewer_hints = _build_reviewer_hints(root, impacted_paths)

    return {
        "plan_number": pn,
        "brief": brief,
        "brief_markdown": format_brief_markdown(brief),
        "challenges": [
            {"category": c.category, "text": c.text, "severity": c.severity} for c in challenges
        ],
        "challenges_markdown": format_challenges_markdown(challenges),
        "gaps": [{"category": g.category, "text": g.text, "severity": g.severity} for g in gaps],
        "gaps_markdown": format_gaps_markdown(gaps),
        "governing_adrs": get_adrs_for_plan(store, pn),
        "validation_spikes": get_spikes_for_plan(store, pn),
        "related_studies": get_studies_for_plan(store, pn),
        "dependencies": get_plan_dependencies(store, pn),
        "open_findings": all_findings,
        "reviewer_hints": reviewer_hints,
        "meta": meta,
    }


def _tool_prepare_implementation(
    store: Any, arguments: dict[str, Any], meta: dict, root: Path
) -> dict[str, Any]:
    """Composite: implementation preparation for a plan."""
    from agentscaffold.review.brief import generate_brief
    from agentscaffold.review.queries import (
        get_contracts_for_file,
        get_file_importers,
        get_plan_dependencies,
        get_plan_impacted_files,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    brief = generate_brief(store, pn)
    impacted = get_plan_impacted_files(store, pn)
    deps = get_plan_dependencies(store, pn)

    per_file: list[dict[str, Any]] = []
    for f in impacted:
        fpath = f.get("f.path", "")
        importers = get_file_importers(store, fpath)
        contracts = get_contracts_for_file(store, fpath)
        per_file.append(
            {
                "path": fpath,
                "change_type": f.get("r.changeType", ""),
                "consumer_count": len(importers),
                "consumers": [i.get("a.path", "") for i in importers[:10]],
                "contracts": [c.get("c.name", "") for c in contracts],
            }
        )

    return {
        "plan_number": pn,
        "brief": brief,
        "impacted_files": per_file,
        "dependencies": deps,
        "dep_status": [
            {"plan": d.get("dep.number"), "status": d.get("dep.status", "unknown")} for d in deps
        ],
        "meta": meta,
    }


def _tool_compare_plans(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: compare two plans for overlap and conflicts."""
    from agentscaffold.review.queries import get_plan_by_number, get_plan_impacted_files

    pa = arguments.get("plan_a")
    pb = arguments.get("plan_b")
    if pa is None or pb is None:
        return {"error": "plan_a and plan_b are required.", "meta": meta}

    plan_a = get_plan_by_number(store, pa)
    plan_b = get_plan_by_number(store, pb)
    if not plan_a:
        return {"error": f"Plan {pa} not found.", "meta": meta}
    if not plan_b:
        return {"error": f"Plan {pb} not found.", "meta": meta}

    files_a = {f.get("f.path", "") for f in get_plan_impacted_files(store, pa)}
    files_b = {f.get("f.path", "") for f in get_plan_impacted_files(store, pb)}

    shared = files_a & files_b
    only_a = files_a - files_b
    only_b = files_b - files_a

    return {
        "plan_a": {"number": pa, "title": plan_a.get("p.title"), "status": plan_a.get("p.status")},
        "plan_b": {"number": pb, "title": plan_b.get("p.title"), "status": plan_b.get("p.status")},
        "shared_files": sorted(shared),
        "only_in_a": sorted(only_a),
        "only_in_b": sorted(only_b),
        "overlap_count": len(shared),
        "conflict_risk": "high" if len(shared) > 3 else "medium" if shared else "low",
        "meta": meta,
    }


def _tool_staleness_check(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: check if a plan is stale."""
    from agentscaffold.review.queries import (
        get_all_plans,
        get_plan_by_number,
        get_plan_impacted_files,
        get_studies_for_plan,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    plan = get_plan_by_number(store, pn)
    if not plan:
        return {"error": f"Plan {pn} not found.", "meta": meta}

    impacted = get_plan_impacted_files(store, pn)
    plan_files = {f.get("f.path", "") for f in impacted}

    all_plans = get_all_plans(store)
    overlapping_completed = []
    for p in all_plans:
        other_num = p.get("p.number")
        if other_num == pn or p.get("p.status", "").lower() != "complete":
            continue
        other_files = {f.get("f.path", "") for f in get_plan_impacted_files(store, other_num)}
        overlap = plan_files & other_files
        if overlap:
            overlapping_completed.append(
                {
                    "plan": other_num,
                    "title": p.get("p.title"),
                    "shared_files": sorted(overlap),
                }
            )

    studies = get_studies_for_plan(store, pn)

    signals: list[str] = []
    if overlapping_completed:
        signals.append(f"{len(overlapping_completed)} completed plans overlap with impacted files")
    if studies:
        for s in studies:
            outcome = s.get("s.outcome", "")
            if outcome and "baseline" in outcome.lower():
                signals.append(
                    f"Study {s.get('s.studyId')} outcome '{outcome}' may contradict approach"
                )

    return {
        "plan_number": pn,
        "plan_title": plan.get("p.title"),
        "plan_status": plan.get("p.status"),
        "last_updated": plan.get("p.lastUpdated"),
        "stale_signals": signals,
        "is_stale": bool(signals),
        "overlapping_completed_plans": overlapping_completed,
        "related_studies": [
            {"id": s.get("s.studyId"), "outcome": s.get("s.outcome")} for s in studies
        ],
        "meta": meta,
    }


def _tool_prepare_rewrite(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: superset of staleness check plus rewrite context."""
    staleness = _tool_staleness_check(store, arguments, meta)

    from agentscaffold.review.queries import get_all_plans, get_plan_dependencies

    pn = arguments.get("plan_number")
    deps = get_plan_dependencies(store, pn)

    all_plans = get_all_plans(store)
    recent_completed = [
        {"number": p.get("p.number"), "title": p.get("p.title")}
        for p in all_plans
        if p.get("p.status", "").lower() == "complete"
    ][:10]

    staleness["dependencies"] = deps
    staleness["recent_completed_plans"] = recent_completed
    return staleness


def _tool_prepare_retro(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: retrospective context for a completed plan."""
    from agentscaffold.review.feedback import format_retro_markdown, generate_retro_enrichment
    from agentscaffold.review.queries import get_plan_by_number, get_studies_for_plan
    from agentscaffold.review.verify import format_verification_markdown, verify_implementation

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    plan = get_plan_by_number(store, pn)
    if not plan:
        return {"error": f"Plan {pn} not found.", "meta": meta}

    items = verify_implementation(store, pn)
    insights = generate_retro_enrichment(store, pn)
    studies = get_studies_for_plan(store, pn)

    return {
        "plan_number": pn,
        "plan_title": plan.get("p.title"),
        "verification": [{"check": i.check, "status": i.status, "detail": i.detail} for i in items],
        "verification_markdown": format_verification_markdown(items),
        "retro_insights": [{"category": i.category, "text": i.text} for i in insights],
        "retro_markdown": format_retro_markdown(insights),
        "related_studies": [
            {"id": s.get("s.studyId"), "title": s.get("s.title"), "outcome": s.get("s.outcome")}
            for s in studies
        ],
        "meta": meta,
    }


def _parse_workflow_state(root: Path, config: Any) -> dict[str, Any]:
    """Live-parse workflow_state.md for current project status."""
    if config and hasattr(config, "graph"):
        ws_path = root / config.graph.workflow_state_file
    else:
        ws_path = root / "docs" / "ai" / "state" / "workflow_state.md"

    if not ws_path.is_file():
        return {"error": "workflow_state.md not found", "path": str(ws_path)}

    text = ws_path.read_text(errors="replace")
    result: dict[str, Any] = {"path": str(ws_path)}

    blockers_m = re.search(
        r"^##\s+Blockers?\s*\n(.*?)(?=\n##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    result["blockers"] = blockers_m.group(1).strip() if blockers_m else "None"

    next_m = re.search(
        r"^##\s+Next\s+Steps?\s*\n(.*?)(?=\n##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    result["next_steps"] = next_m.group(1).strip() if next_m else "None"

    current_m = re.search(
        r"^##\s+Current\s+Implementation\s*\n(.*?)(?=\n##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    result["current_implementation"] = current_m.group(1).strip() if current_m else "None"

    in_progress: list[str] = []
    for m in re.finditer(r"Plan\s+(\d+).*?In\s*Progress", text, re.IGNORECASE):
        in_progress.append(m.group(1))
    result["in_progress_plans"] = in_progress

    return result


def _tool_orient(store: Any, meta: dict, root: Path, config: Any) -> dict[str, Any]:
    """Composite: session orientation with stats + workflow state."""
    from agentscaffold.review.queries import (
        get_all_adrs,
        get_all_plans,
        get_all_studies,
        get_hot_files,
    )

    stats = store.get_stats()
    plans = get_all_plans(store)
    hot_files = get_hot_files(store, limit=5)
    studies = get_all_studies(store)
    adrs = get_all_adrs(store)
    workflow = _parse_workflow_state(root, config)

    recent_plans = plans[:10]

    return {
        "stats": stats,
        "recent_plans": recent_plans,
        "hot_files": hot_files,
        "recent_studies": studies[:5],
        "active_adrs": [
            a for a in adrs if a.get("a.status", "").lower() not in ("superseded", "deprecated")
        ],
        "workflow_state": workflow,
        "meta": meta,
    }


def _tool_find_studies(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: search studies by topic and/or outcome."""
    from agentscaffold.review.queries import get_studies_by_outcome, get_studies_by_tags

    topic = arguments.get("topic", "")
    outcome = arguments.get("outcome")

    results: list[dict[str, Any]] = []
    if topic:
        results = get_studies_by_tags(store, [topic])

    if outcome:
        outcome_results = get_studies_by_outcome(store, outcome)
        if results:
            existing_ids = {r.get("s.studyId") for r in results}
            for o in outcome_results:
                if o.get("s.studyId") not in existing_ids:
                    results.append(o)
        else:
            results = outcome_results

    return {
        "topic": topic,
        "outcome_filter": outcome,
        "studies": results,
        "count": len(results),
        "meta": meta,
    }


def _tool_prior_experiments(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: all experiments related to a plan."""
    from agentscaffold.review.queries import (
        get_plan_impacted_files,
        get_studies_for_file,
        get_studies_for_plan,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    direct = get_studies_for_plan(store, pn)

    impacted = get_plan_impacted_files(store, pn)
    file_studies: list[dict[str, Any]] = []
    seen_ids: set[str] = {s.get("s.studyId", "") for s in direct}
    for f in impacted:
        fpath = f.get("f.path", "")
        for s in get_studies_for_file(store, fpath):
            sid = s.get("s.studyId", "")
            if sid not in seen_ids:
                seen_ids.add(sid)
                file_studies.append(s)

    return {
        "plan_number": pn,
        "directly_referenced": direct,
        "file_overlap_studies": file_studies,
        "total_count": len(direct) + len(file_studies),
        "meta": meta,
    }


def _tool_find_adrs(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: search ADRs by topic keyword and/or status."""
    from agentscaffold.review.queries import get_all_adrs

    topic = arguments.get("topic", "")
    status_filter = arguments.get("status")

    all_adrs = get_all_adrs(store)
    results = all_adrs

    if topic:
        topic_lower = topic.lower()
        results = [a for a in results if topic_lower in a.get("a.title", "").lower()]

    if status_filter:
        status_lower = status_filter.lower()
        results = [a for a in results if status_lower in a.get("a.status", "").lower()]

    return {
        "topic": topic,
        "status_filter": status_filter,
        "adrs": results,
        "count": len(results),
        "meta": meta,
    }


def _tool_decision_context(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: full decision chain for a plan (ADRs, spikes, studies, deps)."""
    from agentscaffold.review.queries import (
        get_adrs_for_plan,
        get_plan_by_number,
        get_plan_dependencies,
        get_spikes_for_plan,
        get_studies_for_plan,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    plan = get_plan_by_number(store, pn)
    if not plan:
        return {"error": f"Plan {pn} not found.", "meta": meta}

    adrs = get_adrs_for_plan(store, pn)
    spikes = get_spikes_for_plan(store, pn)
    studies = get_studies_for_plan(store, pn)
    deps = get_plan_dependencies(store, pn)

    return {
        "plan_number": pn,
        "plan_title": plan.get("p.title"),
        "plan_status": plan.get("p.status"),
        "governing_adrs": adrs,
        "validation_spikes": spikes,
        "supporting_studies": studies,
        "plan_dependencies": deps,
        "has_full_decision_chain": bool(adrs or spikes or studies),
        "meta": meta,
    }


def _tool_record_finding(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Record a review finding in the knowledge graph."""
    from agentscaffold.graph.findings import record_finding  # noqa: PLC0415

    plan_number = arguments.get("plan_number")
    review_type = arguments.get("review_type", "")
    category = arguments.get("category", "")
    finding = arguments.get("finding", "")

    if not all([plan_number is not None, review_type, category, finding]):
        return {
            "error": "plan_number, review_type, category, and finding are required.",
            "meta": meta,
        }

    result = record_finding(
        store,
        plan_number=int(plan_number),
        review_type=review_type,
        category=category,
        finding=finding,
        severity=arguments.get("severity", "medium"),
        file_paths=arguments.get("file_paths") or [],
        function_ids=arguments.get("function_ids") or [],
    )
    result["meta"] = meta
    return result


def _tool_resolve_finding(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Mark a ReviewFinding as resolved."""
    from agentscaffold.graph.findings import resolve_finding  # noqa: PLC0415

    finding_id = arguments.get("finding_id", "")
    resolution = arguments.get("resolution", "")

    if not finding_id or not resolution:
        return {"error": "finding_id and resolution are required.", "meta": meta}

    result = resolve_finding(store, finding_id, resolution=resolution)
    result["meta"] = meta
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
            from agentscaffold.graph.query_compat import ql

            layers = ql(
                store,
                sql=(
                    'SELECT number AS "l.number", '
                    'name AS "l.name", '
                    'pathPatterns AS "l.pathPatterns" '
                    "FROM ArchitectureLayer ORDER BY number"
                ),
            )
            return {"layers": layers}

        return {"error": f"Unknown resource: {uri}"}

    finally:
        store.close()
