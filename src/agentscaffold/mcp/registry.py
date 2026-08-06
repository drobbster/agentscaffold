"""Enumerable registry of the MCP tool surface.

The single source of truth for which tools exist and what they advertise. The
server renders these into ``mcp.types.Tool`` objects; the conformance suite
parametrises over them; the agent-file generator reads them for routing.

**This module imports nothing from ``mcp``.** The MCP SDK is an optional
dependency, and the generator has to enumerate the tool surface whether or not
it is installed, so the specs are plain data and the SDK types are applied by
the caller that needs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """One tool as advertised to an MCP client.

    ``input_schema`` is a JSON Schema object. It is rebuilt on every call to
    :func:`tool_specs` rather than shared, because callers historically mutated
    the schema in place to inject arguments.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


#: Advertised on every object-schema tool by :func:`tool_specs`.
#:
#: Per-call project scoping exists because the server runs from one fixed
#: directory and cannot infer which project the agent is editing. Declaring it
#: centrally keeps the 31 schemas from each having to remember it.
_WORKING_PATH_PROP = {
    "type": "string",
    "description": (
        "Optional. Absolute or workspace-relative path of the file or directory "
        "you are currently working on. In a multi-project workspace the server "
        "resolves the owning project from this path and scopes the call to it, so "
        "reads follow your active project even though the MCP server runs from a "
        "single fixed directory. Omit to use the server's default project, or pass "
        "project / all_projects explicitly."
    ),
}


#: Cross-project reads stay opt-in per call: the default scope is the one
#: project the call resolved to, and federation is something the agent asks for,
#: never something the server does silently on its behalf.
_SCOPE_PROPS = {
    "project": {
        "type": "string",
        "description": (
            "Target a specific project in a multi-project workspace "
            "(defaults to the project this call resolves to)"
        ),
    },
    "all_projects": {
        "type": "boolean",
        "description": (
            "Read across every project in the workspace. Each result carries a "
            "'project' field naming its origin."
        ),
        "default": False,
    },
}


def tool_specs() -> list[ToolSpec]:
    """Every tool the server advertises, with ``working_path`` already applied.

    Returns freshly-built specs so a caller that mutates a schema cannot affect
    the next caller.
    """
    specs = _tool_specs()
    for spec in specs:
        apply_uniform_args(spec.input_schema)
    return specs


