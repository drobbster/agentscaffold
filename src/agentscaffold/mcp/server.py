"""MCP server for AgentScaffold knowledge graph.

Exposes graph queries as MCP tools and resources via stdio transport.
Composite tools and their intent metadata are the single source of truth
for semantic mapping -- platform rule files are generated from these.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import AnyUrl

from agentscaffold.active_root import active_root
from agentscaffold.mcp.registry import WRITE_TOOLS, tool_specs
from agentscaffold.mcp.resources import (
    GUIDANCE_ROUTING_URI,
    guidance_resource_definition,
    read_guidance_routing,
)

logger = logging.getLogger(__name__)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Resource, TextContent, Tool

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

_MCP_EXTRAS_MSG = "MCP server requires extra dependencies: pip install agentscaffold[mcp]"

# Tools that mutate the graph and must wait for the exclusive write lock.
# All other tools open read-preferring (Plan 244) so async freshness refresh
# does not block interactive reads for ~20s+.
#
# Imported rather than restated: `doctor --tools` needs the same distinction to
# decide what it may safely run, and a second copy would drift.
_GRAPH_WRITE_TOOLS: frozenset[str] = WRITE_TOOLS

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
    "scaffold_diff_plan_vs_code": [
        "diff plan X vs code",
        "what's left on plan X",
        "plan vs implementation for plan X",
        "which planned files are missing",
        "mid-implementation progress on plan X",
    ],
    "scaffold_grep_graph": [
        "grep the workspace for X",
        "ripgrep for X in the project",
        "text search the repo for X",
        "scaffold grep for X",
    ],
    "scaffold_why_empty": [
        "why is search empty",
        "why no callers",
        "why empty impact",
        "explain empty scaffold result",
    ],
    "scaffold_next_action": [
        "what should I do next",
        "next action",
        "what tool should I call next",
        "route me to the next step",
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
    "scaffold_diff_plan_vs_code": {"diff", "missing", "progress", "implementation", "vs"},
    "scaffold_grep_graph": {"grep", "ripgrep", "text", "workspace", "search"},
    "scaffold_why_empty": {"why", "empty", "explain", "no", "callers"},
    "scaffold_next_action": {"next", "action", "route", "should", "tool"},
}

# Required string args that must be non-empty (Plan 246 fail-loud validation).
_REQUIRED_STRING_ARGS: dict[str, tuple[str, ...]] = {
    "scaffold_impact": ("file_or_symbol",),
    "scaffold_context": ("symbol",),
    "scaffold_search": ("query",),
    "scaffold_recall_governance": ("query",),
    "scaffold_grep_graph": ("pattern",),
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

    # MCP owns stdout for JSON-RPC. Suppress Rich pipeline progress so
    # in-process incremental refresh cannot poison the transport (Plan 242).
    from agentscaffold.graph.pipeline import install_stdio_safe_console

    install_stdio_safe_console()

    # Legacy per-project entries keep working; the user is told once, at startup,
    # how to collapse them. Advisory only -- never a reason to fail to start.
    from agentscaffold.mcp.install import warn_once_about_legacy_entries

    warn_once_about_legacy_entries()

    asyncio.run(_serve())


async def _serve() -> None:
    """Async entry point for the MCP server."""
    server = Server("agentscaffold")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[Tool]:
        return _get_tool_definitions()

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = _dispatch_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    @server.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_resources() -> list[Resource]:
        return _get_resource_definitions()

    @server.read_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def read_resource(uri: str) -> str:
        return json.dumps(_dispatch_resource(uri), indent=2, default=str)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _get_tool_definitions() -> list[Tool]:
    """Render the tool registry into MCP SDK objects.

    The declarations live in :mod:`agentscaffold.mcp.registry`, which imports
    nothing from ``mcp`` so that the agent-file generator and the conformance
    suite can enumerate the surface without the optional SDK installed. This
    function is the only place that turns them into SDK types.
    """
    if not _MCP_AVAILABLE:
        return []

    return [
        Tool(
            name=spec.name,
            description=spec.description,
            inputSchema=spec.input_schema,
        )
        for spec in tool_specs()
    ]


# ---------------------------------------------------------------------------
# Resource definitions
# ---------------------------------------------------------------------------


def _get_resource_definitions() -> list[Resource]:
    """Return MCP resource definitions."""
    if not _MCP_AVAILABLE:
        return []

    return [
        Resource(
            uri=AnyUrl("scaffold://project/context"),
            name="Project Context",
            description="Project stats, layer map, hot spots, recent plans.",
            mimeType="application/json",
        ),
        Resource(
            uri=AnyUrl("scaffold://project/layers"),
            name="Architecture Layers",
            description="Architecture layers with file counts.",
            mimeType="application/json",
        ),
        guidance_resource_definition(),
    ]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


_RESTRICT_TO: set[str] = set()


def configure_restrict_to(names: Iterable[str] | None) -> None:
    """Set the ``--restrict-to`` allowlist for this server process.

    Plan 249 Section 11 counts this among the mitigations for the fact that one
    process can now read every registered project: a user who wants a narrower
    blast radius can start the server bound to an explicit set. Passing None or
    an empty iterable clears the restriction rather than denying everything,
    since an unset allowlist must not fail closed.

    Comma-separated values are split here rather than at the call site, because
    users reach for both ``--restrict-to a --restrict-to b`` and
    ``--restrict-to a,b``, and an allowlist entry that is silently parsed into
    one nonexistent project name would deny access without explaining why.
    """
    global _RESTRICT_TO
    _RESTRICT_TO = {
        part.strip() for name in (names or ()) for part in str(name).split(",") if part.strip()
    }


def _route_root_for_working_path(working_path: Any) -> Path | None:
    """Resolve the project root that owns *working_path* (dynamic per-call scoping).

    The Cursor MCP server runs from a single fixed working directory, so it
    cannot infer which project the agent is actively editing. When a caller
    passes ``working_path`` (the file or dir it is working on), resolve the
    owning project root from it so multi-project reads scope to that project
    instead of the server's launch directory. Absolute or workspace-relative
    paths are accepted. Returns None when the path is empty or cannot be
    resolved, so the caller keeps the default root.
    """
    if not working_path:
        return None
    try:
        from agentscaffold.paths import resolve_root, resolve_workspace_root

        candidate = Path(str(working_path)).expanduser()
        if not candidate.is_absolute():
            candidate = resolve_workspace_root() / candidate
        candidate = candidate.resolve()
        if not candidate.exists():
            return None
        return resolve_root(candidate)
    except Exception:
        return None


def _current_project_or_none() -> str | None:
    """Resolve the active project for a scoped write/read, or None if unscoped.

    Used by the findings write/read handlers so review findings are stamped with
    (and filtered by) the project the agent is working in. Relies on the cwd,
    which ``_dispatch_tool`` has already routed via ``working_path``. Returns
    None in a single-project workspace or when the project cannot be resolved
    (federated/ambiguous), preserving the pre-multi-project unscoped behavior.
    """
    try:
        from agentscaffold.graph.scoping import resolve_scope

        return resolve_scope().project
    except Exception:
        return None


def _scope_sql(arguments: dict[str, Any], column: str = "project") -> tuple[str, dict[str, str]]:
    """Build the project predicate a read tool must AND into its WHERE clause.

    Returns ``("", {})`` when no filter applies -- a single-project workspace, an
    explicit ``all_projects``, or a scope that could not be resolved -- so the
    caller composes it the same way in every case.

    Read tools that build their own SQL do not otherwise pass through the
    scoping layer that ``hybrid_search`` gives ``scaffold_search``, and a query
    that omits this returns rows from whichever project happens to sort first.

    Params come back as a dict because the backend binds ``?`` placeholders from
    ``params.values()``; the scoping helper's list would raise there.
    """
    try:
        from agentscaffold.graph.scoping import resolve_scope, sql_predicate

        scope = resolve_scope(
            project=arguments.get("project") or None,
            all_projects=bool(arguments.get("all_projects", False)),
        )
        fragment, params = sql_predicate(scope, column)
        return fragment, ({column: params[0]} if params else {})
    except Exception:
        # Fail open rather than erroring the tool: an unresolvable scope in a
        # single-project workspace is the overwhelmingly common case, and it is
        # exactly the pre-multi-project behaviour.
        return ("", {})


def _and_where(sql: str, fragment: str) -> str:
    """AND *fragment* onto a statement that already has a WHERE clause."""
    return sql if not fragment else f"{sql} AND {fragment}"


def _stats_scope_label() -> dict[str, Any]:
    """Describe what ``scaffold_stats`` counted, so the totals are unambiguous."""
    label: dict[str, Any] = {"kind": "workspace", "covers": "all projects in this workspace"}
    try:
        from agentscaffold.graph.scoping import current_project_name
        from agentscaffold.paths import load_workspace

        workspace = load_workspace()
        if not workspace.is_multi_project:
            label = {"kind": "project", "covers": "the only project in this workspace"}
        else:
            label["projects"] = list(workspace.project_names())
            label["current_project"] = current_project_name()
    except Exception:  # noqa: BLE001 - labelling must never fail the tool
        pass
    return label


def _qualified_node_id(raw_id: str, arguments: dict[str, Any]) -> str:
    """Project-qualify a node ID built from user input, if the scope calls for it.

    Tools that look a node up by constructed ID (rather than by filtering rows)
    cannot use a WHERE predicate, because in a multi-project workspace the ID
    itself carries the project. Returns *raw_id* unchanged for a single-project
    workspace or a federated/unresolvable scope.
    """
    try:
        from agentscaffold.graph.scoping import qualify_id, resolve_scope

        scope = resolve_scope(
            project=arguments.get("project") or None,
            all_projects=bool(arguments.get("all_projects", False)),
        )
        if scope.is_noop or not scope.project:
            return raw_id
        return qualify_id(scope.project, raw_id)
    except Exception:
        return raw_id


def _effective_mcp_root(start: Path | None = None) -> Path:
    """Resolve the project root for MCP calls launched from a workspace root.

    Cursor can launch MCP servers from a broad IDE workspace rather than the
    active AgentScaffold project. When the current directory is an AgentScaffold
    workspace with exactly one registered project, route no-arg tools to that
    project root so project-local state resolves correctly.
    """
    try:
        from agentscaffold.paths import (
            load_workspace,
            resolve_mcp_start,
            resolve_root,
            resolve_workspace_root,
        )

        # Plan 234: honor an explicit MCP anchor (scaffold mcp --workspace/--project
        # or AGENTSCAFFOLD_* env vars) before falling back to the launch cwd, so
        # no-argument tools resolve the configured project even when Cursor opens a
        # parent folder. The single-child / single-project heuristics below still
        # apply on top of the resolved start.
        current = resolve_mcp_start(start)
        workspace_root = resolve_workspace_root(current)

        # Cursor can launch user-level MCP servers from the broad IDE workspace
        # (for this devbox, /home/drobb) while the AgentScaffold workspace is a
        # child folder. If there is exactly one child workspace manifest, use it
        # as the MCP workspace root so no-arg tools still resolve project state.
        if workspace_root == current and not (current / "workspace.yaml").is_file():
            child_workspaces = [
                p.parent
                for p in current.glob("*/workspace.yaml")
                if (p.parent / "workspace.yaml").is_file()
            ]
            if len(child_workspaces) == 1:
                workspace_root = child_workspaces[0].resolve()
                current = workspace_root

        workspace = load_workspace(current)
        if current == workspace_root and len(workspace.projects) == 1:
            entry = workspace.projects[0]
            project_path = Path(entry.path)
            if not project_path.is_absolute():
                project_path = workspace_root / project_path
            if project_path.is_dir():
                return project_path.resolve()
        return resolve_root(current)
    except Exception:
        return (start or Path.cwd()).resolve()


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Resolve which project a tool call is about, then run it scoped to that project."""
    # Fail loud on missing/empty required string args before opening the graph.
    for arg_name in _REQUIRED_STRING_ARGS.get(name, ()):
        value = arguments.get(arg_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            return {
                "error": f"Missing required argument '{arg_name}'.",
                "missing_argument": arg_name,
            }

    # Resolve which project this call is about before touching the graph, so an
    # unscopeable call costs nothing and cannot read a database it had no
    # business opening. Replaces the previous behaviour, which swallowed every
    # resolution failure and federated across all projects -- answering a
    # question about one project with another's data, silently.
    from agentscaffold.mcp.errors import McpToolError, to_error_response
    from agentscaffold.mcp.project_resolution import resolve_project

    try:
        resolution = resolve_project(
            project=arguments.get("project"),
            working_path=arguments.get("working_path"),
            anchor=_effective_mcp_root(),
            restrict_to=_RESTRICT_TO or None,
        )
    except McpToolError as exc:
        # scaffold_projects is the documented recovery from an unresolvable
        # call, so it must answer when resolution fails -- refusing it with the
        # very error it exists to explain would leave the agent with no way out.
        if name == "scaffold_projects":
            from agentscaffold.mcp.projects import build_projects_payload

            return {
                **build_projects_payload(None, restrict_to=_RESTRICT_TO or None),
                "unresolved": to_error_response(exc),
            }
        return to_error_response(exc)

    if name == "scaffold_projects":
        from agentscaffold.mcp.projects import build_projects_payload

        return build_projects_payload(resolution, restrict_to=_RESTRICT_TO or None)

    # Project-scoped reads resolve their scope from "where we are", and this is
    # where the resolved project reaches them. It used to be os.chdir, which is
    # process-global and therefore only safe while dispatch is serialised (see
    # finding rf::65b49d5c2a95); an active-root context is per-call, so two
    # dispatches for different projects can now be in flight at once -- which is
    # what makes the Step A6 handle pool reachable.
    with active_root(resolution.root):
        return _dispatch_resolved(name, arguments, resolution)


def _dispatch_resolved(name: str, arguments: dict[str, Any], resolution: Any) -> dict[str, Any]:
    """Run a tool call whose project is already resolved and scoped."""
    from agentscaffold.config import load_config
    from agentscaffold.graph import GraphLockError, graph_available, open_graph

    root = resolution.root
    config = load_config(root / "scaffold.yaml")
    # Pin the embedding weights cache from config BEFORE any retrieval-status
    # probe (the meta build below runs evaluate_retrieval). Without this, cold
    # tools like scaffold_stats probe the unpinned default HF cache and report
    # retrieval as 'degraded' even though semantic search works.
    try:
        from agentscaffold.graph.embeddings import configure_embeddings

        configure_embeddings(config.search.embedding_model, config.search.cache_dir)
    except Exception:  # pragma: no cover - defensive; search config optional
        pass
    # The silent federation fallback that stood here is gone (Plan 249 Step A6b).
    # It existed because resolution could land on a root that was not a project;
    # resolve_project now either returns a real project root or refuses, so the
    # condition it guarded against cannot arise, and quietly widening a call's
    # scope is the failure this plan exists to remove.
    if not graph_available(config):
        return {"error": "No knowledge graph found. Run 'scaffold index' first."}

    read_preferring = name not in _GRAPH_WRITE_TOOLS
    store = None
    # Read tools: at most one brief retry (Plan 244). Write tools keep Plan 235
    # backoff so transient lock contention can clear.
    open_attempts = (0.0, 0.1) if read_preferring else (0.0, 0.5, 1.0)
    for attempt, delay in enumerate(open_attempts, start=1):
        if delay:
            time.sleep(delay)
        try:
            store = open_graph(config, read_only=read_preferring)
            break
        except GraphLockError as exc:
            if attempt >= len(open_attempts):
                from agentscaffold.graph.locks import graph_write_lock_held
                from agentscaffold.mcp.freshness import refresh_runtime_state
                from agentscaffold.paths import resolve_db_path

                db_path = resolve_db_path(config)
                refresh_meta: dict[str, Any] = {}
                try:
                    refresh_meta = refresh_runtime_state(root, config)
                except Exception:  # noqa: BLE001
                    refresh_meta = {}
                writer_active = graph_write_lock_held(db_path) or refresh_meta.get(
                    "refresh_state"
                ) in {"running", "scheduled"}
                return {
                    "error": str(exc),
                    "graph_locked": True,
                    "refresh_in_progress": bool(writer_active),
                    "retry_exhausted": True,
                    "retry_attempts": attempt,
                    "meta": {
                        **refresh_meta,
                        "read_during_refresh": False,
                        "freshness_status": ("refreshing" if writer_active else "unknown"),
                        "freshness_reason": (
                            "refresh_in_progress" if writer_active else "graph_locked"
                        ),
                    },
                }
        except Exception as exc:  # pragma: no cover - defensive fallback
            return {"error": f"Failed to open knowledge graph: {exc}"}
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
    meta.update(_maybe_schedule_embedding_lane(root, config, meta))
    if read_preferring:
        try:
            from agentscaffold.graph.locks import graph_write_lock_held
            from agentscaffold.paths import resolve_db_path

            during_refresh = graph_write_lock_held(resolve_db_path(config)) or meta.get(
                "refresh_state"
            ) in {"running", "scheduled"}
            meta["read_during_refresh"] = bool(during_refresh)
            if during_refresh:
                meta["freshness_status"] = "refreshing"
                meta.setdefault("freshness_reason", "refresh_in_progress")
        except Exception:  # noqa: BLE001
            meta.setdefault("read_during_refresh", False)

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
            # Counts are workspace-wide by design -- this is the graph's health
            # dashboard, not a per-project report. Said explicitly because the
            # tool accepts working_path and its neighbours all scope to one
            # project, so an unlabelled "functions: 5" reads as this project's 5.
            result["scope"] = _stats_scope_label()
            result["meta"] = meta
            return result

        elif name == "scaffold_query":
            sql = arguments.get("sql", "")
            if not sql:
                return {"error": "Missing 'sql' parameter.", "meta": meta}
            rows = store.query(sql)
            return {"results": rows, "count": len(rows), "meta": meta}

        elif name == "scaffold_context":
            return _tool_context(store, arguments, meta, root)

        elif name == "scaffold_impact":
            return _tool_impact(store, arguments, meta, root)

        elif name == "scaffold_search":
            if str(arguments.get("mode", "hybrid")).lower() in ("semantic", "hybrid"):
                from agentscaffold.graph.embeddings import configure_embeddings

                configure_embeddings(config.search.embedding_model, config.search.cache_dir)
            return _tool_search(store, arguments, meta, root)

        elif name == "scaffold_recall_governance":
            if str(arguments.get("mode", "hybrid")).lower() in ("semantic", "hybrid"):
                from agentscaffold.graph.embeddings import configure_embeddings

                configure_embeddings(config.search.embedding_model, config.search.cache_dir)
            return _tool_search(store, {**arguments, "kind": "governance"}, meta, root)

        elif name == "scaffold_validate":
            return _tool_validate(store, arguments, meta)

        elif name == "scaffold_review_context":
            return _tool_review_context(store, arguments, meta)

        elif name == "scaffold_prepare_review":
            return _tool_prepare_review(store, arguments, meta, root, config)

        elif name == "scaffold_prepare_implementation":
            return _tool_prepare_implementation(store, arguments, meta, root)

        elif name == "scaffold_compare_plans":
            return _tool_compare_plans(store, arguments, meta, config)

        elif name == "scaffold_staleness_check":
            return _tool_staleness_check(store, arguments, meta, config)

        elif name == "scaffold_prepare_rewrite":
            return _tool_prepare_rewrite(store, arguments, meta, config)

        elif name == "scaffold_prepare_retro":
            return _tool_prepare_retro(store, arguments, meta)

        elif name == "scaffold_orient":
            return _tool_orient(store, meta, root, config, arguments)

        elif name == "scaffold_diff_plan_vs_code":
            return _tool_diff_plan_vs_code(store, arguments, meta, root)

        elif name == "scaffold_grep_graph":
            return _tool_grep_graph(arguments, meta, root)

        elif name == "scaffold_why_empty":
            return _tool_why_empty(store, arguments, meta)

        elif name == "scaffold_next_action":
            return _tool_next_action(store, arguments, meta, root, config)

        elif name == "scaffold_find_studies":
            return _tool_find_studies(store, arguments, meta)

        elif name == "scaffold_prior_experiments":
            return _tool_prior_experiments(store, arguments, meta, config)

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


def _maybe_schedule_embedding_lane(root: Path, config: Any, meta: dict[str, Any]) -> dict[str, Any]:
    """Attach async embedding lane state and schedule degraded retrieval repair."""
    try:
        from agentscaffold.graph.embedding_scheduler import (
            embedding_runtime_state,
            maybe_schedule_async_embeddings,
        )

        lane_meta = embedding_runtime_state(root, config)
        degraded = meta.get("retrieval_status") == "degraded"
        if degraded:
            schedule = maybe_schedule_async_embeddings(
                root,
                config,
                reason=str(meta.get("retrieval_reason", "retrieval_degraded")),
            )
            lane_meta.update(schedule)
        else:
            lane_meta.setdefault("embedding_triggered", False)
            lane_meta.setdefault("embedding_schedule_reason", "retrieval_not_degraded")
        return lane_meta
    except Exception as exc:  # pragma: no cover - metadata is best-effort
        return {
            "embedding_policy": str(
                getattr(getattr(config, "graph", None), "async_embeddings", "off")
            ),
            "embedding_state": "failed",
            "embedding_triggered": False,
            "embedding_schedule_reason": "embedding_scheduler_error",
            "embedding_last_error": str(exc),
        }


def _tool_context(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
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
    if not isinstance(symbol, str) or not symbol.strip():
        return {
            "error": "Missing required argument 'symbol'.",
            "missing_argument": "symbol",
            "meta": meta,
        }
    symbol = symbol.strip()

    # Scope to the project this call resolved to. Without it, a symbol that
    # exists in more than one project of a shared workspace is answered from
    # whichever row came back first -- a plausible-looking answer about the
    # wrong project, which is worse than no answer.
    scope_sql, scope_params = _scope_sql(arguments)

    # Search across functions, classes, methods
    results = ql(
        store,
        sql=_and_where(
            f'SELECT id AS "fn.id", name AS "fn.name", filePath AS "fn.filePath", '
            f'startLine AS "fn.startLine", endLine AS "fn.endLine", signature AS "fn.signature" '
            f"FROM Function WHERE name = '{symbol}'",
            scope_sql,
        ),
        params=dict(scope_params),
    )
    if not results:
        results = ql(
            store,
            sql=_and_where(
                f'SELECT id AS "c.id", name AS "c.name", filePath AS "c.filePath", '
                f'startLine AS "c.startLine", endLine AS "c.endLine" '
                f"FROM Class WHERE name = '{symbol}'",
                scope_sql,
            ),
            params=dict(scope_params),
        )

    if not results:
        payload: dict[str, Any] = {
            "error": f"Symbol '{symbol}' not found in graph.",
            "meta": meta,
        }
        if root is not None:
            from agentscaffold.mcp.empty_fallback import attach_empty_fallback

            payload = attach_empty_fallback(
                payload,
                store=store,
                root=root,
                meta=meta,
                kind="context",
                target=symbol,
            )
        return payload

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
    config_consumers = (
        _config_consumers(store, _qualified_node_id(f"file::{file_path}", arguments))
        if file_path
        else []
    )

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


def _tool_impact(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
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
    if not isinstance(target, str) or not target.strip():
        return {
            "error": "Missing required argument 'file_or_symbol'.",
            "missing_argument": "file_or_symbol",
            "meta": meta,
        }
    target = target.strip()
    try:
        depth = int(arguments.get("depth", 2) or 2)
    except (TypeError, ValueError):
        depth = 2

    # Node IDs are project-qualified in a multi-project workspace
    # (``alpha::file::src/x.py``), so a bare ``file::`` ID matches nothing there
    # and every importer and caller list comes back empty -- indistinguishable
    # from a file that genuinely has no importers. Qualifying here covers the
    # whole tool, since every query below derives its target from this ID.
    file_id = _qualified_node_id(f"file::{target}", arguments)
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

    payload: dict[str, Any] = {
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
    if result_count == 0 and root is not None:
        from agentscaffold.mcp.empty_fallback import attach_empty_fallback

        payload = attach_empty_fallback(
            payload,
            store=store,
            root=root,
            meta=meta,
            kind="impact",
            target=target,
        )
    return payload


def _tool_search(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
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

    payload: dict[str, Any] = {
        "results": [
            {
                "node_id": r.node_id,
                "name": r.name,
                "path": r.path,
                "type": r.node_type,
                "score": r.score,
                "source": r.source,
                **({"project": r.project} if r.project else {}),
            }
            for r in results
        ],
        "count": len(results),
        "markdown": format_search_results(results),
        "meta": meta,
    }
    if not results and root is not None and str(query_text).strip():
        from agentscaffold.mcp.empty_fallback import attach_empty_fallback

        payload = attach_empty_fallback(
            payload,
            store=store,
            root=root,
            meta=meta,
            kind="search",
            query=str(query_text).strip(),
        )
    return payload


def _tool_validate(store: Any, arguments: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Handle scaffold_validate tool call."""
    check = arguments.get("check", "")

    if check == "layers":
        from agentscaffold.graph.layers import check_layers

        scope_sql, scope_params = _scope_sql(arguments)
        report = check_layers(store, scope_sql, dict(scope_params) if scope_params else None)
        return {"report": report.to_dict(), "meta": meta}

    if check == "staleness":
        from agentscaffold.graph.verify import verify_graph

        report = verify_graph(store, _effective_mcp_root())
        return {"report": report, "meta": meta}

    if check == "contracts":
        from agentscaffold.graph.verify import check_contract_drift

        report = check_contract_drift(store)
        return {"report": report, "meta": meta}

    if check == "coverage":
        from agentscaffold.mcp.coverage import repo_coverage

        return {"report": repo_coverage(store), "meta": meta}

    return {"error": f"Check '{check}' not yet implemented.", "meta": meta}


def _tool_review_context(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
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

    from agentscaffold.mcp.detail import apply_detail

    return apply_detail(result, arguments.get("detail"))


# ---------------------------------------------------------------------------
# Composite tool handlers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low")


def _scope_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Read the per-call read scope (Plan 249): default is the resolved project."""
    return {
        "project": arguments.get("project") or None,
        "all_projects": bool(arguments.get("all_projects", False)),
    }


def _scope_echo(scope: dict[str, Any]) -> dict[str, Any]:
    """Echo a non-default scope so a federated result is never read as local."""
    if scope["all_projects"]:
        return {"scope": "all_projects"}
    if scope["project"]:
        return {"scope": "project", "project": scope["project"]}
    return {}


def _clean_out_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Strip ``alias.`` prefixes from agent-facing tool output rows (Plan 238).

    The query layer aliases columns as ``alias.field`` (a deliberate internal
    contract). That prefix is noise once it reaches the agent, so plan/governance
    composites clean it at the tool boundary -- matching what ``search``/``context``
    already do -- without touching the query layer itself.
    """
    from agentscaffold.mcp.render import clean_rows  # noqa: PLC0415

    return clean_rows(rows or [])


def _with_normalized_status(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean rows and attach ``status_normalized`` next to the raw ``status`` (Plan 238)."""
    from agentscaffold.review.filters import normalize_plan_status  # noqa: PLC0415

    cleaned = _clean_out_rows(rows)
    for row in cleaned:
        if "status" in row:
            row["status_normalized"] = normalize_plan_status(row.get("status"))
    return cleaned


def _is_plan_complete(raw_status: str | None) -> bool:
    """Return True if a plan status normalizes to Complete (date/note tolerant)."""
    from agentscaffold.review.filters import normalize_plan_status  # noqa: PLC0415

    return normalize_plan_status(raw_status) == "Complete"


def _adr_is_active(raw_status: str | None) -> bool:
    """Return True unless an ADR status indicates it is superseded/deprecated.

    Uses substring matching so descriptive statuses like ``Superseded by ADR-030``
    are correctly treated as inactive (exact-token membership missed these).
    """
    s = (raw_status or "").lower()
    return "supersed" not in s and "deprecat" not in s


def _empty_graph_warning(stats: dict[str, Any]) -> str | None:
    """Return a warning string when the graph looks empty, else None (Plan 239).

    Several read tools render confident negatives (``is_stale: false``,
    ``has_full_decision_chain: false``, empty overlaps) that are indistinguishable
    from "the graph was never populated". Attaching this signal lets the agent tell
    a confirmed absence from an unconfirmed one.
    """
    if stats.get("files", 0) == 0 and stats.get("plans", 0) == 0:
        return (
            "Graph appears empty (0 files, 0 plans). "
            "Run 'scaffold index' before treating absent results as confirmed."
        )
    return None


def _sev_key(row: dict[str, Any]) -> int:
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

    # ``.mdc`` first: Cursor only loads that extension, so it is what the
    # generator writes and what every current project has. ``.md`` is checked
    # after it for projects that have not regenerated since the rename -- looking
    # for it alone silently emitted no hint at all, because the generator removes
    # any stale ``.md`` it finds.
    for suffix in ("mdc", "md"):
        relative = f".cursor/rules/agentscaffold.{suffix}"
        if (root / relative).is_file():
            hints.append(relative)
            break

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
    store: Any, arguments: dict[str, Any], meta: dict[str, Any], root: Path, config: Any
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

    # Open findings: plan-scoped first, then file-scoped (deduplicated).
    # Scope to the active project so a sibling project's same-numbered plan does
    # not leak findings into this review.
    finding_project = _current_project_or_none()
    plan_findings = get_open_findings(store, plan_number=pn, limit=20, project=finding_project)
    seen_ids: set[str] = {r.get("rf.id", "") for r in plan_findings}
    file_findings: list[dict[str, Any]] = []
    for fpath in impacted_paths[:10]:
        for row in get_open_findings(store, file_path=fpath, limit=5, project=finding_project):
            fid = row.get("rf.id", "")
            if fid not in seen_ids:
                seen_ids.add(fid)
                file_findings.append(row)
    all_findings = sorted(plan_findings + file_findings, key=_sev_key)[:20]

    reviewer_hints = _build_reviewer_hints(root, impacted_paths)
    open_backlog = get_backlog_items_for_plan(store, pn)

    from agentscaffold.mcp.detail import apply_detail

    payload = {
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
        "governing_adrs": _clean_out_rows(get_adrs_for_plan(store, pn)),
        "validation_spikes": _clean_out_rows(get_spikes_for_plan(store, pn)),
        "related_studies": _clean_out_rows(get_studies_for_plan(store, pn)),
        "dependencies": _clean_out_rows(get_plan_dependencies(store, pn)),
        "open_findings": _clean_out_rows(all_findings),
        "open_backlog_items": _clean_out_rows(open_backlog),
        "reviewer_hints": reviewer_hints,
        "meta": meta,
    }
    return apply_detail(payload, arguments.get("detail"))


def _tool_prepare_implementation(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any], root: Path
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
    deps = get_plan_dependencies(store, int(pn))

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

    from agentscaffold.mcp.detail import apply_detail
    from agentscaffold.mcp.plan_card import build_plan_card

    payload = {
        "plan_number": pn,
        "plan_card": build_plan_card(store, int(pn), root=root),
        "brief": brief,
        "impacted_files": per_file,
        "dependencies": deps,
        "dep_status": [
            {"plan": d.get("dep.number"), "status": d.get("dep.status", "unknown")} for d in deps
        ],
        "meta": meta,
    }
    return apply_detail(payload, arguments.get("detail"))


def _tool_compare_plans(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    """Composite: compare two plans for overlap and conflicts."""
    from agentscaffold.review.filters import (
        meaningful_plan_file_overlap,
        normalize_plan_status,
        rank_lead_overlap,
        resolve_overlap_noise_paths,
    )
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

    configured = getattr(getattr(config, "graph", None), "overlap_noise_paths", None)
    noise_paths = resolve_overlap_noise_paths(configured)
    meaningful, noise_shared = meaningful_plan_file_overlap(
        files_a, files_b, noise_paths=noise_paths
    )
    lead = rank_lead_overlap(meaningful, limit=5)
    only_a = sorted(f for f in (files_a - files_b) if f)
    only_b = sorted(f for f in (files_b - files_a) if f)

    return {
        "plan_a": {
            "number": pa,
            "title": plan_a.get("p.title"),
            "status": plan_a.get("p.status"),
            "status_normalized": normalize_plan_status(plan_a.get("p.status")),
        },
        "plan_b": {
            "number": pb,
            "title": plan_b.get("p.title"),
            "status": plan_b.get("p.status"),
            "status_normalized": normalize_plan_status(plan_b.get("p.status")),
        },
        "shared_files": meaningful,
        "lead_shared_files": lead,
        "lead_overlap": lead[0] if lead else None,
        "only_in_a": only_a,
        "only_in_b": only_b,
        "overlap_count": len(meaningful),
        "overlap_noise_filtered": noise_shared,
        "overlap_noise_filtered_count": len(noise_shared),
        "conflict_risk": ("high" if len(meaningful) > 3 else "medium" if meaningful else "low"),
        "conflict_risk_basis": (
            "meaningful shared impacted-file count (>3 high, >=1 medium, 0 low); "
            "ubiquitous governance docs excluded; lead_shared_files ranks code/config first"
        ),
        "graph_warning": _empty_graph_warning(store.get_stats()),
        "meta": meta,
    }


def _tool_staleness_check(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    """Composite: check if a plan is stale."""
    from agentscaffold.review.filters import (
        meaningful_plan_file_overlap,
        normalize_plan_file_path,
        normalize_plan_status,
        rank_lead_overlap,
        resolve_overlap_noise_paths,
    )
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

    configured = getattr(getattr(config, "graph", None), "overlap_noise_paths", None)
    noise_paths = resolve_overlap_noise_paths(configured)

    all_plans = get_all_plans(store)
    # Frequency map: how many completed plans touch each path (Plan 247 demotion).
    path_frequency: dict[str, int] = {}
    completed_file_sets: list[tuple[Any, dict[str, Any], set[str]]] = []
    for p in all_plans:
        other_num = p.get("p.number")
        if other_num == pn or not _is_plan_complete(p.get("p.status")):
            continue
        if other_num is None:
            continue
        other_files = {f.get("f.path", "") for f in get_plan_impacted_files(store, int(other_num))}
        completed_file_sets.append((other_num, p, other_files))
        for raw in other_files:
            if not raw:
                continue
            key = normalize_plan_file_path(raw)
            path_frequency[key] = path_frequency.get(key, 0) + 1

    overlapping_completed = []
    noise_filtered_total = 0
    all_meaningful: list[str] = []
    for other_num, p, other_files in completed_file_sets:
        meaningful, noise_shared = meaningful_plan_file_overlap(
            plan_files,
            other_files,
            noise_paths=noise_paths,
            path_frequency=path_frequency,
        )
        noise_filtered_total += len(noise_shared)
        if meaningful:
            all_meaningful.extend(meaningful)
            overlapping_completed.append(
                {
                    "plan": other_num,
                    "title": p.get("p.title"),
                    "shared_files": meaningful,
                    "lead_shared_files": rank_lead_overlap(meaningful, limit=3),
                    "overlap_noise_filtered": noise_shared,
                }
            )

    studies = get_studies_for_plan(store, pn)
    lead = rank_lead_overlap(all_meaningful, limit=5)

    signals: list[str] = []
    if overlapping_completed:
        if lead:
            signals.append(
                f"{len(overlapping_completed)} completed plans overlap; lead shared path: {lead[0]}"
            )
        else:
            signals.append(
                f"{len(overlapping_completed)} completed plans overlap with meaningful "
                "impacted files"
            )
    if studies:
        for s in studies:
            outcome = s.get("s.outcome", "")
            if outcome and "baseline" in outcome.lower():
                signals.append(
                    f"Study {s.get('s.studyId')} outcome '{outcome}' may contradict approach"
                )

    from agentscaffold.mcp.plan_card import build_plan_card

    return {
        "plan_number": pn,
        "plan_title": plan.get("p.title"),
        "plan_status": plan.get("p.status"),
        "plan_status_normalized": normalize_plan_status(plan.get("p.status")),
        "last_updated": plan.get("p.lastUpdated"),
        "plan_card": build_plan_card(store, int(pn), plan_row=plan),
        "stale_signals": signals,
        "is_stale": bool(signals),
        "lead_shared_files": lead,
        "lead_overlap": lead[0] if lead else None,
        # An empty graph produces no overlap/study signals, which reads as a
        # confident "not stale". Surface that the absence may be unconfirmed.
        "graph_warning": _empty_graph_warning(store.get_stats()),
        "overlapping_completed_plans": overlapping_completed,
        "overlap_noise_filtered_count": noise_filtered_total,
        "related_studies": [
            {"id": s.get("s.studyId"), "outcome": s.get("s.outcome")} for s in studies
        ],
        "meta": meta,
    }


def _tool_prepare_rewrite(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    """Composite: superset of staleness check plus rewrite context."""
    staleness = _tool_staleness_check(store, arguments, meta, config)

    from agentscaffold.review.queries import get_all_plans, get_plan_dependencies

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}
    deps = get_plan_dependencies(store, pn)

    all_plans = get_all_plans(store)
    recent_completed = [
        {"number": p.get("p.number"), "title": p.get("p.title")}
        for p in all_plans
        if _is_plan_complete(p.get("p.status"))
    ][:10]

    staleness["dependencies"] = deps
    staleness["recent_completed_plans"] = recent_completed
    return staleness


def _tool_prepare_retro(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
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


def _tool_orient(
    store: Any,
    meta: dict[str, Any],
    root: Path,
    config: Any,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Composite: session orientation with stats + workflow state."""
    from agentscaffold.mcp.coverage import repo_coverage
    from agentscaffold.mcp.detail import apply_detail
    from agentscaffold.mcp.plan_card import build_plan_card
    from agentscaffold.review.queries import (
        get_all_adrs,
        get_all_plans,
        get_all_studies,
        get_hot_files,
        get_open_backlog_items,
    )

    arguments = arguments or {}
    stats = store.get_stats()
    coverage = repo_coverage(store)
    plans = get_all_plans(store)
    hot_files = get_hot_files(store, limit=5)
    studies = get_all_studies(store)
    adrs = get_all_adrs(store)
    workflow = _parse_workflow_state(root, config)

    recent_plans = plans[:10]
    recent_cards = []
    for p in recent_plans:
        cleaned = _with_normalized_status([p])[0]
        pn = p.get("p.number")
        if pn is not None:
            card = build_plan_card(store, int(pn), root=root, plan_row=p)
            if card:
                cleaned["plan_card"] = {
                    "unchecked_steps": card.get("unchecked_steps"),
                    "checked_steps": card.get("checked_steps"),
                    "impacted_file_count": card.get("impacted_file_count"),
                    "open_finding_count": card.get("open_finding_count"),
                    "last_updated": card.get("last_updated"),
                }
        recent_cards.append(cleaned)

    open_backlog = get_open_backlog_items(store, limit=3)

    try:
        _bl_proj = _current_project_or_none()
        _bl_proj_filter = (
            f" AND project = '{_bl_proj.replace(chr(39), chr(39) * 2)}'" if _bl_proj else ""
        )
        count_rows = store.query(
            "SELECT COUNT(*) AS cnt FROM BacklogItem"
            f" WHERE status NOT IN ('archived', 'unblockable'){_bl_proj_filter}"
        )
        open_backlog_count = count_rows[0]["cnt"] if count_rows else 0
    except Exception:
        open_backlog_count = 0

    active_adrs = [a for a in adrs if _adr_is_active(a.get("a.status"))]

    # Plan 247: fold next_action + compact plan_progress into orient so agents
    # do not need a second hop after session start.
    from agentscaffold.mcp.next_action import next_actions

    actions_payload = next_actions(
        store,
        root=root,
        config=config,
        workflow=workflow,
        meta=meta,
        plan_number=arguments.get("plan_number"),
    )
    plan_progress: list[dict[str, Any]] = []
    for card_row in recent_cards:
        pc = card_row.get("plan_card")
        if not pc:
            continue
        plan_progress.append(
            {
                "plan_number": card_row.get("number") or card_row.get("p.number"),
                "title": card_row.get("title") or card_row.get("p.title"),
                "status": card_row.get("status") or card_row.get("p.status"),
                "unchecked_steps": pc.get("unchecked_steps"),
                "checked_steps": pc.get("checked_steps"),
                "open_finding_count": pc.get("open_finding_count"),
            }
        )

    result = {
        "stats": stats,
        "coverage": coverage,
        "graph_warning": _empty_graph_warning(stats),
        "recent_plans": recent_cards,
        "hot_files": _clean_out_rows(hot_files),
        "recent_studies": _clean_out_rows(studies[:5]),
        "active_adrs": _clean_out_rows(active_adrs),
        "workflow_state": workflow,
        "open_backlog_count": open_backlog_count,
        "open_backlog_top3": _clean_out_rows(open_backlog),
        "recommended_actions": actions_payload.get("actions", []),
        "plan_progress": plan_progress[:5],
        "next_action_focus": actions_payload.get("focus_plan"),
        "meta": meta,
    }
    return apply_detail(result, arguments.get("detail"))


def _tool_find_studies(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    """Composite: search studies by topic and/or outcome."""
    from agentscaffold.review.queries import get_studies_by_outcome, get_studies_by_tags

    topic = arguments.get("topic", "")
    outcome = arguments.get("outcome")
    scope = _scope_args(arguments)

    results: list[dict[str, Any]] = []
    if topic:
        results = get_studies_by_tags(store, [topic], **scope)

    if outcome:
        outcome_results = get_studies_by_outcome(store, outcome, **scope)
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
        "studies": _clean_out_rows(results),
        "count": len(results),
        **_scope_echo(scope),
        "meta": meta,
    }


def _tool_prior_experiments(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    config: Any | None = None,
) -> dict[str, Any]:
    """Composite: all experiments related to a plan."""
    from agentscaffold.review.filters import (
        is_overlap_noise_path,
        resolve_overlap_noise_paths,
    )
    from agentscaffold.review.queries import (
        get_plan_impacted_files,
        get_studies_for_file,
        get_studies_for_plan,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    direct = get_studies_for_plan(store, pn)

    configured = getattr(getattr(config, "graph", None), "overlap_noise_paths", None)
    noise_paths = resolve_overlap_noise_paths(configured)

    impacted = get_plan_impacted_files(store, pn)
    file_studies: list[dict[str, Any]] = []
    seen_ids: set[str] = {s.get("s.studyId", "") for s in direct}
    noise_skipped = 0
    for f in impacted:
        fpath = f.get("f.path", "")
        if is_overlap_noise_path(fpath, noise_paths):
            noise_skipped += 1
            continue
        for s in get_studies_for_file(store, fpath):
            sid = s.get("s.studyId", "")
            if sid not in seen_ids:
                seen_ids.add(sid)
                file_studies.append(s)

    return {
        "plan_number": pn,
        "directly_referenced": _clean_out_rows(direct),
        "file_overlap_studies": _clean_out_rows(file_studies),
        "total_count": len(direct) + len(file_studies),
        "overlap_noise_filtered_count": noise_skipped,
        "meta": meta,
    }


def _tool_find_adrs(store: Any, arguments: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """Composite: search ADRs by topic keyword and/or status."""
    from agentscaffold.review.queries import get_all_adrs

    topic = arguments.get("topic", "")
    status_filter = arguments.get("status")
    scope = _scope_args(arguments)

    all_adrs = get_all_adrs(store, **scope)
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
        "adrs": _clean_out_rows(results),
        "count": len(results),
        **_scope_echo(scope),
        "meta": meta,
    }


def _tool_decision_context(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    """Composite: full decision chain for a plan (ADRs, spikes, studies, deps)."""
    from agentscaffold.review.queries import (
        get_adrs_for_plan,
        get_plan_by_number,
        get_plan_dependencies,
        get_plan_projects,
        get_spikes_for_plan,
        get_studies_for_plan,
    )

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}

    scope = _scope_args(arguments)
    # A decision chain is a single plan's history, so federating it cannot mean
    # "merge every project's plan 249" -- that would splice unrelated ADRs and
    # spikes into one narrative. It means "find which project owns this number".
    # If more than one does, the number alone is not an answer, so refuse and
    # name the candidates rather than silently returning whichever came first.
    if scope["all_projects"]:
        from agentscaffold.mcp.errors import AmbiguousProjectError, to_error_response

        owners = get_plan_projects(store, pn)
        if len(owners) > 1:
            return {
                **to_error_response(
                    AmbiguousProjectError(
                        f"Plan {pn} exists in {len(owners)} projects; "
                        "name one with the 'project' argument.",
                        candidates=owners,
                    )
                ),
                "meta": meta,
            }
        scope = {"project": owners[0] if owners else None, "all_projects": False}

    plan = get_plan_by_number(store, pn, **scope)
    if not plan:
        return {"error": f"Plan {pn} not found.", "meta": meta}

    adrs = get_adrs_for_plan(store, pn, **scope)
    spikes = get_spikes_for_plan(store, pn, **scope)
    studies = get_studies_for_plan(store, pn, **scope)
    deps = get_plan_dependencies(store, pn, **scope)

    from agentscaffold.review.filters import normalize_plan_status

    return {
        "plan_number": pn,
        "plan_title": plan.get("p.title"),
        "plan_status": plan.get("p.status"),
        "plan_status_normalized": normalize_plan_status(plan.get("p.status")),
        "governing_adrs": _clean_out_rows(adrs),
        "validation_spikes": _clean_out_rows(spikes),
        "supporting_studies": _clean_out_rows(studies),
        "plan_dependencies": _clean_out_rows(deps),
        "has_full_decision_chain": bool(adrs or spikes or studies),
        **({"project": scope["project"]} if scope["project"] else {}),
        # If the graph is empty the chain looks absent even when it exists in
        # docs; flag so a False is not read as a confirmed "no decisions".
        "graph_warning": _empty_graph_warning(store.get_stats()),
        "meta": meta,
    }


def _tool_record_finding(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    """Record a review finding in the knowledge graph."""
    from agentscaffold.graph.findings import record_finding  # noqa: PLC0415

    plan_number = arguments.get("plan_number")
    review_type = arguments.get("review_type", "")
    category = arguments.get("category", "")
    finding = arguments.get("finding", "")

    if plan_number is None or not review_type or not category or not finding:
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
        project=_current_project_or_none(),
    )
    result["meta"] = meta
    return result


def _tool_resolve_finding(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    """Mark a ReviewFinding as resolved."""
    from agentscaffold.graph.findings import resolve_finding  # noqa: PLC0415

    finding_id = arguments.get("finding_id", "")
    resolution = arguments.get("resolution", "")

    if not finding_id or not resolution:
        return {"error": "finding_id and resolution are required.", "meta": meta}

    result = resolve_finding(
        store, finding_id, resolution=resolution, project=_current_project_or_none()
    )
    return _wrap_resolve_result(
        result,
        meta,
        kind="ReviewFinding",
        remediation=(
            "Pass the rf:: id from scaffold_record_finding or from "
            "orient / prepare_review. A miss returns not_found rather than "
            "a fake resolve."
        ),
    )


def _wrap_resolve_result(
    result: dict[str, Any],
    meta: dict[str, Any],
    *,
    kind: str,
    remediation: str,
) -> dict[str, Any]:
    """Attach MCP error_code when a resolve write matched nothing or was ambiguous."""
    from agentscaffold.mcp.errors import AmbiguousIdError, NotFoundError  # noqa: PLC0415

    status = result.get("status")
    if status == "not_found":
        payload = NotFoundError(
            f"{kind} not found: {result.get('id')!r}.",
            remediation=remediation,
        ).to_response()
        payload["id"] = result.get("id")
        payload["status"] = "not_found"
        payload["meta"] = meta
        return payload
    if status == "ambiguous":
        raw = result.get("candidates") or []
        labels = []
        for item in raw:
            if isinstance(item, dict):
                iid = item.get("id", "")
                title = item.get("title") or ""
                labels.append(f"{iid}: {title}" if title else str(iid))
            else:
                labels.append(str(item))
        payload = AmbiguousIdError(
            f"Multiple {kind} rows match {result.get('id')!r}.",
            candidates=labels,
            remediation=remediation,
        ).to_response()
        payload["id"] = result.get("id")
        payload["status"] = "ambiguous"
        payload["meta"] = meta
        return payload
    result["meta"] = meta
    return result


def _tool_record_findings_batch(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
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
        project=_current_project_or_none(),
    )
    result["meta"] = meta
    return result


def _tool_record_backlog_item(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
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
            project=_current_project_or_none(),
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
        project=_current_project_or_none(),
    )
    result["meta"] = meta
    return result


def _tool_resolve_backlog_item(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    """Mark a BacklogItem as archived (completed)."""
    from agentscaffold.graph.backlog import resolve_backlog_item  # noqa: PLC0415

    item_id = arguments.get("item_id", "")
    if not item_id:
        return {"error": "item_id is required.", "meta": meta}

    result = resolve_backlog_item(
        store,
        item_id,
        resolution=arguments.get("resolution", ""),
        project=_current_project_or_none(),
    )
    return _wrap_resolve_result(
        result,
        meta,
        kind="BacklogItem",
        remediation=(
            "Pass the bi:: id from scaffold_record_backlog_item or from "
            "orient.open_backlog_top3 / prepare_review.open_backlog_items. "
            "Human IDs like DQ-043 are accepted when they uniquely prefix a title."
        ),
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Agent tool pack handlers (Plan 246)
# ---------------------------------------------------------------------------


def _tool_diff_plan_vs_code(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any], root: Path
) -> dict[str, Any]:
    from agentscaffold.mcp.diff_plan import diff_plan_vs_code

    pn = arguments.get("plan_number")
    if pn is None:
        return {"error": "plan_number is required.", "meta": meta}
    result = diff_plan_vs_code(store, int(pn), root=root)
    result["meta"] = meta
    return result


def _tool_grep_graph(arguments: dict[str, Any], meta: dict[str, Any], root: Path) -> dict[str, Any]:
    from agentscaffold.mcp.workspace_grep import workspace_grep

    result = workspace_grep(
        root,
        str(arguments.get("pattern", "")),
        path=arguments.get("path"),
        glob=arguments.get("glob"),
        max_hits=int(arguments.get("max_hits") or 50),
    )
    result["meta"] = meta
    return result


def _tool_why_empty(store: Any, arguments: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    from agentscaffold.mcp.why_empty import explain_why_empty

    result = explain_why_empty(
        store,
        kind=str(arguments.get("kind") or "structural"),
        target=str(arguments.get("target") or ""),
        query=str(arguments.get("query") or ""),
        meta=meta,
        arguments_hint=arguments,
    )
    result["meta"] = meta
    return result


def _tool_next_action(
    store: Any,
    arguments: dict[str, Any],
    meta: dict[str, Any],
    root: Path,
    config: Any,
) -> dict[str, Any]:
    from agentscaffold.mcp.next_action import next_actions

    workflow = _parse_workflow_state(root, config)
    pn = arguments.get("plan_number")
    result = next_actions(
        store,
        root=root,
        config=config,
        workflow=workflow,
        meta=meta,
        plan_number=int(pn) if pn is not None else None,
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
    store: Any, arguments: dict[str, Any], meta: dict[str, Any], root: Path, config: Any
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
    # Expose enough counts to confirm parsing actually ran. `functions` alone is
    # misleading (top-level functions only); methods/classes/edges reveal whether
    # the structural graph is populated.
    orient_summary = {
        "schema_version": stats.get("schema_version"),
        "files": stats.get("files", 0),
        "functions": stats.get("functions", 0),
        "methods": stats.get("methods", 0),
        "classes": stats.get("classes", 0),
        "imports_edges": stats.get("imports_edges", 0),
        "calls_edges": stats.get("calls_edges", 0),
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
    # Only high-value findings are PERSISTED (default: high severity), and only
    # if not already recorded for this plan. The full challenge/gap lists remain
    # in the returned payload for the reviewing agent. This stops every review
    # run from injecting ~20 low-precision co-occurrence findings into the graph.
    candidate_findings: list[dict[str, Any]] = []
    for c in review_result.get("challenges", []):
        candidate_findings.append(
            {
                "category": c.get("category", "challenge"),
                "finding": c.get("text", ""),
                "severity": c.get("severity", "medium"),
                "file_paths": _finding_file_paths(c.get("evidence")),
            }
        )
    for g in review_result.get("gaps", []):
        candidate_findings.append(
            {
                "category": g.get("category", "gap"),
                "finding": g.get("text", ""),
                "severity": g.get("severity", "medium"),
                "file_paths": _finding_file_paths(g.get("evidence")),
            }
        )

    findings_to_write = _select_findings_to_persist(
        candidate_findings, review_result.get("open_findings", [])
    )

    findings_written = {"ids": [], "count": 0}
    dry_run = bool(arguments.get("dry_run"))
    if findings_to_write and not dry_run:
        findings_written = record_findings_batch(
            store,
            plan_number=pn,
            review_type="pre_review",
            findings=findings_to_write,
            project=_current_project_or_none(),
        )

    # --- Stamp Plan.reviewedAt ---
    reviewed_at = None if dry_run else stamp_plan_reviewed(store, pn)

    # --- Build proceed_prompt ---
    n_findings = findings_written["count"]
    if dry_run:
        proceed_prompt = (
            f"Pre-review dry_run for Plan {pn}. "
            f"{len(findings_to_write)} findings would be recorded (not written). "
            "Re-run without dry_run to persist and stamp reviewedAt."
        )
    else:
        proceed_prompt = (
            f"Pre-review complete for Plan {pn}. "
            f"{n_findings} findings recorded to graph. "
            "Ready to proceed with implementation, or would you like to discuss anything first?"
        )

    from agentscaffold.mcp.plan_card import build_plan_card

    return {
        "plan_number": pn,
        "dry_run": dry_run,
        "plan_card": build_plan_card(store, int(pn), root=root),
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
            "candidates": len(candidate_findings),
            "would_write_count": len(findings_to_write) if dry_run else n_findings,
            "persist_policy": "high_severity_only",
        },
        "reviewed_at": reviewed_at,
        "proceed_prompt": proceed_prompt,
        "meta": meta,
    }


def _select_findings_to_persist(
    candidates: list[dict[str, Any]],
    existing_open: list[dict[str, Any]],
    *,
    min_severity: str = "high",
) -> list[dict[str, Any]]:
    """Filter review findings down to the set worth persisting to the graph.

    Keeps only findings at or above ``min_severity`` (default ``high``) and drops
    any that duplicate an already-open finding for the plan (matched on category +
    normalized finding text). This makes ``scaffold_begin_plan`` idempotent: a
    re-run does not multiply findings.
    """
    order = {"low": 0, "medium": 1, "high": 2}
    threshold = order.get(min_severity, 2)

    def _norm(text: str) -> str:
        return " ".join(str(text).split()).strip().lower()

    existing_keys = {
        (str(r.get("rf.category", "")).lower(), _norm(r.get("rf.finding", "")))
        for r in existing_open
    }

    selected: list[dict[str, Any]] = []
    batch_keys: set[tuple[str, str]] = set()
    for f in candidates:
        if order.get(f.get("severity", "medium"), 1) < threshold:
            continue
        key = (str(f.get("category", "")).lower(), _norm(f.get("finding", "")))
        if key in existing_keys or key in batch_keys:
            continue
        batch_keys.add(key)
        selected.append(f)
    return selected


def _tool_complete_plan(
    store: Any, arguments: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
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
    dry_run = bool(arguments.get("dry_run"))
    if retro_findings and not dry_run:
        findings_written = record_findings_batch(
            store,
            plan_number=pn,
            review_type="post_retro",
            findings=retro_findings,
            project=_current_project_or_none(),
        )

    # --- Write backlog items if provided ---
    backlog_items_arg = arguments.get("backlog_items")
    backlog_written = {"ids": [], "count": 0}
    if backlog_items_arg and not dry_run:
        backlog_written = record_backlog_items_batch(
            store,
            plan_number=pn,
            items=backlog_items_arg,
            project=_current_project_or_none(),
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
        "dry_run": dry_run,
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
            "would_write_count": len(retro_findings) if dry_run else findings_written["count"],
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

    # Routing guidance is static text and is served before the graph check: a
    # fresh clone with no graph is exactly when an agent needs the policy most.
    if uri == GUIDANCE_ROUTING_URI:
        return {"content": read_guidance_routing()}

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
