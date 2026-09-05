# AgentScaffold

**Persistent institutional memory and governance enforcement for AI coding agents.**

AgentScaffold gives your AI agent two things it lacks by default: a durable knowledge graph that remembers your codebase, plans, contracts, and review findings across every session — and a governance framework that enforces your development workflow before a single line of code is written.

The efficiency gains (fewer file reads, lower token spend) are downstream of this. When an agent carries real memory and follows real process, it spends less time rebuilding context and more time doing the work.

## The Two Problems

### Memory: Agents start from zero every session

Every time you start a new session with Cursor, Claude Code, Codex, or any AI coding agent, it starts from zero. It reads your files. It greps for imports. It traces call chains. It burns through your token budget and subscription quota just to understand what it already understood yesterday.

On a moderately complex codebase, a single "understand this module" task can cost **12 file reads + 2 grep searches** before the agent even starts working. A full plan review pulls in **10+ files**. Getting oriented in a new codebase means reading **38+ files**.

AgentScaffold indexes your codebase once and serves it via MCP tools in a single call. The graph persists across sessions, grows incrementally, and includes governance artifacts — so the agent knows not just what the code does but why decisions were made and what review findings remain open.

### Governance: Agents skip process unless you enforce it

AI agents left to themselves skip reviews, ignore contracts, and build solutions that diverge from your architecture. They work fast until they work wrong.

AgentScaffold enforces a plan lifecycle with adversarial reviews before implementation, interface contracts that survive across plans, and retrospectives that feed learning back into the process. Review findings are written into the knowledge graph and surfaced in every subsequent review of the same plan — the agent cannot forget a finding because it is persisted, not held in context.

## When to Use AgentScaffold

| Situation | Benefit |
|---|---|
| Large or complex codebase (>10K LOC) | Graph retrieval replaces expensive context-building reads |
| Plans that span multiple sessions | Persistent findings, decisions, and state survive context resets |
| Domain-sensitive work (trading, ML, infra) | Domain pack reviewers enforce domain-specific standards before code is written |
| Multiple AI agents or platforms | MCP layer works uniformly across Cursor, Claude Code, Windsurf, and any MCP-compatible agent |
| Teams managing architectural integrity | Interface contracts and ADRs linked to code prevent drift detection gaps |
| Post-incident retrospectives | Review findings remain queryable; resolved findings keep their history |

### When you probably don't need it

A well-tuned `CLAUDE.md` or Cursor rules file gets a solo developer most of the way on a small, short-lived project. If you are working alone on a few thousand lines over a few days, native tooling is enough and AgentScaffold's indexing and governance overhead may not pay for itself. The value compounds with **scale** (transitive impact analysis past the point where grep breaks down), **time** (cross-session memory that accumulates instead of resetting), and **team** (a shared graph and contract lifecycle that per-developer rules files cannot provide).

## What It Does

AgentScaffold combines two capabilities:

### 1. Persistent Knowledge Graph

A DuckDB + DuckPGQ-backed graph that indexes your codebase once and serves it to agents instantly:

- **Code structure**: Functions, classes, methods, interfaces, import chains, call graphs — across Python, TypeScript, Go, Rust, Java, C, and C++
- **Governance artifacts**: Plans, contracts, learnings, and review findings linked to the code they reference
- **Community detection**: Leiden algorithm clustering identifies tightly coupled modules
- **Semantic search**: Hybrid search combining structural graph queries with vector embeddings (fused via reciprocal-rank fusion), with explicit `available`/`degraded`/`unavailable` status when embeddings or `sentence-transformers` are missing (graceful keyword fallback). Embeddings are enriched with each definition's docstring/leading comment (read from source at index time) and L2-normalized at store time, so matches reflect intent rather than identifiers alone
- **Incremental indexing**: SHA-256 content hashing means only changed files are re-processed
- **Contract drift detection**: Automatically surfaces methods declared in contracts but missing from code
- **Review finding write-back**: Findings recorded during plan reviews are persisted as graph nodes and surfaced in every future review of the same plan

The graph is exposed via **MCP tools** that any compatible agent can call, or through the CLI for direct use.

### 2. Agent Governance Framework

A structured development workflow that teaches your AI agent to follow a plan lifecycle with quality gates:

