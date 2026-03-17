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

## What It Does

AgentScaffold combines two capabilities:

### 1. Persistent Knowledge Graph

A DuckDB + DuckPGQ-backed graph that indexes your codebase once and serves it to agents instantly:

- **Code structure**: Functions, classes, methods, interfaces, import chains, call graphs — across Python, TypeScript, Go, Rust, Java, C, and C++
- **Governance artifacts**: Plans, contracts, learnings, and review findings linked to the code they reference
- **Community detection**: Leiden algorithm clustering identifies tightly coupled modules
- **Semantic search**: Hybrid search combining structural graph queries with vector embeddings
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

**From the eval harness (115 scenarios):**

| Task | Without AgentScaffold | With AgentScaffold | Savings |
|------|----------------------|-------------------|---------|
| Understand a module and its dependents | 12 reads + 2 greps | 1 tool call | ~97% fewer tokens, ~93% fewer calls |
| Codebase orientation | 38 file reads | 2 tool calls | ~77% fewer tokens, ~95% fewer calls |
| Impact analysis (blast radius) | 12 file reads | 1 tool call | ~88% fewer tokens, ~92% fewer calls |
| Find all code matching a concept | 8 file reads | 1 tool call | ~44% fewer tokens, ~88% fewer calls |
| Full plan review with evidence | 10 file reads | 1 tool call | ~90% fewer calls (richer output) |

**Capability aggregate (raw): ~91% average call reduction. ~58% average token reduction.**

We report two views to avoid sugar-coating:

| View | Token Reduction | Call Reduction |
|------|-----------------|----------------|
| Raw capability | ~58% | ~91% |
| Behavioral (replay-adjusted) | ~44% | ~69% |
| Quality-adjusted behavioral | ~39% | ~62% |

Behavioral and quality-adjusted values come from replay traces (observed tool-call sequences + quality parity checks), not phrase-level intent matching. Adjusted values are lower because agents do not always choose tools consistently — the graph does not help if the agent reads files directly instead.

> **Note**: Exact numbers above are from the most recent evaluation run. Run `python -m pytest eval/scenarios/ -q` in `packages/agentscaffold` to reproduce against the current codebase.

## Quick Start

```bash
pip install agentscaffold
cd my-project
scaffold init
scaffold index          # Build the knowledge graph
scaffold agents generate-all  # Generate IDE/agent rule files
scaffold mcp serve      # Start MCP server for tool access
```

The `init` command scaffolds your project with:

- `docs/ai/` — templates, prompts, standards, state files
- `AGENTS.md` — rules your AI agent follows automatically
- `.cursor/rules/agentscaffold.md` — Cursor-specific rules
- `.claude/agents/` — Claude Code subagent files per reviewer
- `scaffold.yaml` — your project's framework configuration
- `justfile` + `Makefile` — task runner shortcuts
- `.github/workflows/` — CI with security scanning

The `index` command builds the knowledge graph at `.scaffold/graph.duckdb`, enabling search, reviews, impact analysis, and session memory.

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

### Install with language support

```bash
pip install agentscaffold[graph]              # Python, JS, TS
pip install agentscaffold[graph-all-languages] # + Go, Rust, Java, C, C++
pip install agentscaffold[all]                # Everything
```

## How Agents Use It

### MCP Tools (for AI agents)

When you run `scaffold mcp serve`, these tools become available to your agent.

#### Interaction Modes

AgentScaffold supports two complementary ways of working:

- **Natural-language + MCP (interactive)**: describe intent conversationally and let the agent route to the right governance/graph workflow.
- **Structural CLI commands (explicit/automation)**: use direct `scaffold` commands for deterministic setup, verification, CI, and fallback.

Teams usually get best UX with NL+MCP for day-to-day flow, then use explicit CLI commands for verification (`scaffold validate`, `scaffold graph verify`, `scaffold index --incremental`).

You don't need to memorize tool names. AgentScaffold teaches the agent how to interpret user intent in natural conversation, map that intent to the right MCP workflow, and only fall back to direct reads/search when tool output is insufficient.

**Composite tools** — single calls that replace entire multi-step workflows:

| Tool | What It Replaces |
|------|-----------------|
| `scaffold_prepare_review` | Reading plan, contracts, learnings, and source to prepare a full adversarial review |
| `scaffold_prepare_implementation` | Tracing dependencies, checking contracts, and verifying readiness before coding |
| `scaffold_orient` | Reading 38+ files to understand project state, blockers, and next steps |
| `scaffold_decision_context` | Tracing the full decision chain (ADRs, spikes, studies) behind a plan |
| `scaffold_staleness_check` | Manually comparing plan dates, file changes, and overlapping completed work |
| `scaffold_compare_plans` | Reading two plans and their file impacts to identify conflicts |
| `scaffold_prepare_retro` | Gathering verification results, study outcomes, and retro insights |
| `scaffold_find_studies` | Searching study files by topic, tags, or outcome |
| `scaffold_find_adrs` | Searching architecture decision records by topic or status |

**Write tools** — close the review loop by persisting findings into the graph:

| Tool | Purpose | Latency |
|------|---------|---------|
| `scaffold_record_finding` | Persist a review finding (severity, category, affected files) | < 200 ms |
| `scaffold_resolve_finding` | Mark a finding resolved with resolution text | < 200 ms |

Findings recorded via `scaffold_record_finding` appear in all future `scaffold_prepare_review` calls for the same plan, ordered by severity. Resolved findings are retained for retrospectives but filtered from active review output.

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

### CLI (for humans)

```bash
scaffold plan create my-feature            # Create a plan from template
scaffold plan lint --plan 001              # Validate plan structure
scaffold plan status                       # Dashboard of all plans
scaffold validate                          # Run all enforcement checks
scaffold retro check                       # Find missing retrospectives
scaffold agents generate-all   # Regenerate all platform agent files
scaffold agents cursor # Cursor rules only
scaffold agents claude # Claude Code agent files only
scaffold agents skills                     # Generate skill disclosure files
scaffold plugins package trading           # Package a domain pack as a wheel
scaffold import chat.json --format chatgpt # Import conversation
scaffold ci setup                          # Generate CI workflows
scaffold metrics                           # Plan analytics
scaffold graph search "data routing"       # Hybrid search
scaffold graph verify                      # Graph accuracy check
scaffold review brief 42                   # Pre-review brief for plan 42
scaffold review challenges 42              # Adversarial challenges with evidence
scaffold session start --plan 42           # Start a tracked coding session
```

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

Full documentation is in [docs/](docs/):

- [Getting Started](docs/getting-started.md) — installation, init, first plan
- [User Guide](docs/user-guide.md) — session workflow, knowledge graph, review patterns
- [Platform Integration](docs/platform-integration.md) — Cursor, Claude Code, Windsurf, Cline, aider, Codex, MCP setup
- [Configuration Reference](docs/configuration.md) — full scaffold.yaml reference
- [Domain Packs](docs/domain-packs.md) — available packs and installation
- [Semi-Autonomous Guide](docs/semi-autonomous-guide.md) — CLI/CI agent mode
- [CI Integration](docs/ci-integration.md) — GitHub Actions workflows

## License

MIT
