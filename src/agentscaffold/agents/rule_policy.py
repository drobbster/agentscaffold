"""Shared rule composition for MCP-first agent routing policies."""

from __future__ import annotations

from agentscaffold.config import ScaffoldConfig


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
        "- Decision lineage (ADR/spike/study) -> `scaffold_decision_context` first",
        "- Symbol context/impact -> `scaffold_context` or `scaffold_impact` first",
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
        lines.append("Trigger phrases:")
        for intent in intents:
            if quote_intents:
                lines.append(f'- "{intent}"')
            else:
                lines.append(f"- {intent}")
        lines.append("")
    return lines


def generate_rule_policy_document(
    *,
    config: ScaffoldConfig,
    title: str,
    intro_lines: list[str] | None = None,
    quote_intents: bool = True,
) -> str:
    """Build a platform rule document with policy, guardrails, and intents."""
    lines: list[str] = [f"# {title}", ""]
    if intro_lines:
        lines.extend(intro_lines)
        lines.append("")
    lines.extend(_tool_selection_policy_lines())
    lines.extend(_governance_guardrails_lines(config))
    lines.extend(_intent_map_lines(quote_intents=quote_intents))
    return "\n".join(lines).rstrip() + "\n"