- **Plan lifecycle**: Draft → Review → Ready → In Progress → Complete
- **Adversarial reviews**: Devil's advocate, expansion analysis, domain-specific reviews — all run before a single line of code is written
- **Interface contracts**: Formal declarations of module boundaries, versioned and tracked
- **Retrospectives**: Post-execution learning that feeds back into the process
- **Session tracking**: State files that persist context across chat sessions
- **Lifecycle hooks**: Pre-edit validation and post-edit incremental re-indexing enforced at the platform level

**Think of it as a virtual sprint team.** Most AI agents work alone. AgentScaffold puts your agent on a team. Before it writes a single line of code, the plan faces a devil's advocate who asks "what if this breaks?", an expansion reviewer who asks "what did you miss?", and a domain expert — a quant architect, a UX designer, a security engineer — who pressure-tests the approach through the lens of your specific domain.

After implementation, a post-implementation review verifies what was built against what was planned. A retrospective captures what worked, what didn't, and what to do differently. Those findings flow into the learnings tracker, which feeds back into the agent's rules and templates — so the next sprint starts sharper than the last.

## Measured Efficiency Gains

These numbers are downstream of governance and memory — not the lead story, but real.

**From the eval harness (125 scenarios, revalidated 2026-09-05):**

| Task | Without AgentScaffold | With AgentScaffold | Savings |
|------|----------------------|-------------------|---------|
| Understand a module and its dependents | 12 reads + 2 greps | 1 tool call | 84% fewer tokens, 93% fewer calls |
| Codebase orientation | 38 file reads | 2 tool calls | 64% fewer tokens, 95% fewer calls |
| Impact analysis (blast radius) | 12 file reads | 1 tool call | 43% fewer tokens, 92% fewer calls |
| Find all code matching a concept | 8 file reads | 1 tool call | 29% fewer tokens, 88% fewer calls |
| Full plan review with evidence | 10 file reads | 1 tool call | 5% fewer tokens, 90% fewer calls |
| Review with prior finding history | 3 re-reviews | 1 tool call | 58% fewer tokens, 67% fewer calls |
| Empty search diagnosis (call compression) | search + why_empty + grep | 1 fused search | 19% fewer tokens, 67% fewer calls |

**Capability aggregate (raw): ~84% average call reduction, ~43% average token reduction.**

Full plan review remains the densest composite: one call replaces ten file reads and stays near token-neutral (5%) because summary trimming prioritizes high-severity signals. The win there is still calls and completeness. Empty-search call compression collapses a three-hop diagnosis into one response with inline `why_empty` + `grep_fallback`. Review with prior finding history returns a known issue instead of paying ~2,000 tokens to re-derive it each session.

We report three views so the headline is not the optimistic one:

| View | Token Reduction | Call Reduction |
|------|-----------------|----------------|
| Raw capability (tool routes correctly) | ~43% | ~84% |
| Behavioral (replay-adjusted) | ~35% | ~68% |
| Quality-adjusted behavioral | ~31% | ~61% |

Behavioral and quality-adjusted values come from replay traces (observed tool-call sequences + quality parity checks), not phrase-level intent matching. They are lower because agents do not always route to the tool — the graph does not help if the agent reads files directly instead. Intent-map adoption for exact/paraphrase/negative suites is 100% in the latest harness run; replay-observed tool-first adherence remains the stricter behavioral proxy.

> **Note**: Numbers above are from the most recent evaluation run (`eval/reports/latest.md`). From the package root, reproduce with `cd eval && uv run --project .. pytest -q` (`uv run` is the runner the suite is written for; a PATH `pytest` can pick up the wrong environment).

## Quick Start

```bash
pip install agentscaffold
cd my-project
scaffold init                 # Scaffolds docs + platform rules (manual once, routing in the managed block)
scaffold index                # Build the knowledge graph
scaffold mcp install          # Register the MCP server with your agent client
scaffold doctor               # Confirm the setup resolves the way you expect
```

