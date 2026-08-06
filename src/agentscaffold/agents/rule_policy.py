"""Shared rule composition for MCP-first agent routing policies.

Used by Cursor (``.mdc``), Claude Code (``CLAUDE.md``), Windsurf
(``.windsurfrules``), and the generic prompt snippet so every install gets the
same MCP-first + call-compression controls regardless of IDE.
"""

from __future__ import annotations

from agentscaffold.config import ScaffoldConfig

# Notes appended under specific Intent Map entries (Plan 247 call compression).
_INTENT_NOTES: dict[str, str] = {
    "scaffold_orient": (
        "Primary session router. Prefer its `recommended_actions`, "
        "`plan_progress`, and `next_action_focus` over a follow-up "
        "`scaffold_next_action` call."
    ),
    "scaffold_diff_plan_vs_code": (
        "Preferred mid-implementation progress check (next unchecked step, "
        "disk/graph presence, symbol spot-checks). Prefer over re-reading the "
        "full plan body for status."
    ),
    "scaffold_search": (
        "On empty results, read inline `why_empty` and `grep_fallback` before "
        "calling `scaffold_why_empty` or `scaffold_grep_graph`."
    ),
    "scaffold_impact": (
        "On empty importers/callers, read inline `why_empty` and "
        "`grep_fallback` before extra tool hops."
    ),
    "scaffold_context": (
        "When a symbol is missing, read inline `why_empty` / `grep_fallback` "
        "on that response before a separate diagnosis call."
    ),
    "scaffold_why_empty": (
        "Fallback only. Prefer inline `why_empty` on empty "
        "search/impact/context responses when present."
    ),
    "scaffold_grep_graph": (
        "Fallback only. Prefer inline `grep_fallback` on empty search/impact "
        "when present; otherwise use for low coverage / non-parsed languages."
    ),
    "scaffold_next_action": (
        "Fallback only. Prefer `recommended_actions` from `scaffold_orient` "
        "when present."
    ),
}


def _tool_selection_policy_lines() -> list[str]:
    return [
        "## AgentScaffold Tool Selection Policy (MCP-First with Practical Fallback)",
        "",
        "You MUST attempt AgentScaffold MCP tools first when the request matches a known intent.",
        "If MCP output is insufficient, direct file reads/search are allowed.",
        "",
        "## Required Procedure",
        "",
        "1. Classify the request into an AgentScaffold intent.",
        "2. If matched, call the mapped MCP tool first.",
        "3. If the tool fails or is insufficient, fall back to direct reads/search.",
        "4. Before fallback, state one short reason.",
        "5. If intent is unclear, ask one concise clarification question.",
        "",
        "## Fallback Is Allowed When",
        "",
        "- MCP tool errors or times out.",
        "- Graph/index is unavailable or stale.",
        "- MCP output does not contain the specific detail needed.",
        "",
        "## High-Value MCP-First Routes",
        "",
        "- Plan review/gap/challenge -> `scaffold_prepare_review` first",
        "- Project status/blockers/next steps -> `scaffold_orient` first",
        "  (use embedded `recommended_actions` / `plan_progress`; do not also",
        "  call `scaffold_next_action` unless those fields are absent)",
        "- Mid-implementation progress / what's left on a plan ->",
        "  `scaffold_diff_plan_vs_code` first",
        "- Decision lineage (ADR/spike/study) -> `scaffold_decision_context` first",
        "- Symbol context/impact -> `scaffold_context` or `scaffold_impact` first",
        "- Empty search/impact/context -> consume inline `why_empty` +",
        "  `grep_fallback` on that same response before extra tool hops",
        "",
        "## Call Compression Discipline",
        "",
        "Prefer fewer, richer MCP calls. Do not undo fused responses with",
        "redundant follow-ups:",
        "",
        "- After `scaffold_orient`, act on `recommended_actions` /",
        "  `plan_progress` / `next_action_focus` instead of calling",
        "  `scaffold_next_action` again.",
        "- After empty `scaffold_search`, `scaffold_impact`, or missing-symbol",
        "  `scaffold_context`, use inline `why_empty` and `grep_fallback`",
        "  instead of immediately calling `scaffold_why_empty` or",
        "  `scaffold_grep_graph`.",
        "- Use standalone `scaffold_why_empty`, `scaffold_grep_graph`, and",
        "  `scaffold_next_action` only when fused fields are missing or",
        "  insufficient.",
        "- Prefer `scaffold_diff_plan_vs_code` over dumping or re-reading the",
        "  full plan file just to check progress.",
        "",
    ]


def _graph_trust_discipline_lines() -> list[str]:
    return [
        "## Graph Trust Discipline (Avoid Context Blindness)",
        "",
        "AgentScaffold's graph is a fast first-pass, not ground truth. Treat its",
        "structural results as evidence to narrow your search, not as proof.",
        "",
        "- An empty result (`0 callers`, `0 importers`, no impact) means",
        "  `unconfirmed`, NOT `unused`. Do not conclude code is safe to change",
        "  from an empty graph result alone.",
        "- When search/impact/context returns empty, read `why_empty` and",
        "  `grep_fallback` on that same response before a follow-up tool or",
        "  treating the target as unused.",
        "- Call/import edges exist ONLY for parsed languages (python, javascript,",
        "  typescript, go, rust, java, c, cpp). Markdown, YAML, shell, SQL, JSON,",
        "  and config files are invisible to structural queries. Check the",
        "  `coverage` field on tool output; heed any `caveat`.",
        "- Static analysis cannot see dynamic dispatch, reflection (`getattr`),",
        "  dependency-injection registries, or config/string-driven wiring.",
        "- Before changing safety-critical, cross-language, or dynamically-wired",
        "  code, confirm usage with a text search (grep) in addition to the graph",
        "  (inline `grep_fallback` counts when present).",
        "- If `scaffold_orient` reports low parsed coverage, lean more on grep.",
        "",
    ]


