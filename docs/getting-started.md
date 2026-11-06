# Getting Started with AgentScaffold

This guide walks you through installing AgentScaffold, upgrading an existing install, initializing a project, and running your first plan through the full lifecycle.

## 1. Installation

Install from PyPI. The base package and optional extras cover different capabilities:

| Install command | What you get |
|----------------|-------------|
| `pip install agentscaffold` | Governance framework only: plan lifecycle, reviews, templates, `scaffold init/validate/plan/retro` CLI. No graph, no MCP. |
| `pip install "agentscaffold[graph]"` | + Knowledge graph indexing (DuckDB/DuckPGQ) with Python, JS, TS parsers. Enables `scaffold index`, `scaffold graph`, `scaffold review`. |
| `pip install "agentscaffold[graph-all-languages]"` | + Go, Rust, Java, C, C++ tree-sitter parsers on top of `[graph]`. |
| `pip install "agentscaffold[search]"` | + Semantic search via sentence-transformers. Required for `--mode semantic` and `--mode hybrid`. |
| `pip install "agentscaffold[mcp]"` | + MCP server (`scaffold mcp`). Required for IDE tool integration (Cursor, Claude Code, etc.). |
| `pip install "agentscaffold[all]"` | Everything above. Recommended for full interactive sessions with an AI agent. |

Most users want `agentscaffold[all]` or at minimum `agentscaffold[graph,mcp]` for MCP tool
support. The bare install is useful for CI pipelines that only need `scaffold validate`.

```bash
pip install "agentscaffold[all]"
```