`scaffold mcp install` writes the server entry into your client's `mcp.json`
(`~/.cursor/mcp.json` by default; `--config` for another client). You install
**one** entry, not one per project — see [Multi-Project
Workspaces](#multi-project-workspaces) for why that changed in 0.10.0.

Bare `scaffold mcp` runs the server in the foreground. You rarely invoke it
yourself; the client launches it from the entry `install` wrote. It is useful for
watching the server's output while debugging.

The `init` command scaffolds your project and, on a fresh init, generates the
complete rule set for every supported platform:

- `docs/ai/` — templates, prompts, standards, state files
- `scaffold.yaml` — your project's framework configuration
- `AGENTS.md` — project-owned governance manual (scaffolded once) plus a managed routing block
- `.cursor/rules.md` + `.cursor/rules/agentscaffold.mdc` — Cursor process rules and the MCP routing / graph trust-discipline policy
- `.cursor/mcp.json` — a per-project Cursor MCP registration. Still written for
  single-repo use, but superseded by `scaffold mcp install` for workspaces: one
  project-aware server replaces one entry per project. Existing per-project entries
  keep working behind a one-time deprecation notice
- `CLAUDE.md` and `.claude/agents/` — Claude Code rules and one subagent file per configured reviewer
- `.windsurfrules` — Windsurf rules
- Lifecycle hooks for each enabled platform
- `.gitignore` — a managed block ignoring AgentScaffold runtime artifacts (`.scaffold/`, `.venv-scaffold/`, `*.duckdb`) so the graph DB, model cache, logs, and locks never get committed

Re-running `scaffold init` is idempotent and never overwrites hand-edited rules.
Run `scaffold agents generate-all` to refresh **routing** (the managed block in
`AGENTS.md`, plus `CLAUDE.md`, `.windsurfrules`, and `.cursor/rules/agentscaffold.mdc`)
after you edit `scaffold.yaml`. It does not rewrite the governance manual and it
does not inject graph stats into `AGENTS.md`. To pull later template updates into
the manual, use `scaffold agents diff-manual`. If `AGENTS.md` already has the
same headings twice, run `scaffold agents repair` (dry run; `--apply` writes).

`.cursor/mcp.json` is written only for a repo that no shared server covers, which
is what makes a lone repo work with no further setup. Once the root is registered
or `scaffold mcp install` has run, one project-aware server serves the project and
the per-project file is skipped — regenerating rules will not undo the single-entry
setup. If you have an older per-project file left over, `scaffold mcp install` and
`scaffold doctor` both point it out; remove it by hand, since these files are
frequently committed.

**File safety.** AgentScaffold never silently clobbers agent or skill files you
already own. Project-owned docs (`AGENTS.md`, `CLAUDE.md`, `.windsurfrules`,
`.cursor/rules.md`) receive generated guidance inside a delimited managed block —
existing files are appended to (or the block is refreshed in place), never
overwritten, and anything outside the block is always preserved. A marker-less
file that already looks generated refuses unless you pass `--allow-append`.
`--force` replaces the entire file (a `.bak` is kept) and is not that escape.
To take ownership of a file, add `<!-- agentscaffold: managed=false -->` near
the top; deleting the markers is not ownership. User-authored skills (`SKILL.md`
without a `managed_by: agentscaffold` marker) are left untouched. Only
machine-owned policy files (`.cursor/rules/agentscaffold.mdc`, reviewer rules,
enforcement hooks) are regenerated each run. The project `.gitignore` is treated
as co-owned: AgentScaffold only ever creates it, refreshes its own managed
block, or appends the block — it never rewrites your `.gitignore` whole, even
under `--force`. See
[File Safety](docs/platform-integration.md#file-safety-what-agentscaffold-will-and-will-not-overwrite).

The `index` command builds the knowledge graph — a DuckDB + DuckPGQ database — enabling search, reviews, impact analysis, and session memory.

**Where the graph lives.** An unregistered repo keeps it in-tree at
`.scaffold/graph.duckdb`. A workspace registered with `scaffold project register`
resolves it under your platform state directory, keyed by workspace id, so
generated state stops accumulating inside the source tree.

Upgrading never moves it. An existing in-tree database always wins over an empty
state directory, because flipping a default is not a migration: silently
re-resolving would index from scratch and orphan the populated database. Move it
deliberately with `scaffold workspace migrate-state` (dry run by default; it
copies, verifies, then removes, and refuses to start while another process holds
the source). `scaffold doctor` reports where the graph actually resolves.

### Async freshness (low-latency graph updates for MCP)

AgentScaffold supports async freshness mode for MCP usage. Instead of blocking a tool call to re-index, the request path runs a cheap freshness check and returns immediately. If the graph looks stale, a background incremental refresh is scheduled (with debounce and single-flight locking) while the agent continues working.

Why this design matters:

- Keeps MCP interactions in milliseconds/seconds instead of minutes on large repos
- Avoids duplicate refresh jobs under parallel tool usage
- Surfaces explicit freshness metadata (`fresh`, `stale`, `unknown`, `refreshing`) so agents can reason about confidence
- Preserves strict governance by allowing gate transitions to defer when freshness is required and not yet restored

Configure in `scaffold.yaml`:

```yaml
freshness:
  async_enabled: true
  debounce_seconds: 120
  gate_strict: false
  background_queue_enabled: true
```

**Single-writer model (teams):** the graph is one DuckDB file and only one process may write it at a time. The async refresh serializes refresh *scheduling* per workspace, but it does not make concurrent writers safe. Each developer should keep their own local graph rather than sharing a single file over a network mount; running `scaffold index` while the MCP server holds the graph open raises a clear `GraphLockError` (after a short retry) and MCP tool calls return `{"graph_locked": true}` instead of crashing.

**Collaboration ergonomics (opt-in):** for teams where several people (or agents) work the same repo, two features reduce git contention on shared governance files. With `collab.sharded: true`, the high-churn `workflow_state.md` / `backlog.md` can be stored as per-entry fragments so concurrent writers touch different files (`scaffold state split` shards an existing file reversibly; `scaffold state render` reassembles the canonical file deterministically). Advisory plan claims (`scaffold plan claim <n> --owner <who>` / `scaffold plan release`) record git-backed, visible ownership of an in-flight plan — visibility, not an enforced lock. Both default off, so existing repos are unaffected.

### Multi-Project Workspaces

Several projects can share **one** knowledge-graph cache — useful for a monorepo of services or a set of related repos you want an agent to reason across. A `workspace.yaml` at the workspace root lists the member projects:

```yaml
projects:
  - name: api
    path: services/api
  - name: web
    path: apps/web
```

```bash
scaffold workspace onboard services/api        # register a project (creates workspace.yaml)
scaffold workspace onboard apps/web             # second project -> workspace is now multi-project
scaffold workspace list                         # show projects + mode
```

#### One server, not one per project

Before 0.10.0 an MCP server was bound to a single directory, so a monorepo needed
one server entry per project — each with its own process, its own graph handle, and
its own copy of the generated guidance. That does not scale, and it puts the agent
in the position of choosing which server to ask.

A single **project-aware** server now serves the whole workspace. Each call resolves
its own project from the path being worked on, so the agent never picks a server and
never has to be told where it is.

```bash
scaffold project register ~/dev/trading-stack   # record a root the server may resolve
scaffold project list                           # what is registered
scaffold mcp install                            # install the one server entry
scaffold mcp install --migrate                  # and retire legacy per-project entries
scaffold doctor                                 # verify registrations, entries, and skew
scaffold gc                                     # reclaim state from workspaces that are gone
```

`install` writes to `~/.cursor/mcp.json` by default (`--config` for another
client) and supports `--dry-run`. It never modifies an unrelated server entry: the
resulting document is verified against the original before anything is written,
and a config it cannot parse is refused rather than guessed at. Legacy
per-project entries keep working and are only removed by an explicit `--migrate`,
which backs the file up first.

One server process can read every registered project. If you want a tighter
boundary, `scaffold mcp --restrict-to <names>` binds the server to an explicit
allowlist and refuses anything resolving outside it — add it to the entry's `args`
in `mcp.json`.

Registering a root and installing the server are **separate commands on purpose**.
Widening what a server is allowed to read should never be a side effect of
onboarding a project.

When a call cannot be attributed to a project, the server refuses rather than
guessing and answering from a default — a wrong project's answer is worse than no
answer, because nothing about it looks wrong. With several workspaces registered,
a call that omits both `working_path` and `project` is refused: the launch
directory is a container, not a project. `scaffold_projects` is the recovery
path: it reports what is registered, which project the call resolved to, and why.
Do not pin `--workspace` in a shared `mcp.json` on a multi-workspace machine.

Once a workspace has more than one project, every node is namespaced by project (`{project}::{raw_id}`) and stamped with a `project` column. **Reads default to the current project**, so an agent working in `api` never misreads `web`'s plans, findings, or learnings (even when both have a `plan 12` or a `src/utils.py`). Widen explicitly when you want to:

```bash
scaffold graph search "auth flow"                  # current project only (default)
scaffold graph search "auth flow" --project web    # target a sibling
scaffold graph search "auth flow" --all-projects   # federate (results carry project provenance)
scaffold graph duplicates --table Function         # cross-project near-duplicates (reuse candidates)
```

#### How Agents Resolve The Current Project

In normal agent work you do **not** need to mention the workspace. AgentScaffold
resolves the active project from the current working directory.

Example:

```text
~/dev/trading-stack/
  workspace.yaml
  market-data-service/
    scaffold.yaml
  strategy-engine/
    scaffold.yaml
```

If Cursor, Claude Code, or another agent is working from
`~/dev/trading-stack/market-data-service`, then plain graph/governance reads
default to the `market-data-service` project:

```bash
cd ~/dev/trading-stack/market-data-service
scaffold graph search "symbol normalization"     # market-data-service only
```

If the agent is working from `~/dev/trading-stack/strategy-engine`, the same
command defaults to `strategy-engine`:

```bash
cd ~/dev/trading-stack/strategy-engine
scaffold graph search "symbol normalization"     # strategy-engine only
```

Only widen scope when the task is explicitly cross-project:

```bash
scaffold graph search "symbol normalization" --project market-data-service
scaffold graph search "symbol normalization" --all-projects
```

The generated agent rules teach this behavior: default to the current project,
treat plan numbers and file paths as project-scoped, and preserve project
provenance when using federated results.

A lone repo with no `workspace.yaml` is completely unaffected: it behaves as a single synthesized project, nothing is ID-prefixed, and every scope predicate is a no-op. An existing single-project cache can be re-keyed into a named project in place with `scaffold workspace onboard <dir> --migrate-existing <name>` (an atomic, rollback-safe rebuild verified by an integrity check); otherwise just re-index.

**Trust model:** a workspace is a single trust domain (all projects belong to the same user/org). Project scoping is a *relevance and correctness* boundary that prevents cross-project misorientation — not a security isolation boundary. Writes are project-scoped at the storage choke point with a check-before-insert collision guard, so re-indexing one project can never corrupt or wipe a sibling.

### Install with language support

```bash
pip install agentscaffold[graph]              # Python, JS, TS
pip install agentscaffold[graph-all-languages] # + Go, Rust, Java, C, C++
pip install "agentscaffold[benchmark]"        # Optional live benchmark runner deps
pip install agentscaffold[all]                # Everything
```

### Benchmarking

AgentScaffold includes an opt-in `scaffold benchmark` command group for comparing
a baseline plain-tools agent arm against an AgentScaffold-equipped arm. The
initial implementation is preflight/dry-run only:

```bash
scaffold benchmark models
scaffold benchmark doctor
scaffold benchmark run --dry-run --model claude-haiku --task-slice 0:1
scaffold benchmark compare path/to/summary.json
scaffold benchmark report path/to/results-dir
```

Live benchmark runs can spend model-provider credits and will require
`agentscaffold[benchmark]`, Docker, an API key, `--max-cost-usd`, and
`--confirm-live`. See [Benchmarking](docs/benchmarking.md).

## How Agents Use It

### MCP Tools (for AI agents)

When you run `scaffold mcp`, these tools become available to your agent.

#### Interaction Modes

AgentScaffold supports two complementary ways of working:

- **Natural-language + MCP (interactive)**: describe intent conversationally and let the agent route to the right governance/graph workflow.
- **Structural CLI commands (explicit/automation)**: use direct `scaffold` commands for deterministic setup, verification, CI, and fallback.

Teams usually get best UX with NL+MCP for day-to-day flow, then use explicit CLI commands for verification (`scaffold validate`, `scaffold graph verify`, `scaffold index --incremental`).

You don't need to memorize tool names. AgentScaffold teaches the agent how to interpret user intent in natural conversation, map that intent to the right MCP workflow, and only fall back to direct reads/search when tool output is insufficient.

There are **31 tools**. The list below is complete; `scaffold doctor --tools` calls
every one of them against your installation and reports which respond.

**Governed lifecycle** — the two-phase chain that wraps implementation:

| Tool | What It Does |
|------|-------------|
| `scaffold_begin_plan` | Phase 1: orientation plus the full pre-implementation review, records findings, stamps the plan as reviewed, returns a proceed prompt |
| `scaffold_complete_plan` | Phase 2: retrospective, records retro insights and any backlog items, returns a completion checklist |

These are the framework's spine. Phase 1 runs before code is written and Phase 2
after, and the boundary is deliberate: the tools own graph state, the agent owns
file state. When strict gating is enabled, a plan that has not been through Phase 1
cannot enter implementation.

**Composite tools** — single calls that replace entire multi-step workflows:

| Tool | What It Replaces |
|------|-----------------|
| `scaffold_prepare_review` | Reading plan, contracts, learnings, and source to prepare a full adversarial review |
| `scaffold_prepare_implementation` | Tracing dependencies, checking contracts, and verifying readiness before coding |
| `scaffold_orient` | Reading 38+ files to understand project state, blockers, and next steps |
| `scaffold_decision_context` | Tracing the full decision chain (ADRs, spikes, studies) behind a plan |
| `scaffold_staleness_check` | Manually comparing plan dates, file changes, and overlapping completed work |
| `scaffold_compare_plans` | Reading two plans and their file impacts to identify conflicts |
| `scaffold_prepare_rewrite` | Staleness check plus the dependency landscape and contracts added since the plan was written |
| `scaffold_prepare_retro` | Gathering verification results, study outcomes, and retro insights |
| `scaffold_find_studies` | Searching study files by topic, tags, or outcome |
| `scaffold_find_adrs` | Searching architecture decision records by topic or status |
| `scaffold_prior_experiments` | Finding experiments linked to a plan by reference, tag overlap, or file overlap |
| `scaffold_recall_governance` | Semantic recall across plans, findings, learnings, ADRs, studies, spikes, and backlog |
| `scaffold_diff_plan_vs_code` | Checking a plan against disk and graph mid-implementation: next unchecked step, missing files, symbol spot-checks |

**Write tools** — close the review loop by persisting into the graph:

| Tool | Purpose | Latency |
|------|---------|---------|
| `scaffold_record_finding` | Persist a review finding (severity, category, affected files) | < 200 ms |
| `scaffold_record_findings_batch` | Persist several findings in one transaction — the batch lands whole or not at all | < 200 ms |
| `scaffold_resolve_finding` | Mark a finding resolved with resolution text | < 200 ms |
| `scaffold_record_backlog_item` | Persist backlog items, singly or in batch, so they surface in orientation and reviews | < 200 ms |
| `scaffold_resolve_backlog_item` | Archive a completed backlog item, retained for retrospective queries | < 200 ms |

Nothing is deleted. Resolved findings and archived items keep their history and drop
out of active review output rather than disappearing. The backlog write is
*additive* to `backlog.md`: the markdown stays the human-readable source, and the
graph copy is what makes items queryable.

Findings recorded via `scaffold_record_finding` appear in all future `scaffold_prepare_review` calls for the same plan, ordered by severity. Resolved findings are retained for retrospectives but filtered from active review output.

**Finding lifecycle, before and after:**

*Without AgentScaffold* — A reviewer flags that `libs/data/router.py` has 8 transitive importers and changing its signature is risky. The session ends. Three sessions later, a different agent reviews the same plan, re-reads the same files, re-traces the same imports, and re-derives the same risk from scratch — roughly 2,000 tokens of reasoning per session, repeated every time, because the conclusion lived only in a chat transcript no one reloads.

*With AgentScaffold* — The first reviewer calls `scaffold_record_finding` (severity `high`, category `dependency`, file `libs/data/router.py`). It is persisted as a `ReviewFinding` node linked to the file. Every later `scaffold_prepare_review` for that plan surfaces it in one call, so the reviewer starts from "this risk is known and open" instead of rediscovering it. When the risk is mitigated, `scaffold_resolve_finding` records the resolution and the finding drops out of active review but stays in the graph for the retrospective. In the eval harness this cut the review's token cost by 58% versus re-deriving — but the real point is that a known issue is never silently forgotten between sessions.

**Granular tools** — building blocks for custom queries:

| Tool | What It Replaces |
|------|-----------------|
| `scaffold_context` | Reading 12+ files to understand a symbol, its callers, and its layer |
| `scaffold_impact` | Manually tracing imports and grep-searching for consumers |
| `scaffold_search` | Multiple grep passes to find code by concept |
| `scaffold_review_context` | Reading plan files, contracts, and source to prepare a single review type |
| `scaffold_stats` | Scanning the entire directory tree to understand codebase shape |
| `scaffold_validate` | Running separate staleness checks and contract verification |
| `scaffold_query` | Writing ad-hoc queries against the knowledge graph |
| `scaffold_projects` | Asking which projects are registered and which one a call resolved to |

**Routing and fallback** — for when a query comes back empty:

| Tool | What It Does |
|------|-------------|
| `scaffold_why_empty` | Explains why a search, impact, or context call returned nothing, and what to do instead |
| `scaffold_grep_graph` | Text search across the workspace, for the file types structural queries cannot see |
| `scaffold_next_action` | Routes to the next tool when intent is ambiguous |

You will rarely need these three directly, because the answers they give are
already attached to the responses that would send you looking for them: an empty
`scaffold_search` carries its own `why_empty` and `grep_fallback`, and
`scaffold_orient` carries its own recommended next actions. They exist as
standalone tools for the cases where those inline fields are absent.

That inlining matters more than it sounds. **An empty result means *unconfirmed*,
not *unused*.** Structural edges exist only for parsed languages, and static
analysis cannot see dynamic dispatch, reflection, or config-driven wiring — so
"0 callers" from the graph is a reason to grep, not a licence to delete. Shipping
the explanation and the fallback command inside the empty response is what stops
that misreading from costing a round trip, or worse, going unnoticed.

### CLI (for humans)

```bash
scaffold plan create my-feature            # Create a plan from template
scaffold plan lint --plan 001              # Validate plan structure
scaffold plan status                       # Dashboard of all plans
scaffold validate                          # Run all enforcement checks
scaffold retro                             # Find plans missing retrospectives
scaffold agents generate-all   # Refresh routing / platform rule files
scaffold agents repair         # Dry-run de-duplicate AGENTS.md headings
scaffold agents diff-manual    # Offer template updates to the project-owned manual
scaffold agents cursor # Cursor rules only
scaffold agents claude # Claude Code agent files only
scaffold agents skills                     # Generate SKILL.md files from your standards
scaffold plugins package trading           # Package a domain pack as a wheel
scaffold import chat.json --format chatgpt # Import conversation
scaffold ci                                # Generate CI workflows
scaffold metrics                           # Plan analytics
scaffold graph search "data routing"       # Hybrid search (keyword + semantic)
scaffold graph search "data routing" --all-projects  # Federate across a multi-project workspace
scaffold graph duplicates                  # Cross-project near-duplicate definitions
scaffold workspace onboard services/api    # Register a project into the workspace
scaffold workspace list                    # List workspace projects + mode
scaffold graph verify                      # Graph accuracy check
scaffold review brief 42                   # Pre-review brief for plan 42
scaffold review challenges 42              # Adversarial challenges with evidence
scaffold session start --plan 42           # Start a tracked coding session
```

**Setup and health:**

```bash
scaffold project register ~/dev/my-workspace  # Record a root the MCP server may resolve
scaffold project list                         # Show registered roots
scaffold mcp install                          # Install the MCP server entry into your client
scaffold doctor                               # Diagnose the installation (read-only)
scaffold doctor --strict                      # Same, but exits non-zero — the CI gate
scaffold doctor --tools                       # Call every MCP tool and report which respond
scaffold gc                                   # Reclaim state from workspaces that no longer exist
scaffold workspace migrate-state              # Move graph state out of the source tree
scaffold graph prune --malformed-findings     # Remove findings left by the pre-0.10.0 extraction bug
```

`doctor` only reads. It never repairs, creates, or migrates, so it is safe to run
on a setup you already believe is broken — which is the only time anyone runs it.
It exits 0 whatever it finds, so it is safe in a shell profile or a git hook;
`--strict` is the gate to put in CI. `gc` and `prune` are dry-run by default and
need `--apply` to remove anything.

`--tools` answers a different question from the rest: not "is this configured
correctly" but "does each tool actually respond". Write tools are skipped unless
you pass `--include-writes`, which runs them against a disposable scratch project
so your real graph is never touched. A graph held by another process reports as
`busy` rather than as a failure — an index running in the next terminal is routine,
and a diagnostic that cries wolf during one stops being read.

### Skills

`scaffold agents skills` compiles your standards into `SKILL.md` files under
`.claude/skills/` and `.cursor/skills/`, so agents that support progressive
disclosure can load a standard on demand instead of carrying all of them in
context. Each file gets frontmatter with a one-line description and a short
catalog entry, and the full standard sits below it — the agent reads the summary
and pulls the body only when the task calls for it.

The set is **derived, not fixed**: one skill per standards file. Adding a domain
pack adds its standards, and therefore its skills, which is why the count grows
with your configuration rather than being a number this README could state.
User-authored `SKILL.md` files (those without a `managed_by: agentscaffold`
frontmatter marker) are never overwritten. `--if-standards-changed` regenerates
only when a standard is newer than its skill, which is what you want in a hook.

## Execution Profiles

**Interactive** (default): Human + AI agent in an IDE conversation. The agent follows AGENTS.md, asks questions when uncertain.

**Semi-Autonomous** (opt-in): Agent invoked from CLI/CI without a human present. Adds session tracking, safety boundaries, notification hooks, structured PR output, and cautious execution rules.

Both profiles coexist in the same AGENTS.md. The agent self-selects based on invocation context.

## Rigor Levels

- **Minimal**: Lightweight gates for prototypes and small projects
- **Standard**: Full plan lifecycle with reviews, contracts, and retrospectives
- **Strict**: All gates enforced, all plans require approval

## Domain Packs

The governance framework is domain-aware. Domain packs teach the adversarial reviewers to think like specialists in your field — a trading pack adds a quant architect who challenges risk assumptions and position sizing logic, a webapp pack adds a UX reviewer who flags accessibility gaps and performance regressions. Each pack includes tailored review prompts, implementation standards, and approval gates specific to the domain:

| Pack | Focus |
|------|-------|
| trading | Quantitative finance, RL, traceability |
| webapp | UX/UI, accessibility, performance budgets |
| mlops | Model lifecycle, experiment tracking, drift detection |
| data-engineering | Pipeline quality, schema evolution, SLAs |
| api-services | API design, backward compatibility, contract testing |
| infrastructure | IaC, deployment safety, cost analysis |
| mobile | Platform guidelines, offline-first, app store compliance |
| game-dev | Game loops, ECS, frame budgets |
| embedded | Memory constraints, real-time deadlines, OTA safety |
| research | Reproducibility, statistical rigor, experiment protocol |

This keeps governance strict where risk is high and lightweight where speed matters, without rewriting the core framework.

```bash
scaffold domains add trading
scaffold domains add webapp
```

## Documentation

Full documentation is in [docs/](https://github.com/drobbster/agentscaffold/tree/staging/docs):

- [Getting Started](https://github.com/drobbster/agentscaffold/blob/staging/docs/getting-started.md) — installation, init, first plan
- [User Guide](https://github.com/drobbster/agentscaffold/blob/staging/docs/user-guide.md) — session workflow, knowledge graph, review patterns
- [CLI Reference](https://github.com/drobbster/agentscaffold/blob/staging/docs/cli-reference.md) — every command, flag, and exit code
- [Platform Integration](https://github.com/drobbster/agentscaffold/blob/staging/docs/platform-integration.md) — Cursor, Claude Code, Windsurf, Cline, aider, Codex, MCP setup
- [Multi-Project Workspaces](https://github.com/drobbster/agentscaffold/blob/staging/docs/multi-project.md) — monorepos, project scoping, the shared graph
- [Configuration Reference](https://github.com/drobbster/agentscaffold/blob/staging/docs/configuration.md) — full scaffold.yaml reference
- [Domain Packs](https://github.com/drobbster/agentscaffold/blob/staging/docs/domain-packs.md) — available packs and installation
- [Creating Domain Packs](https://github.com/drobbster/agentscaffold/blob/staging/docs/creating-domain-packs.md) — build a pack for your own domain
- [Importing Conversations](https://github.com/drobbster/agentscaffold/blob/staging/docs/importing-conversations.md) — bring existing chat history into project docs
- [Semi-Autonomous Guide](https://github.com/drobbster/agentscaffold/blob/staging/docs/semi-autonomous-guide.md) — CLI/CI agent mode
- [CI Integration](https://github.com/drobbster/agentscaffold/blob/staging/docs/ci-integration.md) — GitHub Actions workflows

For maintainers: [Releasing](https://github.com/drobbster/agentscaffold/blob/staging/RELEASING.md) — branch flow, version bump, tag, publish.

## License

MIT
