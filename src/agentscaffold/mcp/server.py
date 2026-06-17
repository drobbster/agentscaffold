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
    "scaffold_search": [
        "search the workspace for X",
        "search across all projects for X",
        "find code related to X",
        "find duplicates across projects",
        "look for duplicate code in the workspace",
        "search all projects for similar implementations",
        "look across every project for similar implementations",
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
    "scaffold_record_findings_batch": [
        "record all findings",
        "log all findings",
        "record findings batch",
        "record multiple findings",
        "save all review findings",
        "batch record findings",
        "record findings in the plan appendix",
        "log these findings",
        "capture all findings",
        "write all findings to graph",
    ],
    "scaffold_record_backlog_item": [
        "add backlog item",
        "record backlog item",
        "log backlog item",
        "add to backlog",
        "create backlog item",
        "note backlog item",
        "track backlog item",
    ],
    "scaffold_resolve_backlog_item": [
        "resolve backlog item",
        "close backlog item",
        "mark backlog item done",
        "complete backlog item",
        "archive backlog item",
        "mark backlog item complete",
        "backlog item is done",
    ],
    "scaffold_begin_plan": [
        "begin plan X",
        "start plan X",
        "kick off plan X",
        "let's start implementation of plan X",
        "run the pre-reviews for plan X",
        "follow the collab protocol to begin plan X",
        "pre-review chain for plan X",
        "run begin plan for plan X",
    ],
    "scaffold_complete_plan": [
        "wrap up plan X",
        "complete plan X",
        "post-implementation for plan X",
        "close out plan X",
        "run the retro for plan X",
        "follow the collab protocol to close plan X",
        "run complete plan for plan X",
        "finish plan X",
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
    "scaffold_search": {"search", "find", "workspace", "projects", "duplicate", "similar"},
    "scaffold_record_finding": {"record", "log", "finding", "discovered", "issue", "capture"},
    "scaffold_resolve_finding": {"resolve", "resolved", "close", "fixed", "addressed"},
    "scaffold_record_findings_batch": {"batch", "all", "findings", "multiple", "appendix"},
    "scaffold_record_backlog_item": {"backlog", "item", "add", "create", "track"},
    "scaffold_resolve_backlog_item": {"backlog", "done", "complete", "archive", "resolved"},
    "scaffold_begin_plan": {"begin", "kick", "pre", "reviews", "collab", "protocol", "start"},
    "scaffold_complete_plan": {"wrap", "close", "post", "retro", "finish", "complete"},
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
                "Get call-graph context for a symbol: its definition, the "
                "functions and methods that call it (callers), and the functions "
                "it calls (callees). Returns a 'markdown' summary plus structured "
                "lists."
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
                "Analyze the blast radius of changing a file. Walks IMPORTS edges "
                "up to 'depth' hops to find transitive importing files, and lists "
                "the functions and methods that call into the file. Returns a "
                "'markdown' summary plus structured lists."
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
                    "kind": {
                        "type": "string",
                        "enum": ["code", "governance", "all"],
                        "description": "Search corpus (default: code)",
                        "default": "code",
                    },
                    "rerank": {
                        "type": "boolean",
                        "description": "Rerank final results with the configured cross-encoder",
                        "default": False,
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Target a specific project in a multi-project workspace "
                            "(defaults to the current project)"
                        ),
                    },
                    "all_projects": {
                        "type": "boolean",
                        "description": "Search across every project in the workspace",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="scaffold_recall_governance",
            description=(
                "Semantically recall prior governance knowledge (plans, findings, "
                "learnings, ADRs, studies, spikes, backlog) for a natural-language query."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language recall query"},
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
                    "project": {
                        "type": "string",
                        "description": "Target a specific project in a multi-project workspace",
                    },
                    "all_projects": {
                        "type": "boolean",
                        "description": "Search governance across every project in the workspace",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="scaffold_validate",
            description=(
                "Run validation checks: layer conformance, contract drift, graph "
                "staleness, or graph coverage (parsed vs structurally-invisible files)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "check": {
                        "type": "string",
                        "enum": ["layers", "contracts", "staleness", "coverage"],
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
        Tool(
            name="scaffold_record_findings_batch",
            description=(
                "Record multiple ReviewFinding nodes in a single transaction. Use this "
                "when a review produces several findings at once (e.g. post-implementation "
                "review, plan appendix findings). More efficient than calling "
                "scaffold_record_finding N times."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {
                        "type": "integer",
                        "description": "Plan number all findings relate to",
                    },
                    "review_type": {
                        "type": "string",
                        "description": "Review type label (e.g. 'quant_architect', 'security')",
                    },
                    "findings": {
                        "type": "array",
                        "description": "List of finding objects",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string"},
                                "finding": {"type": "string"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high", "critical"],
                                },
                                "file_paths": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "function_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["category", "finding"],
                        },
                    },
                },
                "required": ["plan_number", "review_type", "findings"],
            },
        ),
        Tool(
            name="scaffold_record_backlog_item",
            description=(
                "Record one or more BacklogItem nodes in the knowledge graph. Use this "
                "alongside writing to backlog.md — the graph write is additive and enables "
                "backlog queries in orient and prepare_review. Pass 'items' (array) for "
                "batch recording (recommended), or 'title' for a single item."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {
                        "type": "integer",
                        "description": "Plan number all items relate to",
                    },
                    "items": {
                        "type": "array",
                        "description": "List of backlog item objects (batch mode)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "priority": {
                                    "type": "string",
                                    "enum": ["P1", "P2", "P3", "P4", "P5"],
                                },
                                "effort": {"type": "string"},
                                "source": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["open", "blocked", "unblockable"],
                                },
                            },
                            "required": ["title"],
                        },
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title for a single backlog item",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["P1", "P2", "P3", "P4", "P5"],
                        "description": "Priority for single-item mode (default: P3)",
                        "default": "P3",
                    },
                    "effort": {
                        "type": "string",
                        "description": "Effort estimate (e.g. 'Small (2h)', 'Medium (1d)')",
                    },
                    "source": {
                        "type": "string",
                        "description": "Review source reference (e.g. 'DA Future Regret', 'EX-8')",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "blocked", "unblockable"],
                        "description": "Initial status for single-item mode (default: open)",
                        "default": "open",
                    },
                },
                "required": ["plan_number"],
            },
        ),
        Tool(
            name="scaffold_resolve_backlog_item",
            description=(
                "Mark a BacklogItem as archived (completed). Use this when a backlog item "
                "is done and being moved from backlog.md to backlog_archive.md. The item "
                "remains in the graph with status='archived' for retrospective queries."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "The ID of the backlog item to archive",
                    },
                    "resolution": {
                        "type": "string",
                        "description": "Optional note describing how the item was completed",
                    },
                },
                "required": ["item_id"],
            },
        ),
        # --- Governed lifecycle composite tools ---
        Tool(
            name="scaffold_begin_plan",
            description=(
                "Run the full pre-implementation review chain for a plan: orient, "
                "prepare_review (all three perspectives), auto-write challenges and gaps "
                "as ReviewFindings to the graph, stamp Plan.reviewedAt. Returns structured "
                "output with orient summary, review perspectives, findings written, and a "
                "proceed_prompt for the agent to present to the user."
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
            name="scaffold_complete_plan",
            description=(
                "Run the full post-implementation chain for a plan: prepare_retro, "
                "auto-write retro insights as ReviewFindings, optionally write backlog items. "
                "Returns structured output with retro results, findings written, structured "
                "learnings, and a completion checklist for the agent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                    "backlog_items": {
                        "type": "array",
                        "description": "Optional backlog items to record",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "priority": {
                                    "type": "string",
                                    "enum": ["P1", "P2", "P3", "P4", "P5"],
                                },
                                "effort": {"type": "string"},
                                "source": {"type": "string"},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["plan_number"],
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
    from agentscaffold.graph import GraphLockError, graph_available, open_graph

    config = load_config()
    if not graph_available(config):
        return {"error": "No knowledge graph found. Run 'scaffold index' first."}

    try:
        store = open_graph(config)
    except GraphLockError as exc:
        return {"error": str(exc), "graph_locked": True}
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {"error": f"Failed to open knowledge graph: {exc}"}
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
            if str(arguments.get("mode", "hybrid")).lower() in ("semantic", "hybrid"):
                from agentscaffold.graph.embeddings import configure_embeddings

                configure_embeddings(config.search.embedding_model, config.search.cache_dir)
            return _tool_search(store, arguments, meta)

        elif name == "scaffold_recall_governance":
            if str(arguments.get("mode", "hybrid")).lower() in ("semantic", "hybrid"):
                from agentscaffold.graph.embeddings import configure_embeddings

                configure_embeddings(config.search.embedding_model, config.search.cache_dir)
            return _tool_search(store, {**arguments, "kind": "governance"}, meta)

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

        elif name == "scaffold_record_findings_batch":
            return _tool_record_findings_batch(store, arguments, meta)

        elif name == "scaffold_record_backlog_item":
            return _tool_record_backlog_item(store, arguments, meta)

        elif name == "scaffold_resolve_backlog_item":
            return _tool_resolve_backlog_item(store, arguments, meta)

        elif name == "scaffold_begin_plan":
            return _tool_begin_plan(store, arguments, meta, root, config)

        elif name == "scaffold_complete_plan":
            return _tool_complete_plan(store, arguments, meta)

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
    try:
        from agentscaffold.graph.search import evaluate_retrieval

        meta.update(evaluate_retrieval(store, "hybrid"))
    except Exception:  # pragma: no cover - retrieval capability is best-effort
        pass
    return meta


def _tool_context(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_context tool call."""
    from agentscaffold.graph.query_compat import ql
    from agentscaffold.mcp.coverage import (
        count_heuristic,
        empty_result_caveat,
        language_for_path,
    )
    from agentscaffold.mcp.render import (
        clean_row,
        clean_rows,
        format_context_markdown,
    )

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

    node = clean_row(results[0])
    node_id = (node.get("id") or "").replace("'", "''")

    # Function callers (CALLS)
    callers = clean_rows(
        ql(
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
    )

    # Method callers (METHOD_CALLS): methods that call this function
    method_callers = clean_rows(
        ql(
            store,
            sql=(
                f'SELECT t.m_name AS "m.name", t.m_fp AS "m.filePath", '
                f't.r_conf AS "r.confidence" '
                f"FROM GRAPH_TABLE(agentscaffold_graph "
                f"MATCH (m:Method)-[r:METHOD_CALLS]->(fn:Function) "
                f"WHERE fn.id = '{node_id}' "
                f"COLUMNS (m.name AS m_name, m.filePath AS m_fp, "
                f"r.confidence AS r_conf)) t"
            ),
        )
    )

    # Callees (CALLS)
    callees = clean_rows(
        ql(
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
    )

    file_path = node.get("filePath") or ""
    config_consumers = _config_consumers(store, f"file::{file_path}") if file_path else []

    caller_count = len(callers) + len(method_callers)
    language = language_for_path(file_path)
    caveat = empty_result_caveat(
        target=node.get("name", symbol),
        language=language,
        result_count=caller_count + len(config_consumers),
        relation="callers",
    )

    return {
        "symbol": node,
        "callers": callers,
        "method_callers": method_callers,
        "callees": callees,
        "caller_count": caller_count,
        "callee_count": len(callees),
        "heuristic_caller_count": count_heuristic(callers) + count_heuristic(method_callers),
        "config_consumers": config_consumers,
        "config_consumer_count": len(config_consumers),
        "coverage": {"target_language": language, "caveat": caveat},
        "markdown": format_context_markdown(
            node,
            callers,
            callees,
            method_callers,
            caveat=caveat,
            config_consumers=config_consumers,
        ),
        "meta": meta,
    }


def _config_consumers(store: Any, file_id: str) -> list[dict[str, Any]]:
    """Return config files that reference *file_id* via CONFIG_REFERENCES edges."""
    from agentscaffold.graph.query_compat import ql
    from agentscaffold.mcp.render import clean_rows

    safe_file_id = file_id.replace("'", "''")
    return clean_rows(
        ql(
            store,
            sql=(
                f'SELECT DISTINCT t.cfg_path AS "cfg.path", '
                f't.ref_key AS "r.refKey", t.sym AS "r.symbol", '
                f't.conf AS "r.confidence" '
                f"FROM GRAPH_TABLE(agentscaffold_graph "
                f"MATCH (cfg:File)-[r:CONFIG_REFERENCES]->(f:File) "
                f"WHERE f.id = '{safe_file_id}' "
                f"COLUMNS (cfg.path AS cfg_path, r.refKey AS ref_key, "
                f"r.symbol AS sym, r.confidence AS conf)) t"
            ),
        )
    )


def _transitive_importers(store: Any, file_id: str, depth: int) -> list[list[dict[str, Any]]]:
    """Breadth-first walk of IMPORTS edges up to *depth* hops.

    Returns a list of levels; level ``i`` holds the files that reach the target
    in ``i + 1`` import hops. Files already seen at a shallower depth are not
    repeated, so each file appears at its shortest distance.
    """
    from agentscaffold.graph.query_compat import ql

    levels: list[list[dict[str, Any]]] = []
    seen: set[str] = {file_id}
    frontier: set[str] = {file_id}

    for _ in range(max(1, depth)):
        if not frontier:
            break
        ids_lit = ", ".join("'" + fid.replace("'", "''") + "'" for fid in frontier)
        rows = ql(
            store,
            sql=(
                f'SELECT DISTINCT t.a_id AS "a.id", t.a_path AS "a.path", '
                f't.a_lang AS "a.language" '
                f"FROM GRAPH_TABLE(agentscaffold_graph "
                f"MATCH (a:File)-[e:IMPORTS]->(b:File) "
                f"WHERE b.id IN ({ids_lit}) "
                f"COLUMNS (a.id AS a_id, a.path AS a_path, a.language AS a_lang)) t"
            ),
        )
        level: list[dict[str, Any]] = []
        next_frontier: set[str] = set()
        for row in rows:
            aid = row["a.id"]
            if aid in seen:
                continue
            seen.add(aid)
            next_frontier.add(aid)
            level.append({"path": row["a.path"], "language": row["a.language"]})
        levels.append(level)
        frontier = next_frontier

    return levels


def _tool_impact(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_impact tool call."""
    from agentscaffold.graph.query_compat import ql
    from agentscaffold.mcp.coverage import (
        count_heuristic,
        empty_result_caveat,
        is_parsed_language,
        language_for_path,
    )
    from agentscaffold.mcp.render import clean_rows, format_impact_markdown

    target = arguments.get("file_or_symbol", "")
    try:
        depth = int(arguments.get("depth", 2) or 2)
    except (TypeError, ValueError):
        depth = 2

    file_id = f"file::{target}"
    safe_file_id = file_id.replace("'", "''")

    # Transitive importers (multi-hop IMPORTS traversal)
    importers_by_level = _transitive_importers(store, file_id, depth)
    flat_importers = [row for level in importers_by_level for row in level]

    # Functions defined in this file and their function callers (CALLS)
    callers = clean_rows(
        ql(
            store,
            sql=(
                f'SELECT DISTINCT t.caller_fp AS "caller.filePath", '
                f't.caller_name AS "caller.name", t.r_conf AS "r.confidence" '
                f"FROM GRAPH_TABLE(agentscaffold_graph "
                f"MATCH (caller:Function)-[r:CALLS]->(fn:Function)"
                f"<-[e:DEFINES_FUNCTION]-(f:File) "
                f"WHERE f.id = '{safe_file_id}' "
                f"COLUMNS (caller.filePath AS caller_fp, "
                f"caller.name AS caller_name, "
                f"r.confidence AS r_conf)) t"
            ),
        )
    )

    # Methods that call functions defined in this file (METHOD_CALLS)
    method_callers = clean_rows(
        ql(
            store,
            sql=(
                f'SELECT DISTINCT t.m_fp AS "m.filePath", t.m_name AS "m.name", '
                f't.r_conf AS "r.confidence" '
                f"FROM GRAPH_TABLE(agentscaffold_graph "
                f"MATCH (m:Method)-[r:METHOD_CALLS]->(fn:Function)"
                f"<-[e:DEFINES_FUNCTION]-(f:File) "
                f"WHERE f.id = '{safe_file_id}' "
                f"COLUMNS (m.filePath AS m_fp, m.name AS m_name, "
                f"r.confidence AS r_conf)) t"
            ),
        )
    )

    config_consumers = _config_consumers(store, file_id)

    language = language_for_path(target)
    result_count = len(flat_importers) + len(callers) + len(method_callers) + len(config_consumers)
    caveat = empty_result_caveat(
        target=target,
        language=language,
        result_count=result_count,
        relation="importers or callers",
    )

    return {
        "target": target,
        "depth": depth,
        "direct_importers": importers_by_level[0] if importers_by_level else [],
        "transitive_importers": flat_importers,
        "importer_count": len(flat_importers),
        "callers_into_file": callers,
        "method_callers_into_file": method_callers,
        "caller_count": len(callers) + len(method_callers),
        "heuristic_caller_count": count_heuristic(callers) + count_heuristic(method_callers),
        "config_consumers": config_consumers,
        "config_consumer_count": len(config_consumers),
        "coverage": {
            "target_language": language,
            "parsed": is_parsed_language(language),
            "caveat": caveat,
        },
        "markdown": format_impact_markdown(
            target,
            importers_by_level,
            callers,
            method_callers,
            caveat=caveat,
            config_consumers=config_consumers,
        ),
        "meta": meta,
    }


def _tool_search(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Handle scaffold_search tool call (hybrid search)."""
    from agentscaffold.graph.search import (
        CODE_TABLES,
        GOVERNANCE_TABLES,
        evaluate_retrieval,
        format_search_results,
        hybrid_search,
    )

    query_text = arguments.get("query", "")
    mode = arguments.get("mode", "hybrid")
    top_k = arguments.get("top_k", 10)
    kind = arguments.get("kind", "code")
    rerank = bool(arguments.get("rerank", False))
    # Scope (Plan 225): defaults to the current project in a multi-project
    # workspace; clients may pass project / all_projects to retarget or federate.
    project = arguments.get("project") or None
    all_projects = bool(arguments.get("all_projects", False))

    # Recompute retrieval status for the actually-requested mode so the search
    # response reflects what ran (the meta snapshot used the default mode).
    meta = {**meta, **evaluate_retrieval(store, mode)}

    if kind == "code":
        tables = CODE_TABLES
    elif kind == "governance":
        tables = GOVERNANCE_TABLES
    elif kind == "all":
        tables = [*CODE_TABLES, *GOVERNANCE_TABLES]
    else:
        tables = CODE_TABLES

    results = hybrid_search(
        store,
        query_text,
        mode=mode,
        top_k=top_k,
        tables=tables,
        rerank=rerank,
        project=project,
        all_projects=all_projects,
    )

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

    if check == "coverage":
        from agentscaffold.mcp.coverage import repo_coverage

        return {"report": repo_coverage(store), "meta": meta}

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

    if root is None:
        return hints

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
        get_backlog_items_for_plan,
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
    open_backlog = get_backlog_items_for_plan(store, pn)

    return {
        "plan_number": pn,
        "brief": brief,
        "brief_markdown": format_brief_markdown(brief),
        "challenges": [
            {
                "category": c.category,
                "text": c.text,
                "severity": c.severity,
                "evidence": c.evidence,
            }
            for c in challenges
        ],
        "challenges_markdown": format_challenges_markdown(challenges),
        "gaps": [
            {
                "category": g.category,
                "text": g.text,
                "severity": g.severity,
                "evidence": g.evidence,
            }
            for g in gaps
        ],
        "gaps_markdown": format_gaps_markdown(gaps),
        "governing_adrs": get_adrs_for_plan(store, pn),
        "validation_spikes": get_spikes_for_plan(store, pn),
        "related_studies": get_studies_for_plan(store, pn),
        "dependencies": get_plan_dependencies(store, pn),
        "open_findings": all_findings,
        "open_backlog_items": open_backlog,
        "reviewer_hints": reviewer_hints,
        "meta": meta,
    }


def _tool_prepare_implementation(
    store: Any, arguments: dict[str, Any], meta: dict, root: Path
) -> dict[str, Any]:
    """Composite: implementation preparation for a plan."""
    from agentscaffold.config import load_config as _load_config  # noqa: PLC0415
    from agentscaffold.review.brief import generate_brief
    from agentscaffold.review.queries import (
        get_contracts_for_file,
        get_file_importers,
        get_plan_dependencies,
        get_plan_impacted_files,
        get_plan_reviewed_at,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    # --- Strict gate: check Plan.reviewedAt when gate_strict is enabled ---
    try:
        cfg = _load_config()
        if cfg.freshness.gate_strict and bool(arguments.get("gate_transition")):
            reviewed_at = get_plan_reviewed_at(store, pn)
            if reviewed_at is None:
                return {
                    "error": (
                        f"scaffold_begin_plan must be called before implementation of Plan {pn}. "
                        "The pre-review chain has not been completed (Plan.reviewedAt is NULL). "
                        "Run 'begin plan {pn}' first."
                    ),
                    "gate_deferred": True,
                    "meta": meta,
                }
    except Exception:  # noqa: BLE001
        pass  # Config load failure should not block implementation

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
    from agentscaffold.mcp.coverage import repo_coverage
    from agentscaffold.review.queries import (
        get_all_adrs,
        get_all_plans,
        get_all_studies,
        get_hot_files,
        get_open_backlog_items,
    )

    stats = store.get_stats()
    coverage = repo_coverage(store)
    plans = get_all_plans(store)
    hot_files = get_hot_files(store, limit=5)
    studies = get_all_studies(store)
    adrs = get_all_adrs(store)
    workflow = _parse_workflow_state(root, config)

    recent_plans = plans[:10]

    open_backlog = get_open_backlog_items(store, limit=3)

    try:
        count_rows = store.query(
            "SELECT COUNT(*) AS cnt FROM BacklogItem"
            " WHERE status NOT IN ('archived', 'unblockable')"
        )
        open_backlog_count = count_rows[0]["cnt"] if count_rows else 0
    except Exception:
        open_backlog_count = 0

    return {
        "stats": stats,
        "coverage": coverage,
        "recent_plans": recent_plans,
        "hot_files": hot_files,
        "recent_studies": studies[:5],
        "active_adrs": [
            a for a in adrs if a.get("a.status", "").lower() not in ("superseded", "deprecated")
        ],
        "workflow_state": workflow,
        "open_backlog_count": open_backlog_count,
        "open_backlog_top3": open_backlog,
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


def _tool_record_findings_batch(
    store: Any, arguments: dict[str, Any], meta: dict
) -> dict[str, Any]:
    """Record multiple ReviewFindings in one transaction."""
    from agentscaffold.graph.findings import record_findings_batch  # noqa: PLC0415

    plan_number = arguments.get("plan_number")
    review_type = arguments.get("review_type", "")
    findings = arguments.get("findings") or []

    if plan_number is None or not review_type:
        return {"error": "plan_number and review_type are required.", "meta": meta}

    if not isinstance(findings, list):
        return {"error": "'findings' must be a list.", "meta": meta}

    result = record_findings_batch(
        store,
        plan_number=int(plan_number),
        review_type=review_type,
        findings=findings,
    )
    result["meta"] = meta
    return result


def _tool_record_backlog_item(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Record one or more BacklogItem nodes (batch or single mode)."""
    from agentscaffold.graph.backlog import (  # noqa: PLC0415
        record_backlog_item,
        record_backlog_items_batch,
    )

    plan_number = arguments.get("plan_number")
    if plan_number is None:
        return {"error": "plan_number is required.", "meta": meta}

    items = arguments.get("items")
    if items is not None:
        # Batch mode
        if not isinstance(items, list):
            return {"error": "'items' must be a list.", "meta": meta}
        result = record_backlog_items_batch(
            store,
            plan_number=int(plan_number),
            items=items,
        )
        result["meta"] = meta
        return result

    # Single-item mode (backwards compatible)
    title = arguments.get("title", "")
    if not title:
        return {"error": "Either 'items' (array) or 'title' (string) is required.", "meta": meta}

    result = record_backlog_item(
        store,
        plan_number=int(plan_number),
        title=title,
        priority=arguments.get("priority", "P3"),
        effort=arguments.get("effort", ""),
        source=arguments.get("source", ""),
        status=arguments.get("status", "open"),
    )
    result["meta"] = meta
    return result


def _tool_resolve_backlog_item(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Mark a BacklogItem as archived (completed)."""
    from agentscaffold.graph.backlog import resolve_backlog_item  # noqa: PLC0415

    item_id = arguments.get("item_id", "")
    if not item_id:
        return {"error": "item_id is required.", "meta": meta}

    result = resolve_backlog_item(
        store,
        item_id,
        resolution=arguments.get("resolution", ""),
    )
    result["meta"] = meta
    return result


# ---------------------------------------------------------------------------
# Governed lifecycle composite handlers (Plan 152)
# ---------------------------------------------------------------------------


def _finding_file_paths(evidence: Any) -> list[str]:
    """Extract file paths from a challenge/gap evidence dict.

    Used to link auto-recorded ReviewFindings to File nodes via
    FINDING_ABOUT_FILE edges, which the [PATTERN] recurring-finding detector
    (challenges._check_patterns) traverses. Without these links, accumulated
    findings would never compound into reviewer memory.
    """
    if not isinstance(evidence, dict):
        return []
    paths: list[str] = []

    single = evidence.get("file")
    if isinstance(single, str) and single:
        paths.append(single)

    # Dict-valued evidence whose keys are file paths.
    for key in ("files", "sample", "upstream_deps"):
        val = evidence.get(key)
        if isinstance(val, dict):
            paths.extend(k for k in val if isinstance(k, str))

    # List of file paths.
    missing = evidence.get("missing_test_files")
    if isinstance(missing, list):
        paths.extend(p for p in missing if isinstance(p, str))

    # List of {"path": ...} consumer dicts.
    consumers = evidence.get("unlisted_consumers")
    if isinstance(consumers, list):
        paths.extend(
            c["path"] for c in consumers if isinstance(c, dict) and isinstance(c.get("path"), str)
        )

    # Deduplicate, preserve order, cap to keep finding writes bounded.
    seen: list[str] = []
    for p in paths:
        if p and p not in seen:
            seen.append(p)
    return seen[:10]


def _tool_begin_plan(
    store: Any, arguments: dict[str, Any], meta: dict, root: Path, config: Any
) -> dict[str, Any]:
    """Composite: full pre-implementation review chain.

    1. Graph-health pre-check
    2. Orient (compact summary)
    3. Prepare review (all three perspectives)
    4. Auto-write challenges + gaps as ReviewFindings (review_type='pre_review')
    5. Stamp Plan.reviewedAt
    6. Return structured output with proceed_prompt
    """
    from agentscaffold.graph.findings import record_findings_batch  # noqa: PLC0415
    from agentscaffold.review.queries import stamp_plan_reviewed  # noqa: PLC0415

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    # --- Graph-health pre-check ---
    stats = store.get_stats()
    graph_warning = None
    if stats.get("files", 0) == 0 and stats.get("plans", 0) == 0:
        graph_warning = (
            "Graph appears empty (0 files, 0 plans). "
            "Run 'scaffold index' to populate the graph before relying on review output."
        )

    # --- Compact orient summary ---
    orient_summary = {
        "schema_version": stats.get("schema_version"),
        "files": stats.get("files", 0),
        "functions": stats.get("functions", 0),
        "plans": stats.get("plans", 0),
        "pipeline_state": stats.get("pipeline_state", "unknown"),
    }

    # --- Run prepare_review internally ---
    review_args = {"plan_number": pn}
    review_result = _tool_prepare_review(store, review_args, meta, root, config)
    if "error" in review_result:
        return {
            "error": f"prepare_review failed: {review_result['error']}",
            "orient": orient_summary,
            "graph_warning": graph_warning,
            "meta": meta,
        }

    # --- Map challenges + gaps to findings format and write to graph ---
    findings_to_write: list[dict[str, Any]] = []
    for c in review_result.get("challenges", []):
        findings_to_write.append(
            {
                "category": c.get("category", "challenge"),
                "finding": c.get("text", ""),
                "severity": c.get("severity", "medium"),
                "file_paths": _finding_file_paths(c.get("evidence")),
            }
        )
    for g in review_result.get("gaps", []):
        findings_to_write.append(
            {
                "category": g.get("category", "gap"),
                "finding": g.get("text", ""),
                "severity": g.get("severity", "medium"),
                "file_paths": _finding_file_paths(g.get("evidence")),
            }
        )

    findings_written = {"ids": [], "count": 0}
    if findings_to_write:
        findings_written = record_findings_batch(
            store,
            plan_number=pn,
            review_type="pre_review",
            findings=findings_to_write,
        )

    # --- Stamp Plan.reviewedAt ---
    reviewed_at = stamp_plan_reviewed(store, pn)

    # --- Build proceed_prompt ---
    n_findings = findings_written["count"]
    proceed_prompt = (
        f"Pre-review complete for Plan {pn}. "
        f"{n_findings} findings recorded to graph. "
        "Ready to proceed with implementation, or would you like to discuss anything first?"
    )

    return {
        "plan_number": pn,
        "orient": orient_summary,
        "graph_warning": graph_warning,
        "pre_review": {
            "brief": review_result.get("brief"),
            "brief_markdown": review_result.get("brief_markdown"),
            "challenges": review_result.get("challenges"),
            "challenges_markdown": review_result.get("challenges_markdown"),
            "gaps": review_result.get("gaps"),
            "gaps_markdown": review_result.get("gaps_markdown"),
            "governing_adrs": review_result.get("governing_adrs"),
            "open_findings": review_result.get("open_findings"),
            "open_backlog_items": review_result.get("open_backlog_items"),
        },
        "findings_written": {
            "ids": findings_written.get("ids", []),
            "count": n_findings,
        },
        "reviewed_at": reviewed_at,
        "proceed_prompt": proceed_prompt,
        "meta": meta,
    }


def _tool_complete_plan(store: Any, arguments: dict[str, Any], meta: dict) -> dict[str, Any]:
    """Composite: full post-implementation chain.

    1. Graph-health pre-check
    2. Prepare retro (verification + enrichment)
    3. Auto-write retro insights as ReviewFindings (review_type='post_retro')
    4. Write backlog items if provided
    5. Return structured output with structured_learnings + completion_checklist
    """
    from agentscaffold.graph.backlog import record_backlog_items_batch  # noqa: PLC0415
    from agentscaffold.graph.findings import record_findings_batch  # noqa: PLC0415

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    # --- Graph-health pre-check ---
    stats = store.get_stats()
    graph_warning = None
    if stats.get("files", 0) == 0 and stats.get("plans", 0) == 0:
        graph_warning = "Graph appears empty (0 files, 0 plans). Retro output may be incomplete."

    # --- Run prepare_retro internally ---
    retro_args = {"plan_number": pn}
    retro_result = _tool_prepare_retro(store, retro_args, meta)
    if "error" in retro_result:
        return {
            "error": f"prepare_retro failed: {retro_result['error']}",
            "graph_warning": graph_warning,
            "meta": meta,
        }

    # --- Write retro insights as ReviewFindings ---
    retro_findings: list[dict[str, str]] = []
    for insight in retro_result.get("retro_insights", []):
        retro_findings.append(
            {
                "category": insight.get("category", "retro"),
                "finding": insight.get("text", ""),
                "severity": "medium",
            }
        )

    findings_written = {"ids": [], "count": 0}
    if retro_findings:
        findings_written = record_findings_batch(
            store,
            plan_number=pn,
            review_type="post_retro",
            findings=retro_findings,
        )

    # --- Write backlog items if provided ---
    backlog_items_arg = arguments.get("backlog_items")
    backlog_written = {"ids": [], "count": 0}
    if backlog_items_arg:
        backlog_written = record_backlog_items_batch(
            store,
            plan_number=pn,
            items=backlog_items_arg,
        )

    # --- Build structured_learnings from retro insights ---
    structured_learnings = [
        {
            "plan_number": pn,
            "category": insight.get("category", "retro"),
            "description": insight.get("text", ""),
            "target": (
                "AGENTS.md" if "process" in insight.get("category", "").lower() else "standards"
            ),
            "status": "pending",
        }
        for insight in retro_result.get("retro_insights", [])
    ]

    completion_checklist = [
        "Write learnings to docs/ai/state/learnings_tracker.md",
        "Write any new backlog items to docs/ai/backlog.md",
        "Update docs/ai/state/workflow_state.md plan status",
        "Mark completed steps in the plan file",
        "Write retro summary to plan appendix",
    ]

    return {
        "plan_number": pn,
        "graph_warning": graph_warning,
        "retro": {
            "verification": retro_result.get("verification"),
            "verification_markdown": retro_result.get("verification_markdown"),
            "retro_insights": retro_result.get("retro_insights"),
            "retro_markdown": retro_result.get("retro_markdown"),
            "related_studies": retro_result.get("related_studies"),
        },
        "findings_written": {
            "ids": findings_written.get("ids", []),
            "count": findings_written["count"],
        },
        "backlog_items_written": {
            "ids": backlog_written.get("ids", []),
            "count": backlog_written["count"],
        },
        "structured_learnings": structured_learnings,
        "completion_checklist": completion_checklist,
        "meta": meta,
    }


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