If your project has dependency conflicts with agentscaffold's packages (duckdb,
sentence-transformers, graspologic), install it into a dedicated virtual environment
instead. See [Isolated Install: Two Venvs](platform-integration.md#isolated-install-two-venvs)
in the Platform Integration guide.

Verify installation:

```bash
scaffold version
```

## Upgrading

For a project that already has AgentScaffold. A new install continues at
[Initialize a Project](#2-initialize-a-project) and skips this section.

Anyone already running AgentScaffold, on any older version, upgrades the
install that `scaffold` comes from and then regenerates hooks. A uv tool
that was installed as `agentscaffold==0.12.0` (or any other exact pin) does
not move when you run `uv tool upgrade`. This does, and it removes the pin:

```bash
uv tool install -U "agentscaffold[all]"
```

A copy installed with pip, including a project virtualenv, upgrades in that
environment instead:

```bash
python -m pip install -U "agentscaffold[all]"
```

Once that copy includes this command, `scaffold upgrade` does the same thing
and regenerates hooks in every registered project. Restart the MCP server
in the editor afterwards.

`scaffold doctor` reports when the `scaffold` on PATH is a different version
from the one you ran, and when a project still has the old shell hook.

Then, in each project, regenerate hooks before any user-scope install, and
rebuild the graph. Use the `scaffold` you just upgraded:

```bash
scaffold agents hooks
scaffold index
```

Restart the MCP server in the editor after the index. The first index after a
schema change rebuilds the graph and keeps findings, sessions, backlog items,
and review stamps.

These are on after that, with no config change:

- The server tells the agent to start a session, orient, and route by intent,
  and it returns the governance manual sections for that step.
- Sessions expire after 12 idle hours. Orient flags a stale workflow diary and
  a long-running session.
- Reviews and impact include earlier findings, learnings, and ADRs about the
  same files. `scaffold review precedent <path>` shows the same list.
- A project inside a monorepo gets import edges for imports written from the
  repository root. Edges recorded before the rebuild show as `unrecorded`
  until that index, which this sequence already ran.
- Pre-edit hooks refuse edits to paths listed in
  `semi_autonomous.safety.read_only_paths`.

Turn the rest on only where you want them.

**The project is not the folder the editor opened**, or you cannot commit
files into the repo. Register it, then install guidance and hooks from your
home directory. The `scaffold agents hooks` step above comes first.

```bash
scaffold project register /path/to/project
scaffold agents install --scope user --dry-run
scaffold agents install --scope user
```

**Files that belong to the project but live outside its folder.** Add globs
relative to the git root, then index again:

```yaml
graph:
  extra_paths:
    - airflow/dags/team_x/**/*.py
```

```bash
scaffold index
```

Matching files are indexed as `@repo/<path>`. See
[Configuration](configuration.md#files-outside-the-project-folder-extra_paths).

**System inventory** stays off until `scaffold.yaml` enables it. A fresh
`scaffold init` writes the block. An existing project adds it, then generates
the file:

```yaml
inventory:
  enabled: true
  enforcement: warn
```

```bash
scaffold inventory init --dry-run
scaffold inventory init
```

Warn mode does not fail checks. The data-engineering, mlops, and trading
domain packs add the Prefect collector when the block lists no collectors. If
compose files are not in the default locations, set that collector's
`sources`. See [System inventory](cli-reference.md#system-inventory).

An `AGENTS.md` that still has routing sections from before managed markers:

```bash
scaffold agents repair --prefer-managed
scaffold agents repair --prefer-managed --apply
```

`--apply` saves `AGENTS.md.bak` first.

What a particular release requires is in [CHANGELOG.md](../CHANGELOG.md). This
section is the procedure for the current release.

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
  AGENTS.md              # Governance manual (yours) + managed routing block
  CLAUDE.md              # Claude Code rules
  .windsurfrules         # Windsurf rules
  scaffold.yaml          # Framework configuration
  .cursor/
    rules.md             # Cursor process rules
    rules/agentscaffold.mdc # MCP routing + graph trust-discipline policy
    mcp.json             # Cursor MCP server registration
  .claude/agents/        # One subagent file per configured reviewer
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

- **AGENTS.md**: The agent reads the project-owned governance manual (plan
  lifecycle, gates, collaboration protocol) and the managed routing block (MCP
  tool selection, Session Working Rhythm). `init` writes the manual once.
  `scaffold agents generate-all` refreshes routing only. Use
  `scaffold agents repair` if headings are duplicated, and
  `scaffold agents diff-manual` to pull later template updates.
- **Platform rule files** (`CLAUDE.md`, `.windsurfrules`, `.cursor/rules/`, `.claude/agents/`): generated automatically on a fresh init. Regenerate the routing files after editing `scaffold.yaml` with `scaffold agents generate-all`.
- **.gitignore**: a managed block is added ignoring AgentScaffold runtime artifacts (`.scaffold/` graph DB and model cache, `.venv-scaffold/`, `*.duckdb`) so they never get committed. An existing `.gitignore` is appended to, never overwritten.
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

This indexes your codebase into a local DuckDB + DuckPGQ graph database (`.scaffold/graph.duckdb`). For subsequent updates, use `--incremental` (only re-indexes changed files).

For semantic and hybrid search, first install the `[search]` extra, then pass `--embeddings`:

```bash
pip install "agentscaffold[search]"
scaffold index --embeddings
```

See the [Knowledge Graph section of the User Guide](user-guide.md#knowledge-graph-codebase-intelligence) for details on querying, MCP tools, and review integration.

### Optional: Enable Async Freshness for MCP Sessions

If your repository is large and incremental indexing is slow, enable async freshness so MCP
tool calls stay fast while graph refresh happens in the background.

In `scaffold.yaml`:

```yaml
freshness:
  async_enabled: true
  debounce_seconds: 120
  gate_strict: false
  background_queue_enabled: true
```

Behavior:

- Request path runs a cheap freshness check and returns immediately.
- Eligible composite workflows schedule background `index --incremental` refreshes.
- Tool metadata includes freshness state (`fresh`, `stale`, `unknown`, `refreshing`).
- With `gate_strict: true`, lifecycle-gate transitions can defer until freshness is restored.

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

For a full migration guide, see the "Migration Guide for Governance-First Users"
section in the [User Guide](user-guide.md).

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

---

## Troubleshooting

### `scaffold index` fails with "No language" warnings

Warnings like `No language_c() in tree_sitter_c` or `No language_cpp() in tree_sitter_cpp` were a bug in agentscaffold 0.3.0 (wrong grammar function name lookup for C and C++) and are fixed in 0.3.1+. Upgrade to resolve them:

```bash
pip install --upgrade "agentscaffold[graph]"
```

If a different language you care about is still not parsed, ensure the grammar extra is installed. All eight bundled grammars (Python, JavaScript, TypeScript, Go, Rust, Java, C, C++) are included in the `[graph]` extra.

### Semantic search returns no results

Two steps are required for semantic search to work:

1. Install the `[search]` extra: `pip install "agentscaffold[search]"`
2. Re-index with embeddings: `scaffold index --embeddings`

If you run `scaffold graph search --mode semantic` without these, the search falls back to keyword-only with a warning.

### Graph is stale after large changes

Run a full re-index:

```bash
scaffold index
```

Incremental indexing (`--incremental`) only processes changed files. After moving, deleting, or renaming many files, a full re-index is more reliable.

### graph.duckdb is corrupted or locked

If you see DuckDB errors on startup, delete the graph and rebuild:

```bash
rm .scaffold/graph.duckdb
scaffold index
```

A DuckDB file lock error usually means another process (e.g. the MCP server) is still running. Stop it first.

- **Task runner**: Generate justfile and Makefile:

  ```bash
  scaffold taskrunner setup
  ```
