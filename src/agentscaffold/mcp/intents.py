"""Registry-owned trigger phrases (Plan 251 C1). Empty list is an explicit waiver."""

from __future__ import annotations

# Phrases copied from the former server.TOOL_INTENTS. Tools with no natural-
# language trigger (situational-only) must still appear with [].
INTENT_PHRASES: dict[str, list[str]] = {
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
        "where are we",
        "what should I work on now",
        "what are the next priorities",
        "latest blockers and what's next",
        "current blockers and next steps",
    ],
    "scaffold_session_start": [
        "start a working session",
        "open a scaffold session",
        "begin recording this session",
        "start session tracking",
    ],
    "scaffold_session_end": [
        "end this session",
        "close the working session",
        "end session with summary",
        "close this working session",
    ],
    "scaffold_session_record_decision": [
        "record this decision",
        "log a session decision",
        "note a strategic decision",
        "record this architectural call",
        "capture this operational decision",
    ],
    "scaffold_session_context": [
        "recent session context",
        "show session context",
    ],
    "scaffold_session_list": [
        "list sessions",
        "show recent sessions",
        "list working sessions",
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
    # Explicit empty-intents waiver (situational-only / no NL trigger list).
    "scaffold_context": [],
    "scaffold_impact": [],
    "scaffold_projects": [],
    "scaffold_query": [],
    "scaffold_recall_governance": [],
    "scaffold_review_context": [],
    "scaffold_stats": [],
    "scaffold_validate": [],
}


class MissingIntentMetadataError(RuntimeError):
    """A registered tool has no INTENT_PHRASES entry (not even an empty waiver)."""


def intent_phrases() -> dict[str, list[str]]:
    """Trigger phrases keyed by tool name. Empty list is a waiver, not a miss."""
    return {name: list(phrases) for name, phrases in INTENT_PHRASES.items()}


def assert_intent_coverage(tool_names: list[str]) -> None:
    """Fail generation when a registered tool has no routing metadata row."""
    missing = [name for name in tool_names if name not in INTENT_PHRASES]
    if missing:
        raise MissingIntentMetadataError(
            "Registered tools have no INTENT_PHRASES row (empty list is the "
            f"waiver): {', '.join(missing)}"
        )
