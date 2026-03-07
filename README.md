# AgentScaffold

**Stop paying for your AI agent to rediscover your codebase every session.**

AgentScaffold is a governance framework and persistent knowledge graph for AI coding agents. It replaces the expensive pattern of agents reading dozens of files, grepping for symbols, and tracing dependencies from scratch -- with a single tool call that returns exactly what the agent needs.

## The Problem

Every time you start a new session with Cursor, Claude Code, Codex, or any AI coding agent, it starts from zero. It reads your files. It greps for imports. It traces call chains. It burns through your token budget and subscription quota just to understand what it already understood yesterday.

On a moderately complex codebase, a single "understand this module" task can cost **12 file reads + 2 grep searches** before the agent even starts working. A full plan review pulls in **10+ files**. Getting oriented in a new codebase means reading **38+ files**.

This is the hidden cost of agentic development: not the coding, but the *context building*.

## The Solution

AgentScaffold builds a knowledge graph of your codebase -- code structure, dependencies, governance artifacts, session history -- and exposes it through MCP tools that your agent calls instead of reading raw files.

**Measured results from our evaluation harness (64 scenarios, 100% pass rate):**

| Task | Without AgentScaffold | With AgentScaffold | Savings |
|------|----------------------|-------------------|---------|
| Understand a module and its dependents | 12 reads + 2 greps | 1 tool call | **97% fewer tokens, 93% fewer calls** |
| Codebase orientation | 38 file reads | 2 tool calls | **77% fewer tokens, 95% fewer calls** |
| Impact analysis (blast radius) | 12 file reads | 1 tool call | **88% fewer tokens, 92% fewer calls** |
| Find all code matching a concept | 8 file reads | 1 tool call | **44% fewer tokens, 88% fewer calls** |
| Full plan review with evidence | 10 file reads | 1 tool call | **90% fewer calls** (richer output) |

**Aggregate: 91% average call reduction. 58% average token reduction. 2.9x overall compression.**

Every tool call your agent doesn't make is money you don't spend on API tokens or subscription overages. And because the governance framework catches flawed assumptions and missing edge cases *before* implementation, you also spend less time fixing bugs that should never have been written.

## What It Does

AgentScaffold combines two capabilities that don't exist together in any other tool:

### 1. Agent Governance Framework

A structured development workflow that teaches your AI agent to follow a plan lifecycle with quality gates:

- **Plan lifecycle**: Draft -> Review -> Ready -> In Progress -> Complete
- **Adversarial reviews**: Devil's advocate, expansion analysis, domain-specific reviews -- all run before a single line of code is written
- **Interface contracts**: Formal declarations of module boundaries, versioned and tracked
- **Retrospectives**: Post-execution learning that feeds back into the process
- **Session tracking**: State files that persist context across chat sessions

**Think of it as a virtual sprint team.** Most AI agents work alone -- they take instructions and start coding. AgentScaffold puts your agent on a team. Before it writes a single line of code, the plan faces a devil's advocate who asks "what if this breaks?", an expansion reviewer who asks "what did you miss?", and a domain expert -- a quant architect, a UX designer, a security engineer -- who pressure-tests the approach through the lens of your specific domain. These adversarial reviews catch flawed assumptions, missing edge cases, and architectural blind spots *before* they become bugs in production.

After implementation, the sprint continues. A post-implementation review verifies what was built against what was planned. A retrospective captures what worked, what didn't, and what to do differently. Those findings flow into the learnings tracker, which feeds back into the agent's rules and templates -- so the next sprint starts sharper than the last. This is the same continuous improvement loop that makes experienced engineering teams get better over time, applied to your AI agent.

The result: tighter plans that survive expert scrutiny, more robust implementations with edge cases identified up front, and a codebase that accumulates institutional knowledge rather than losing it between sessions.

### 2. Persistent Knowledge Graph

A KuzuDB-backed graph that indexes your codebase once and serves it to agents instantly:

- **Code structure**: Functions, classes, methods, interfaces, import chains, call graphs -- across Python, TypeScript, Go, Rust, Java, C, and C++
- **Governance artifacts**: Plans, contracts, learnings, review findings linked to the code they reference
- **Community detection**: Leiden algorithm clustering identifies tightly coupled modules
- **Semantic search**: Hybrid search combining structural graph queries with vector embeddings
- **Incremental indexing**: SHA-256 content hashing means only changed files are re-processed
- **Contract drift detection**: Automatically surfaces methods declared in contracts but missing from code

