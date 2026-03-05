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

Every tool call your agent doesn't make is money you don't spend on API tokens or subscription overages.

## What It Does

AgentScaffold combines two capabilities that don't exist together in any other tool:

### 1. Agent Governance Framework

A structured development workflow that teaches your AI agent to follow a plan lifecycle with quality gates:

- **Plan lifecycle**: Draft -> Review -> Ready -> In Progress -> Complete
- **Adversarial reviews**: Devil's advocate, expansion analysis, domain-specific reviews -- all run before a single line of code is written
- **Interface contracts**: Formal declarations of module boundaries, versioned and tracked
- **Retrospectives**: Post-execution learning that feeds back into the process
- **Session tracking**: State files that persist context across chat sessions

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

When you run `scaffold mcp`, these tools become available to your agent:

| Tool | What It Replaces |
|------|-----------------|
| `scaffold_context` | Reading 12+ files to understand a symbol, its callers, and its layer |
| `scaffold_impact` | Manually tracing imports and grep-searching for consumers |
| `scaffold_search` | Multiple grep passes to find code by concept |
| `scaffold_review_context` | Reading plan files, contracts, learnings, and source to prepare a review |
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

Domain packs add specialized review prompts, standards, and approval gates:

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
