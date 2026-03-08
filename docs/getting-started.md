# Getting Started with AgentScaffold

This guide walks you through installing AgentScaffold, initializing a project, and running your first plan through the full lifecycle.

## 1. Installation

Install from PyPI:

```bash
pip install agentscaffold
```

Verify installation:

```bash
scaffold version
```

## 2. Initialize a Project

Navigate to your project directory and run:

```bash
cd my-project
scaffold init
```

The interactive prompts will ask:

| Prompt | Default | Description |
|--------|---------|-------------|
| Project name | Directory name | Used in docs and config |
| Architecture layers | 3 | Number of layers in your system architecture (see below) |
| Select domains | none | Comma-separated numbers or names (e.g. `1,2` or `trading,webapp`) |
| Execution profile | interactive | `interactive` or `semi_autonomous` |
| Rigor level | standard | `minimal`, `standard`, or `strict` |

**Don't know your architecture layers?** That's normal. If you're starting from scratch, enter `3` (a sensible default for most projects: data, logic, presentation). The system architecture document it generates has blank sections you'll fill in collaboratively with your agent. See the [Greenfield Onboarding](user-guide.md#greenfield-onboarding-starting-from-scratch) section of the User Guide for a step-by-step workflow that uses your AI agent to help you discover and define your architecture.

Example session:

```
Project name [my-project]: my-project
Architecture layers [3]: 3
Select domains (comma-separated numbers, or 'none') [none]: webapp
Execution profile (interactive / semi_autonomous) [interactive]: interactive
Rigor level (minimal / standard / strict) [standard]: standard
```

For non-interactive mode (CI, scripts):

```bash
scaffold init . --non-interactive
```

## 3. Understanding the Generated Structure

After init, your project contains:

```
my-project/
  AGENTS.md              # Rules your AI agent follows
  scaffold.yaml          # Framework configuration
  .cursor/rules.md       # Cursor-specific rules
  docs/
    ai/
      templates/         # Plan templates (feature/bugfix/refactor), plus spike and study
      prompts/           # Devil's advocate, expansion, retrospective
      standards/         # Error handling, logging, testing
      state/             # workflow_state, learnings_tracker, plan_completion_log
      plans/             # Your plan files
      spikes/            # Spike findings
      contracts/         # Interface contracts
    studies/             # A/B test documentation
    runbook/             # Operational docs
  justfile               # Task runner (if generated)
  Makefile               # Task runner (if generated)
```

- **AGENTS.md**: The agent reads this file to learn the plan lifecycle, gates, and collaboration protocol.
- **scaffold.yaml**: Edit this to change rigor, gates, domains, or semi-autonomous settings.
- **docs/ai/**: Source of truth for templates, prompts, and state. The agent references these paths.
- **Plan templates included**: `docs/ai/templates/plan_template.md`,
  `docs/ai/templates/plan_template_bugfix.md`, and
  `docs/ai/templates/plan_template_refactor.md`.

## 4. Creating Your First Plan

Create a plan from the feature template:

```bash
scaffold plan create my-feature
```

This creates `docs/ai/plans/001-my-feature.md` (or the next available number). For a bugfix or refactor:

```bash
scaffold plan create fix-login-bug --type bugfix
scaffold plan create extract-module --type refactor
```

Edit the plan file to fill in sections: Overview, Dependencies, File Impact Map, Execution Steps, Tests, Validation Commands, Rollback Plan.

## 5. Reviewing a Plan

Before execution, plans pass through review gates. Use the collaboration protocol (see `docs/ai/collaboration_protocol.md`):

1. **Devil's advocate**: Run the plan through `docs/ai/prompts/plan_critique.md` to stress-test assumptions.
2. **Expansion review**: Use `docs/ai/prompts/plan_expansion.md` to identify gaps and edge cases.
3. **Domain reviews**: If you have domain packs (e.g. trading), run the domain-specific prompts (e.g. `quant_architect_review.md`).

Example prompt to your agent:

> "Let's review plan 001. Run the devil's advocate review using docs/ai/prompts/plan_critique.md and summarize findings."

The agent will apply the prompt to the plan and surface risks. Update the plan based on findings before marking it Ready.

## 6. Executing a Plan

When the plan is Ready, tell your agent to execute:

> "Execute plan 001. Follow the execution steps in order, check them off as you complete them."

The agent will:

- Read the plan and complete the Plan Review Checklist
- Verify dependencies and interface contracts
- Implement each execution step
- Run validation commands
- Update workflow_state.md and plan_completion_log.md
- Complete a retrospective

## 7. Running the Retrospective

After execution, run a retrospective using `docs/ai/prompts/retrospective.md`. The agent should document:

- What worked well
- What was harder than expected
- Discoveries not in the plan
- Actionable follow-ups

Check for missing retrospectives:

```bash
scaffold retro check
```

## 8. Using Validation

Run all enforcement checks:

```bash
scaffold validate
```

This runs:

- Plan lint (structure and cohesion)
- Integration verification
- Prohibitions (e.g. emojis)
- Secrets check
- Retrospective check (if enabled)

For semi-autonomous PRs:

```bash
scaffold validate --check-safety-boundaries
scaffold validate --check-session-summary
```

## 9. Build the Knowledge Graph

After scaffolding, build the knowledge graph to enable search, reviews, and session memory:

```bash
scaffold index
```

This indexes your codebase into a local graph database (`.scaffold/graph.db`). For semantic search, add `--embeddings`. For subsequent updates, use `--incremental` (only re-indexes changed files).

See the [Knowledge Graph section of the User Guide](user-guide.md#knowledge-graph-codebase-intelligence) for details on querying, MCP tools, and review integration.

## 10. Switch from Command-Heavy to NL + MCP

If you previously drove every step with explicit structural commands, this is the point to
switch to conversational prompting while preserving the same governance rigor.

Readiness checklist:

- [ ] MCP is configured for your platform (see [Platform Integration](platform-integration.md)).
- [ ] You ran `scaffold index` at least once.
- [ ] You regenerated rules after config/domain changes:
  - `scaffold agents generate`
  - `scaffold agents cursor` (or `scaffold agents windsurf` / `scaffold agents claude`)

First 5 prompts to replace command-heavy orchestration:

1. "Let's prepare to review plan 001 with evidence and challenge assumptions."
2. "Before implementation, check whether plan 001 is stale and dependency-complete."
3. "Compare plan 001 and plan 002 for overlap before we proceed."
4. "Where did we leave off on plan 001 and what are blockers?"
5. "Prepare retro context for plan 001 with prior findings and studies."

Keep explicit commands for verification/operations:

```bash
scaffold index --incremental
scaffold graph verify
scaffold validate
```

For a full migration guide, see
[Migrating Governance to NL + MCP](migrating-governance-to-nl-mcp.md).

## 11. Next Steps

- **Domain packs**: Add specialized reviews and standards. See [Domain Packs](domain-packs.md).
- **Semi-autonomous mode**: Enable for CLI-triggered agents. See [Semi-Autonomous Guide](semi-autonomous-guide.md).
- **Regenerate agent files**: After editing `scaffold.yaml` or adding domains:

  ```bash
  scaffold agents generate
  scaffold agents cursor
  ```

- **CI setup**: Generate GitHub Actions workflows:

  ```bash
  scaffold ci setup
  ```

- **Task runner**: Generate justfile and Makefile:

  ```bash
  scaffold taskrunner setup
  ```