The graph is exposed via **MCP tools** that any compatible agent can call, or through the CLI for direct use.

## Quick Start

```bash
pip install agentscaffold
cd my-project
scaffold init
scaffold index          # Build the knowledge graph
```

The `init` command scaffolds your project with:

- `docs/ai/` -- templates, prompts, standards, state files
- `AGENTS.md` -- rules your AI agent follows automatically
- `.cursor/rules.md` -- Cursor-specific rules
- `scaffold.yaml` -- your project's framework configuration
- `justfile` + `Makefile` -- task runner shortcuts
- `.github/workflows/` -- CI with security scanning

The `index` command builds the knowledge graph at `.scaffold/graph.db`, enabling search, reviews, impact analysis, and session memory.

### Install with language support

```bash
pip install agentscaffold[graph]              # Python, JS, TS
pip install agentscaffold[graph-all-languages] # + Go, Rust, Java, C, C++
pip install agentscaffold[all]                # Everything
```

## How Agents Use It

### MCP Tools (for AI agents)

When you run `scaffold mcp`, these tools become available to your agent.

You don't need to memorize tool names. AgentScaffold ships with **intent descriptions** -- natural language trigger phrases that teach your agent to select the right tool automatically. Say "let's review plan 42" and the agent calls `scaffold_prepare_review`. Say "where did we leave off?" and it calls `scaffold_orient`. Run `scaffold agents cursor` (or `windsurf`, `claude`) to generate platform-specific rules that wire this up for your IDE.

**Composite tools** -- single calls that replace entire multi-step workflows:

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

**Granular tools** -- building blocks for custom queries:

| Tool | What It Replaces |
|------|-----------------|
| `scaffold_context` | Reading 12+ files to understand a symbol, its callers, and its layer |
| `scaffold_impact` | Manually tracing imports and grep-searching for consumers |
| `scaffold_search` | Multiple grep passes to find code by concept |
| `scaffold_review_context` | Reading plan files, contracts, and source to prepare a single review type |
| `scaffold_stats` | Scanning the entire directory tree to understand codebase shape |
| `scaffold_validate` | Running separate staleness checks and contract verification |
| `scaffold_query` | Writing ad-hoc Cypher queries against the knowledge graph |

### CLI (for humans)

```bash
scaffold plan create my-feature        # Create a plan from template
scaffold plan lint --plan 001          # Validate plan structure
scaffold plan status                   # Dashboard of all plans
scaffold validate                      # Run all enforcement checks
scaffold retro check                   # Find missing retrospectives
scaffold agents generate               # Regenerate AGENTS.md
scaffold agents cursor                 # Regenerate .cursor/rules.md
scaffold import chat.json --format chatgpt  # Import conversation
scaffold ci setup                      # Generate CI workflows
scaffold metrics                       # Plan analytics
scaffold graph search "data routing"   # Hybrid search
scaffold graph verify                  # Graph accuracy check
scaffold review brief 42               # Pre-review brief for plan 42
scaffold review challenges 42          # Adversarial challenges with evidence
scaffold session start --plan 42       # Start a tracked coding session
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

The governance framework is domain-aware. Domain packs teach the adversarial reviewers to think like specialists in your field -- a trading pack adds a quant architect who challenges risk assumptions and position sizing logic, a webapp pack adds a UX reviewer who flags accessibility gaps and performance regressions. Each pack includes tailored review prompts, implementation standards, and approval gates specific to the domain:

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

```bash
scaffold domain add trading
scaffold domain add webapp
```

## Documentation

Full documentation is in [docs/](docs/):

- [Getting Started](docs/getting-started.md) -- installation, init, first plan
- [User Guide](docs/user-guide.md) -- session workflow, knowledge graph, review patterns
- [Platform Integration](docs/platform-integration.md) -- Cursor, Claude Code, Windsurf, Cline, aider, Codex, MCP setup
- [Configuration Reference](docs/configuration.md) -- full scaffold.yaml reference
- [Domain Packs](docs/domain-packs.md) -- available packs and installation
- [Semi-Autonomous Guide](docs/semi-autonomous-guide.md) -- CLI/CI agent mode
- [CI Integration](docs/ci-integration.md) -- GitHub Actions workflows

## License

MIT
