# AgentScaffold Documentation

## Two Ways to Work

AgentScaffold supports two interaction modes that complement each other:

- **Natural Language + MCP (recommended for interactive sessions)**: Describe intent
  conversationally. The agent maps phrases like "review plan 42", "where did we leave off",
  or "is plan 12 stale" to the right MCP governance workflow automatically.
- **CLI / Automation (explicit + CI)**: Run `scaffold` commands directly for deterministic
  setup, verification, and unattended workflows. Always available as a fallback.

Most teams use NL+MCP for day-to-day flow and explicit CLI for verification steps
(`scaffold validate`, `scaffold graph verify`, `scaffold index --incremental`).

If you already used the governance framework before knowledge graph and MCP tooling,
see the "Migration Guide for Governance-First Users" section in the [User Guide](user-guide.md).

## Template Set Included by Init

When you run `scaffold init`, AgentScaffold installs the full core planning template set:

- `docs/ai/templates/plan_template.md` (feature)
- `docs/ai/templates/plan_template_bugfix.md` (bugfix)
- `docs/ai/templates/plan_template_refactor.md` (refactor)
- plus spike and study templates for discovery and experiment workflows

## Guides

| Document | Description |
|----------|-------------|
| [Getting Started](getting-started.md) | Installation, init, first plan, knowledge graph, review, execution, NL+MCP switch |
| [User Guide](user-guide.md) | Full session workflow, NL intent routing reference, greenfield onboarding, MCP tools (all 26), session tracking |
| [Platform Integration](platform-integration.md) | Cursor, Claude Code, Windsurf, Cline, Continue, aider, Codex, MCP setup, all MCP tools |
| [Configuration](configuration.md) | Full scaffold.yaml reference, gates, rigor presets |
| [Domain Packs](domain-packs.md) | Available packs, installation, using multiple packs |
| [Creating Domain Packs](creating-domain-packs.md) | Structure, manifest, prompts, standards |
| [Semi-Autonomous Guide](semi-autonomous-guide.md) | CLI/CI agent mode, session tracking, safety, notifications |
| [Importing Conversations](importing-conversations.md) | ChatGPT, markdown, Claude exports |
| [CI Integration](ci-integration.md) | scaffold ci setup, workflows, task runner |

## Quick NL Routing Reference

The most common trigger phrases and what they invoke:

| Say this... | Calls this tool |
|-------------|----------------|
| "review plan X" / "critique plan X" | `scaffold_prepare_review` |
| "implement plan X" / "begin building plan X" | `scaffold_prepare_implementation` |
| "where did we leave off" / "what's blocked" | `scaffold_orient` |
| "is plan X stale" / "is plan X still valid" | `scaffold_staleness_check` |
| "retro on plan X" / "post-implementation review" | `scaffold_prepare_retro` |
| "decision history for plan X" / "what ADR governs plan X" | `scaffold_decision_context` |
| "compare plan X and Y" / "do plans overlap" | `scaffold_compare_plans` |

For the full routing table (all 26 MCP tools + trigger phrases), see the
[NL Intent Routing Reference](user-guide.md#nl-intent-routing-reference) section of the User Guide.

## Internal (dev_docs/, not shipped to PyPI)

| Document | Description |
|----------|-------------|
| [Eval Findings and Improvement Plan](../dev_docs/eval-findings-and-improvement-plan.md) | Results from the 64-scenario evaluation harness, bugs found, and fixes applied |