def _workspace_scope_discipline_lines() -> list[str]:
    return [
        "## Multi-Project Workspace Discipline",
        "",
        "If the repo is part of a multi-project workspace (a `workspace.yaml` at the",
        "workspace root lists more than one project), several projects share one",
        "graph. Otherwise (a lone repo) this section is a no-op -- there is exactly",
        "one project and nothing is scoped.",
        "",
        "- Reads default to the CURRENT project (resolved from the working",
        "  directory): search and governance queries (plans, findings, learnings,",
        "  studies, ADRs) return only this project's knowledge. Plan numbers and",
        "  file paths are NOT unique across projects, so do not assume a result",
        "  belongs to a sibling.",
        "- VIA MCP TOOLS the server runs from one fixed directory and cannot infer",
        "  which project you are editing. On every project-scoped tool call, pass",
        "  `working_path` = the file or dir you are working on; the server resolves",
        "  the owning project from it and scopes the read accordingly. Omitting it",
        "  falls back to the server's default project.",
        "- To look at another project, pass `project=<name>` (tools) / `--project",
        "  <name>` (CLI); to search across all of them, pass `all_projects=true` /",
        "  `--all-projects` (federated results carry a `project` provenance field --",
        "  always report which project a cross-project hit came from).",
        "- `scaffold graph duplicates` surfaces cross-project near-duplicate",
        "  definitions (shared-library reuse candidates); treat hits as advisory.",
        "- Scoping is a relevance boundary within a single trust domain, not a",
        "  security isolation boundary. When unsure which project you are in, run",
        "  `scaffold workspace list`.",
        "",
    ]


def _governance_guardrails_lines(config: ScaffoldConfig) -> list[str]:
    lines = [
        "## Governance Guardrails (Always Apply)",
        "",
        "- Read and follow `AGENTS.md` before every task.",
        "- Do NOT execute plans with incomplete review checklists.",
        "- Do NOT skip dependency verification.",
        "- Do NOT create interfaces without contracts.",
        "- Do NOT modify `docs/ai/system_architecture.md` without human approval.",
        "- Every feature or bug fix MUST include corresponding tests.",
    ]
    if not config.prohibitions.emojis:
        lines.append("- Emojis are forbidden in repository content.")
    if config.standards.core:
        standards = ", ".join(f"`{s}`" for s in config.standards.core)
        lines.append(f"- Follow core standards: {standards}.")
    lines.extend(
        [
            "",
            "## Intent Map",
            "",
        ]
    )
    return lines


def _intent_map_lines(quote_intents: bool) -> list[str]:
    from agentscaffold.mcp.server import TOOL_INTENTS

    lines: list[str] = []
    for tool_name, intents in TOOL_INTENTS.items():
        lines.append(f"### {tool_name}")
        lines.append("")
        note = _INTENT_NOTES.get(tool_name)
        if note:
            lines.append(f"Note: {note}")
            lines.append("")
        lines.append("Trigger phrases:")
        for intent in intents:
            if quote_intents:
                lines.append(f'- "{intent}"')
            else:
                lines.append(f"- {intent}")
        lines.append("")
    return lines


def generate_canonical_guidance_body(config: ScaffoldConfig) -> str:
    """Build the platform-invariant routing guidance (Plan 249 Step B2).

    This is the canonical source every per-project rule file is generated from,
    and the content served as the ``agentscaffold://guidance/routing`` resource.
    It deliberately carries no platform framing -- no frontmatter, no
    platform-specific title or intro -- because each platform wraps it in its
    own.
    """
    lines: list[str] = ["# AgentScaffold Routing Guidance", ""]
    lines.extend(_tool_selection_policy_lines())
    lines.extend(_graph_trust_discipline_lines())
    lines.extend(_workspace_scope_discipline_lines())
    lines.extend(_governance_guardrails_lines(config))
    lines.extend(_intent_map_lines(quote_intents=True))
    return "\n".join(lines).rstrip() + "\n"


def generate_rule_policy_document(
    *,
    config: ScaffoldConfig,
    title: str,
    intro_lines: list[str] | None = None,
    quote_intents: bool = True,
    always_apply: bool = False,
) -> str:
    """Build a platform rule document with policy, guardrails, and intents."""
    frontmatter = f"---\nalwaysApply: {str(always_apply).lower()}\n---\n\n"
    lines: list[str] = [f"# {title}", ""]
    if intro_lines:
        lines.extend(intro_lines)
        lines.append("")
    lines.extend(_tool_selection_policy_lines())
    lines.extend(_graph_trust_discipline_lines())
    lines.extend(_workspace_scope_discipline_lines())
    lines.extend(_governance_guardrails_lines(config))
    lines.extend(_intent_map_lines(quote_intents=quote_intents))
    return frontmatter + "\n".join(lines).rstrip() + "\n"
