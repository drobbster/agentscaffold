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
        "Path of the file or directory you are working on: absolute, or relative "
        "to a registered workspace root. The server resolves the owning project "
        "from it and scopes the call, which is how a call follows your active "
        "project even though one server serves every workspace from a single fixed "
        "directory. Pass it whenever you know the file. With several projects "
        "registered there is no default to fall back on, so omitting it may be "
        "refused with 'ambiguous_project'; pass project=<name> instead when you "
        "have no path, or all_projects=true to read across every project."
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


#: Tools that mutate the graph.
#:
#: Declared here rather than in ``server.py`` because two other callers need the
#: distinction without wanting the MCP SDK: the server takes the exclusive write
#: lock for these and opens read-preferring for the rest, and ``doctor --tools``
#: must not run them unless explicitly asked. A second hand-maintained copy of
#: this list is how a new write tool ends up being probed against real
#: governance data -- the same failure shape as L249-13.
WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "scaffold_record_finding",
        "scaffold_resolve_finding",
        "scaffold_record_findings_batch",
        "scaffold_record_backlog_item",
        "scaffold_resolve_backlog_item",
        "scaffold_begin_plan",
        "scaffold_complete_plan",
        "scaffold_session_start",
        "scaffold_session_end",
        "scaffold_session_record_decision",
    }
)


def is_write_tool(name: str) -> bool:
    """True if *name* mutates the graph and needs the exclusive write lock."""
    return name in WRITE_TOOLS


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
                "Also reports a pairwise dependency_cycle (none / apparent / genuine) "
                "when the plans depend on each other. Use when the user asks to "
                "compare plans or check for overlap."
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
                "Pass function_ids when the finding is about a symbol, not only a file. "
                "Omit evidence_kind to record unspecified; set inferred when the claim "
                "was not measured. Findings persist across sessions."
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
                        "description": (
                            "Function node IDs related to this finding. Prefer "
                            "this over file_paths alone when the finding is "
                            "about a symbol."
                        ),
                    },
                    "evidence_kind": {
                        "type": "string",
                        "enum": [
                            "command",
                            "test",
                            "file_ref",
                            "graph_query",
                            "external_doc",
                            "inferred",
                            "unspecified",
                        ],
                        "description": (
                            "How the finding was established. Omit for "
                            "unspecified. Use inferred when it was not measured."
                        ),
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Citation: command, test id, path:line, or SQL",
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
                "graph with status='resolved' for audit trail purposes. finding_id must "
                "be the rf:: id from scaffold_record_finding or from orient / "
                "prepare_review. A miss returns status=not_found (error_code not_found) "
                "rather than a fake resolve."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "finding_id": {
                        "type": "string",
                        "description": (
                            "The rf:: id of the finding to resolve, from "
                            "scaffold_record_finding or from orient / prepare_review. "
                            "Not a human label."
                        ),
                    },
                    "resolution": {
                        "type": "string",
                        "description": "Description of how the finding was resolved",
                    },
                    "resolved_by_plan": {
                        "type": "integer",
                        "description": (
                            "Plan number that addressed the finding. Creates "
                            "FINDING_ADDRESSED_BY only when that Plan vertex exists."
                        ),
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
                                "evidence_kind": {
                                    "type": "string",
                                    "enum": [
                                        "command",
                                        "test",
                                        "file_ref",
                                        "graph_query",
                                        "external_doc",
                                        "inferred",
                                        "unspecified",
                                    ],
                                },
                                "evidence": {"type": "string"},
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
                "remains in the graph with status='archived' for retrospective queries. "
                "item_id must be the bi:: id from scaffold_record_backlog_item / "
                "orient.open_backlog_top3 / prepare_review.open_backlog_items, or a "
                "human id / title prefix that uniquely matches one item (e.g. DQ-043). "
                "A miss returns status=not_found rather than a fake archive."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": (
                            "The bi:: id from record_backlog_item / orient / "
                            "prepare_review, or a unique human id / title prefix "
                            "(e.g. DQ-043). Not sufficient to guess among duplicates."
                        ),
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
        ToolSpec(
            name="scaffold_session_start",
            description=(
                "Start a working session in the knowledge graph. Returns the session "
                "id. If a session is already open for this project, returns that id "
                "instead of minting a second one."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Plan numbers this session is working on",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional opening summary",
                    },
                },
            },
        ),
        ToolSpec(
            name="scaffold_session_end",
            description=(
                "Close a working session with a summary, decisions, and optional "
                "files. Omitting session_id closes the open session for this project."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session id to close; omit to close the open session",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Final session summary",
                    },
                    "plan_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Plan numbers to store on the session",
                    },
                    "decisions": {
                        "type": "array",
                        "description": (
                            "Structured decisions: {decision, evidence, status} "
                            "where status is observed or inferred"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "decision": {"type": "string"},
                                "evidence": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["observed", "inferred"],
                                },
                            },
                            "required": ["decision"],
                        },
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Files touched. Always stored on the session; "
                            "SESSION_MODIFIED edges only when a File vertex exists"
                        ),
                    },
                },
            },
        ),
        ToolSpec(
            name="scaffold_session_context",
            description=(
                "Recent session summaries, hot files, and plan numbers. Fallback "
                "only -- prefer the session_context field already embedded in "
                "scaffold_orient when sessions exist."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent sessions to include",
                        "default": 3,
                    },
                },
            },
        ),
        ToolSpec(
            name="scaffold_session_record_decision",
            description=(
                "Record a strategic, architectural, or operational decision on "
                "the open working session. Opens a session if none is open. "
                "Use for approve / defer / stay-the-course / change-scope "
                "calls. Do not record findings or backlog items here -- those "
                "have their own tools."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "description": "What was decided",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["strategic", "architectural", "operational"],
                        "description": (
                            "strategic = approve/defer/stay-the-course; "
                            "architectural = structure or contract; "
                            "operational = how we execute this session"
                        ),
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Citation or basis for the decision",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["observed", "inferred"],
                        "description": "observed if measured; inferred otherwise",
                    },
                    "plan_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["decision"],
            },
        ),
        ToolSpec(
            name="scaffold_session_list",
            description=("List recent working sessions for this project, most recent first."),
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of sessions to return",
                        "default": 10,
                    },
                },
            },
        ),
    ]
