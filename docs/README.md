# AgentScaffold Documentation

## Choose Your Path

AgentScaffold supports two interaction modes:

- **Interactive Prompting Path (NL + MCP)**: You work in chat with your agent, and the
  agent maps natural-language intent to governance and graph workflows.
- **CLI / Automation Path**: You run explicit `scaffold` commands for deterministic
  setup, verification, and unattended workflows.

If you already used the governance framework before knowledge graph and MCP tooling,
start here:

- [Migrating Governance Workflow to NL + MCP](migrating-governance-to-nl-mcp.md)

## Template Set Included by Init

When you run `scaffold init`, AgentScaffold installs the full core planning template set:

- `docs/ai/templates/plan_template.md` (feature)
- `docs/ai/templates/plan_template_bugfix.md` (bugfix)
- `docs/ai/templates/plan_template_refactor.md` (refactor)
- plus spike and study templates for discovery and experiment workflows

## Guides

| Document | Description |
|----------|-------------|
| [Getting Started](getting-started.md) | Installation, init, first plan, knowledge graph, review, execution |
| [User Guide](user-guide.md) | Session workflow, knowledge graph, greenfield onboarding, review patterns, MCP tools |
| [Migrating Governance to NL + MCP](migrating-governance-to-nl-mcp.md) | Command-heavy to conversational migration while preserving governance rigor |
| [Configuration](configuration.md) | Full scaffold.yaml reference, gates, rigor presets |
| [Domain Packs](domain-packs.md) | Available packs, installation, using multiple packs |
| [Creating Domain Packs](creating-domain-packs.md) | Structure, manifest, prompts, standards |
| [Semi-Autonomous Guide](semi-autonomous-guide.md) | CLI/CI agent mode, session tracking, safety, notifications |
| [Importing Conversations](importing-conversations.md) | ChatGPT, markdown, Claude exports |
| [CI Integration](ci-integration.md) | scaffold ci setup, workflows, task runner |
| [Platform Integration](platform-integration.md) | Cursor, Claude Code, Windsurf, Cline, Continue, aider, Codex, MCP setup |

## Internal (dev_docs/, not shipped to PyPI)

| Document | Description |
|----------|-------------|
| [Eval Findings and Improvement Plan](../dev_docs/eval-findings-and-improvement-plan.md) | Results from the 64-scenario evaluation harness, bugs found, and fixes applied |