def apply_uniform_args(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add the arguments every object-schema tool accepts, in place.

    Declaring ``working_path`` here rather than in 31 schemas is the reason a
    tool cannot be added without being scopeable. Left as a separate function so
    the edge cases stay directly testable: a caller that declared its own
    ``working_path`` keeps it, and a non-object schema is left alone rather than
    growing a ``properties`` key that means nothing there.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return schema
    props = schema.setdefault("properties", {})
    if isinstance(props, dict):
        props.setdefault("working_path", dict(_WORKING_PATH_PROP))
    return schema


def tool_names() -> tuple[str, ...]:
    """Names of every advertised tool, in advertised order."""
    return tuple(spec.name for spec in _tool_specs())


def get_tool_spec(name: str) -> ToolSpec | None:
    """Return one spec by name, or ``None`` if no such tool is advertised."""
    for spec in tool_specs():
        if spec.name == name:
            return spec
    return None


def _tool_specs() -> list[ToolSpec]:
    """The declarations themselves, without the uniform arguments applied."""
    return [
        ToolSpec(
            name="scaffold_context",
            description=(
                "Get call-graph context for a symbol: its definition, the "
                "functions and methods that call it (callers), and the functions "
                "it calls (callees). Returns a 'markdown' summary plus structured "
                "lists. When the symbol is missing, includes inline why_empty and "
                "grep_fallback -- consume those before a separate diagnosis call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol name to look up"},
                    **_SCOPE_PROPS,
                },
                "required": ["symbol"],
            },
        ),
        ToolSpec(
            name="scaffold_impact",
            description=(
                "Analyze the blast radius of changing a file. Walks IMPORTS edges "
                "up to 'depth' hops to find transitive importing files, and lists "
                "the functions and methods that call into the file. Returns a "
                "'markdown' summary plus structured lists. When empty, also "
                "includes inline why_empty and grep_fallback -- consume those "
                "before calling scaffold_why_empty or scaffold_grep_graph."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "file_or_symbol": {"type": "string", "description": "File path or symbol name"},
                    "depth": {
                        "type": "integer",
                        "description": "Traversal depth (default 2)",
                        "default": 2,
                    },
                    **_SCOPE_PROPS,
                },
                "required": ["file_or_symbol"],
            },
        ),
        ToolSpec(
            name="scaffold_search",
            description=(
                "Search across code definitions using hybrid search "
                "(structural graph + semantic similarity). Supports keyword, "
                "semantic, or hybrid modes. When count is 0, the response "
                "includes inline why_empty and grep_fallback -- use those "
                "before a separate diagnosis or grep tool call."
            ),
            input_schema={
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
        ToolSpec(
            name="scaffold_recall_governance",
            description=(
                "Semantically recall prior governance knowledge (plans, findings, "
                "learnings, ADRs, studies, spikes, backlog) for a natural-language query."
            ),
            input_schema={
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
        ToolSpec(
            name="scaffold_validate",
            description=(
                "Run validation checks: layer conformance, contract drift, graph "
                "staleness, or graph coverage (parsed vs structurally-invisible files)."
            ),
            input_schema={
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
        ToolSpec(
            name="scaffold_query",
            description="Execute a raw SQL query against the knowledge graph.",
            input_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query to execute"},
                },
                "required": ["sql"],
            },
        ),
        ToolSpec(
            name="scaffold_stats",
            description=(
                "Get codebase health overview with file/function/edge "
                "counts and governance summary."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
        ),
        ToolSpec(
            name="scaffold_review_context",
            description=(
                "Generate graph-powered review context for a plan. "
                "Returns brief, adversarial challenges, gap analysis, "
                "post-implementation verification, or retro enrichment "
                "depending on review_type."
            ),
            input_schema={
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
                    "detail": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "description": "Token control: summary (default) or full",
                        "default": "summary",
                    },
                },
                "required": ["plan_number", "review_type"],
            },
        ),
        # --- Composite tools ---
        ToolSpec(
            name="scaffold_prepare_review",
            description=(
                "Prepare full review context for a plan in one call. Use when the user "
                "asks to review, critique, prepare, or do devil's advocate on a plan. "
                "Returns dependency brief, gap analysis, adversarial challenges, "
                "governing ADRs, validation spikes, and related studies."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                    "detail": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "description": "Token control: summary (default) or full",
                        "default": "summary",
                    },
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_prepare_implementation",
            description=(
                "Prepare implementation context for a plan. Use when the user asks to "
                "implement, start, or execute a plan. Returns dependency brief, per-file "
                "blast radius, contract obligations, consumer audit, and dependency status."
            ),
            input_schema={
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
                    "detail": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "description": "Token control: summary (default) or full",
                        "default": "summary",
                    },
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_compare_plans",
            description=(
                "Compare two plans for conflicts, shared files, and supersession. "
                "Use when the user asks to compare plans or check for overlap."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_a": {"type": "integer", "description": "First plan number"},
                    "plan_b": {"type": "integer", "description": "Second plan number"},
                },
                "required": ["plan_a", "plan_b"],
            },
        ),
        ToolSpec(
            name="scaffold_staleness_check",
            description=(
                "Check if a plan is stale: overlapping completed plans, missing files, "
                "changed dependencies, contradicting studies. Use when the user asks "
                "if a plan is still valid or stale."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_prepare_rewrite",
            description=(
                "Prepare context for rewriting a stale plan. Superset of staleness check "
                "plus current dependency landscape and new contracts/plans since the plan "
                "was written. Use when the user asks to rewrite, update, or refresh a plan."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_prepare_retro",
            description=(
                "Prepare retrospective context for a completed plan. Returns verification "
                "results, retro enrichment, modification frequency, and related studies. "
                "Use when the user asks for a retrospective or post-implementation review."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_orient",
            description=(
                "Get session orientation: codebase stats, recent plans, hot files, "
                "recent studies, active ADRs, live workflow state (blockers, next "
                "steps, in-progress plans), plus recommended_actions, "
                "plan_progress, and next_action_focus. Use at session start or "
                "when the user asks where we left off, what's blocked, or what "
                "to do next. Prefer embedded recommended_actions over a separate "
                "scaffold_next_action call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "detail": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "description": "Token control: summary (default) or full",
                        "default": "summary",
                    },
                },
            },
        ),
        ToolSpec(
            name="scaffold_find_studies",
            description=(
                "Search studies by topic keyword or outcome. Use when the user asks "
                "about studies, experiments, or A/B tests on a topic."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Keyword to search in tags/title"},
                    "outcome": {
                        "type": "string",
                        "description": "Filter by outcome (e.g. baseline_preferred)",
                    },
                    **_SCOPE_PROPS,
                },
                "required": ["topic"],
            },
        ),
        ToolSpec(
            name="scaffold_prior_experiments",
            description=(
                "Find prior experiments related to a plan: directly referenced studies, "
                "tag-matched studies, and file-overlap studies. Use when the user asks "
                "if something has been tested or what experiments relate to a plan."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_find_adrs",
            description=(
                "Search ADRs by topic keyword or status. Use when the user asks about "
                "architectural decisions, ADRs, or what governs a particular area."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Keyword to search in ADR titles"},
                    "status": {
                        "type": "string",
                        "description": "Filter by ADR status (e.g. Accepted)",
                    },
                    **_SCOPE_PROPS,
                },
                "required": ["topic"],
            },
        ),
        ToolSpec(
            name="scaffold_decision_context",
            description=(
                "Get the full decision chain for a plan: governing ADRs, validation "
                "spikes, supporting studies, related experiments, and dependency status. "
                "Use when the user asks about decision history, prior validation, or "
                "what ADR governs a plan."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                    **_SCOPE_PROPS,
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_projects",
            description=(
                "List the projects this server can answer for and report which project "
                "the current call resolves to (and why). Use when a call was refused as "
                "ambiguous, when you need a valid 'project' name, or to confirm which "
                "project you are in before a scoped read."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        ToolSpec(
            name="scaffold_record_finding",
            description=(
                "Record a review finding in the knowledge graph. Creates a ReviewFinding "
                "node linked to the relevant plan, files, and functions. Use this when "
                "you identify an issue, concern, or improvement during a code review. "
                "Findings persist across sessions and surface in future reviews."
            ),
            input_schema={
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
        ToolSpec(
            name="scaffold_resolve_finding",
            description=(
                "Mark a ReviewFinding as resolved. Use this when an issue identified "
                "during a prior review has been addressed. The finding remains in the "
                "graph with status='resolved' for audit trail purposes."
            ),
            input_schema={
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
        ToolSpec(
            name="scaffold_record_findings_batch",
            description=(
                "Record multiple ReviewFinding nodes in a single transaction. Use this "
                "when a review produces several findings at once (e.g. post-implementation "
                "review, plan appendix findings). More efficient than calling "
                "scaffold_record_finding N times."
            ),
            input_schema={
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
        ToolSpec(
            name="scaffold_record_backlog_item",
            description=(
                "Record one or more BacklogItem nodes in the knowledge graph. Use this "
                "alongside writing to backlog.md — the graph write is additive and enables "
                "backlog queries in orient and prepare_review. Pass 'items' (array) for "
                "batch recording (recommended), or 'title' for a single item."
            ),
            input_schema={
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
        ToolSpec(
            name="scaffold_resolve_backlog_item",
            description=(
                "Mark a BacklogItem as archived (completed). Use this when a backlog item "
                "is done and being moved from backlog.md to backlog_archive.md. The item "
                "remains in the graph with status='archived' for retrospective queries."
            ),
            input_schema={
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
        # --- Agent tool pack (Plan 246) ---
        ToolSpec(
            name="scaffold_diff_plan_vs_code",
            description=(
                "Compare a plan's File Impact Map and execution checkboxes against "
                "filesystem and graph reality. Returns next_unchecked_step, "
                "disk/graph presence, and symbol spot-checks. Preferred "
                "mid-implementation progress check; prefer over re-reading the "
                "full plan body for status."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_grep_graph",
            description=(
                "Structured ripgrep of the project workspace (path-sandboxed). "
                "Fallback when graph search is degraded, coverage is low, or "
                "inline grep_fallback on an empty search/impact response is "
                "absent or insufficient."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern"},
                    "path": {
                        "type": "string",
                        "description": "Optional subdirectory or file under project root",
                    },
                    "glob": {"type": "string", "description": "Optional ripgrep glob filter"},
                    "max_hits": {
                        "type": "integer",
                        "description": "Maximum hits (default 50)",
                        "default": 50,
                    },
                },
                "required": ["pattern"],
            },
        ),
        ToolSpec(
            name="scaffold_why_empty",
            description=(
                "Explain why a structural or search result was empty: coverage gaps, "
                "missing args, degraded retrieval, refresh/lock, or unconfirmed static "
                "analysis. Fallback only -- prefer inline why_empty on empty "
                "search/impact/context responses when present."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["structural", "search", "impact", "context", "generic"],
                        "description": "Empty-result category",
                        "default": "structural",
                    },
                    "target": {
                        "type": "string",
                        "description": "File path or symbol that returned empty",
                    },
                    "query": {"type": "string", "description": "Search query that returned empty"},
                },
            },
        ),
        ToolSpec(
            name="scaffold_next_action",
            description=(
                "Return 1-3 concrete next moves with suggested MCP tool calls from "
                "workflow state, in-progress plans, and optional plan_card. "
                "Fallback only -- prefer recommended_actions from scaffold_orient "
                "when present."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {
                        "type": "integer",
                        "description": "Optional plan to route around",
                    },
                },
            },
        ),
        # --- Governed lifecycle composite tools ---
        ToolSpec(
            name="scaffold_begin_plan",
            description=(
                "Run the full pre-implementation review chain for a plan: orient, "
                "prepare_review (all three perspectives), auto-write challenges and gaps "
                "as ReviewFindings to the graph, stamp Plan.reviewedAt. Returns structured "
                "output with orient summary, review perspectives, findings written, and a "
                "proceed_prompt for the agent to present to the user. Pass dry_run=true to "
                "rehearse without writing findings or stamping reviewedAt."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                    "dry_run": {
                        "type": "boolean",
                        "description": "When true, return review payload without graph writes",
                        "default": False,
                    },
                },
                "required": ["plan_number"],
            },
        ),
        ToolSpec(
            name="scaffold_complete_plan",
            description=(
                "Run the full post-implementation chain for a plan: prepare_retro, "
                "auto-write retro insights as ReviewFindings, optionally write backlog items. "
                "Returns structured output with retro results, findings written, structured "
                "learnings, and a completion checklist for the agent. Pass dry_run=true to "
                "rehearse without writing findings or backlog items."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_number": {"type": "integer", "description": "Plan number"},
                    "dry_run": {
                        "type": "boolean",
                        "description": "When true, return retro payload without graph writes",
                        "default": False,
                    },
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
