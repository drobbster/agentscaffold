---
study_id: STU-2026-03-03-agentscaffold-vs-claude-code-architecture
title: "AgentScaffold vs Claude Code Architecture -- Deep Analysis"
study_type: exploratory
status: complete
started: 2026-03-03
completed: 2026-03-03
tags: [architecture, agent-framework, claude-code, agentscaffold, design-patterns]
related_plans: [149]
related_studies: []
---

# STU-2026-03-03: AgentScaffold vs Claude Code Architecture -- Deep Analysis

**Created**: 2026-03-03
**Status**: Complete
**Tags**: architecture, agent-framework, claude-code, agentscaffold, design-patterns
**Outcome**: Recommendations for AgentScaffold evolution

---

## 1. Executive Summary

Claude Code has evolved from a simple code assistant into a full agent platform with a
composable extension model. Its architecture is organized around five core primitives:
**hooks** (lifecycle event interception), **agents/subagents** (specialized delegated
workers), **skills** (reusable instruction packages), **plugins** (shareable bundles of
all primitives), and **MCP servers** (external tool bridges). These primitives are
layered so they compose cleanly: a plugin can bundle agents that preload skills that
define hooks that call MCP servers.

AgentScaffold shares significant conceptual DNA with Claude Code -- both systems have
knowledge graphs, MCP tool exposure, agent instructions generation, and lifecycle-gated
governance. However, AgentScaffold was designed as a *framework that generates
configuration* for platforms like Cursor, Claude Code, and Windsurf, rather than as a
*runtime extension system* within a single platform.

This study identifies seven architectural gaps, three structural strengths AgentScaffold
already has that Claude Code lacks, and a concrete recommendation framework for evolution.

---

## 2. Architecture Comparison Matrix

### 2.1 Primitives Side-by-Side

| Capability | Claude Code | AgentScaffold | Gap Assessment |
|---|---|---|---|
| **Lifecycle hooks** | 17+ events (PreToolUse, PostToolUse, SessionStart, Stop, SubagentStart, etc.) with command/HTTP/prompt/agent handler types | No hook system; `notify.sender` fires events but cannot intercept or block | **Critical gap** |
| **Agent definitions** | `.claude/agents/*.md` with YAML frontmatter (model, tools, permissions, memory, hooks, skills) | `agents/generate.py` produces AGENTS.md; `agents/cursor.py` produces .cursor/rules.md | **Structural gap** -- AS generates static instruction docs, not runtime-dispatchable agents |
| **Skills** | `SKILL.md` with progressive disclosure (catalog -> instructions -> resources), invocation control, subagent execution | Domain packs with `manifest.yaml` + Jinja2 prompt templates | **Conceptual overlap** but different execution model |
| **Plugins** | Self-contained directory with plugin.json manifest; bundles skills, agents, hooks, MCP servers, LSP servers | Domain packs are the closest analog but lack hook/agent bundling | **Significant gap** |
| **MCP servers** | First-class transport (stdio/HTTP); tools, resources, prompts; lazy-loaded via MCP Tool Search | AS *is* an MCP server exposing 18 tools via stdio | **Strength** -- AS already speaks MCP natively |
| **Knowledge graph** | None built-in; relies on MCP servers and file-system tools | KuzuDB graph with structure/parsing/governance/communities/embeddings | **Major AS strength** |
| **Plan lifecycle** | No built-in governance; relies on CLAUDE.md instructions | Full lifecycle (Draft -> Review -> Ready -> In Progress -> Complete) with gates, reviews, validation | **Major AS strength** |
| **Review system** | No built-in review personas; can be approximated with subagents | Devil's advocate, expansion, domain-specific (quant architect, etc.) with graph-backed context | **Major AS strength** |

### 2.2 Extension Model Comparison

| Dimension | Claude Code | AgentScaffold |
|---|---|---|
| Extension unit | Plugin (directory + manifest) | Domain pack (directory + manifest.yaml) |
| Distribution | Marketplace (official + community), git repos | pip install, manual copy |
| Discoverability | `/plugin` command, marketplace search | `scaffold domains list` |
| Composability | Plugin bundles agents + skills + hooks + MCP + LSP | Domain pack bundles prompts + standards |
| Scoping | User / Project / Local / Managed / Plugin | Global (installed in scaffold.yaml) |
| Versioning | semver in plugin.json | None |
| Sharing | Git repos, marketplaces, CLI install | Not designed for sharing outside monorepo |

### 2.3 Agent/Persona Model Comparison

| Dimension | Claude Code Subagents | AgentScaffold Expert Reviewers |
|---|---|---|
| Definition format | Markdown + YAML frontmatter | Jinja2 prompt templates (.md.j2) |
| Runtime behavior | Spawned as isolated context windows with own model/tools/permissions | Injected as prompt context into MCP tool responses |
| Model selection | Per-agent (haiku/sonnet/opus/inherit) | N/A (single model, platform-dependent) |
| Tool restrictions | Allowlist/denylist per agent | N/A |
| Persistent memory | `memory: user/project/local` with auto-managed MEMORY.md | N/A -- learnings tracked in static files |
| Lifecycle hooks | Per-agent PreToolUse, PostToolUse, etc. | N/A |
| Isolation | Own context window; cannot see parent conversation | Runs within same conversation context |
| Parallel execution | Background agents, git worktree isolation | N/A |

---

## 3. Deep Analysis: Seven Architectural Gaps

### Gap 1: No Lifecycle Hook System

**What Claude Code has**: 17+ lifecycle events that fire at precise moments in the
agent loop. Hooks are deterministic (always execute when matched), support four handler
types (command, HTTP, prompt, agent), and can block operations (PreToolUse exit code 2
denies a tool call). Hooks are composable -- a skill can define hooks scoped to its
lifetime, a plugin can bundle hooks, and subagents can have their own hooks.

**What AgentScaffold has**: A `notify.sender.send_notification()` that fires on four
events (plan_complete, escalation, validation_failure, approval_required). These are
fire-and-forget notifications, not interceptors.

**Why this matters**: Hooks are the enforcement layer. AgentScaffold has governance
rules (prohibitions, safety boundaries, gate requirements) but they are enforced via
`scaffold validate` as a separate CLI step that must be manually invoked. With hooks,
these same rules could be enforced in real-time as the agent works. For example:

- A `PreToolUse` hook on Write/Edit could run `check_prohibitions()` before any file
  is written, blocking emoji insertion or secrets exposure in real-time
- A `PostToolUse` hook could trigger incremental graph updates after file modifications,
  solving the freshness problem at its root
- A `SessionStart` hook could auto-run `scaffold orient` to give the agent fresh context
- A `Stop` hook could auto-run `scaffold validate` before the agent ends its turn

**Recommendation**: Implement a hook system as AgentScaffold's highest-priority
architectural addition. See Section 5 for the design proposal.

### Gap 2: Static Agent Definitions vs Runtime-Dispatchable Agents

**What Claude Code has**: Subagent markdown files in `.claude/agents/` that the
orchestrator can spawn as isolated context windows. Each agent has its own model,
tool restrictions, permission mode, memory, and hooks. The orchestrator reads each
agent's `description` field and delegates automatically.

**What AgentScaffold has**: `scaffold agents generate` produces a static AGENTS.md file
and `scaffold agents cursor` produces a static .cursor/rules.md. These are instruction
documents that tell the hosting platform's agent how to behave. They do not create
dispatchable sub-agents.

The expert reviewer prompts (devil's advocate, expansion, quant architect, etc.) are
conceptually similar to Claude Code subagents -- they are specialized personas with
domain expertise. But they execute as prompt injections into the current conversation
rather than as isolated agents.

**Why this matters**: The static model means every reviewer persona shares the same
context window, model, and tool access. A "quant architect review" cannot be run on a
cheaper/faster model, cannot be restricted to read-only tools, and cannot be parallelized
with the "devil's advocate review."

**Recommendation**: Generate `.claude/agents/` files from domain pack review personas.
Each expert reviewer becomes a spawnable subagent with appropriate model selection
and tool restrictions. See Section 5.2.

### Gap 3: No Progressive Skill Disclosure

**What Claude Code has**: Skills use a three-tier progressive disclosure model:
1. **Catalog** (~50-100 tokens per skill): name + description loaded at session start
2. **Instructions** (<5000 tokens): full SKILL.md loaded on activation
3. **Resources**: supporting files loaded only when referenced

This means 50 skills add only ~5000 tokens at startup. The full payload loads only
when relevant.

**What AgentScaffold has**: Domain pack prompts are Jinja2 templates that are fully
rendered when requested via MCP tools. The MCP tool system has some lazy-loading
properties (tools are only called when the agent decides to use them), but there is no
catalog/discovery layer that lets the agent know what specialized knowledge is available
without loading it.

**Why this matters**: As domain packs grow (trading, mlops, infrastructure, webapp,
etc.), the total prompt payload grows. Progressive disclosure would let AgentScaffold
surface all available domain expertise as lightweight metadata, loading full instructions
only when relevant.

**Recommendation**: Adopt the SKILL.md format for domain pack prompts. See Section 5.3.

### Gap 4: No Plugin Marketplace / Packaging Standard

**What Claude Code has**: Plugins are self-contained directories with a standard
manifest (`plugin.json`), standard directory layout, and CLI commands for discovery,
install, update, and removal. Over 9,000 plugins are available across 43 community
marketplaces.

**What AgentScaffold has**: Domain packs are internal Python packages within the
`agentscaffold` source tree. Adding a new domain pack requires modifying the core
package. There is no external packaging, marketplace, or install-from-URL flow.

**Why this matters**: For AgentScaffold to grow beyond the rebellion-trading-system
monorepo, external contributors need to create and share domain packs without modifying
the core package. The trading domain pack, for example, could be a standalone package
that trading teams install independently.

**Recommendation**: Extract domain packs into an external plugin format. See Section 5.4.

### Gap 5: Incomplete ReviewFinding Write-Back Loop

**What Claude Code has**: Subagents can have persistent memory scoped to user, project,
or local. A `MEMORY.md` file in the agent's memory directory persists across sessions.
The agent is instructed to curate this file, building institutional knowledge. However,
this is a flat markdown scratchpad -- unstructured, unscoped (the same 200 lines
regardless of task), not queryable, and siloed per agent.

**What AgentScaffold already has**: The knowledge graph already serves as a far superior
memory layer. It provides:

- **Structural memory**: File, Function, Class, Method, Interface nodes with IMPORTS
  and CALLS edges -- the agent knows what exists and how it connects
- **Governance memory**: Plan, Contract, Learning, Study, ADR, Spike nodes with edges
  to code -- the agent knows what decisions were made and why
- **Historical memory**: Session nodes, plan status tracking, git-linked change history
- **ReviewFinding schema**: The graph schema already defines a `ReviewFinding` node type
  with `reviewType`, `planNumber`, `severity`, `category`, `finding`, `resolution`, and
  `status` fields, plus four edge types: `FINDING_ABOUT_FILE`, `FINDING_ABOUT_FUNC`,
  `FINDING_LED_TO` (Learning), and `FINDING_ADDRESSED_BY` (Plan)
- **Read-path queries**: `review.queries.get_findings_for_file()` and
  `get_recurring_finding_patterns()` already query these nodes, and
  `review.challenges.generate_challenges()` already incorporates past findings into
  new reviews

**What is missing**: The ReviewFinding nodes are populated during batch indexing by
parsing plan appendices and review documents (`governance._parse_review_findings`).
There is no MCP tool that lets an agent **write findings back during a live review
session**. The graph can read findings but agents cannot create them in real-time.

This means the graph accumulates findings only when plans are re-indexed, not when
reviews are actively happening. A quant architect review that discovers "this plan
overlooks data_contracts updates" cannot record that finding into the graph during
the session. The finding exists only in the conversation transcript and is lost unless
someone manually writes it into a plan appendix that the next index picks up.

**Why this matters**: The read path is excellent. The write path is the gap. Closing it
creates a virtuous cycle: reviews produce findings, findings are queryable, future
reviews surface past findings for overlapping files, reviewers get smarter without
relying on flat-file memory.

**Recommendation**: Add a `scaffold_record_finding` MCP tool and enhance the
ReviewFinding graph integration. This is a graph-native solution that supersedes Claude
Code's MEMORY.md approach entirely. See Section 5.5.

### Gap 6: No Inline Hook Definitions in Agent/Skill Frontmatter

**What Claude Code has**: Hooks can be defined directly in skill and agent YAML
frontmatter, scoped to the component's lifetime. A "secure-operations" skill can
define a PreToolUse hook that validates every Bash command while the skill is active.
When the skill finishes, the hook is removed.

**What AgentScaffold has**: No equivalent. Governance constraints are expressed in
static markdown (AGENTS.md, plan files) and validated by separate CLI commands.

**Why this matters**: This is the composability multiplier. It means a domain pack's
expert reviewer can bring its own safety constraints. A "live trading review" agent
could define hooks that block any file writes to `execution/` directories during review
mode, ensuring the reviewer stays read-only.

**Recommendation**: Include this in the hook system design (Gap 1). Agent definitions
should support `hooks:` frontmatter.

### Gap 7: No LSP Integration

**What Claude Code has**: Plugins can bundle LSP (Language Server Protocol) servers that
give the agent real-time type information, go-to-definition, find-references, and
instant diagnostics after each edit.

**What AgentScaffold has**: The graph provides similar capabilities (symbol resolution,
IMPORTS edges, CALLS edges, community detection) but requires explicit indexing rather
than real-time updates.

**Why this matters**: LSP provides real-time, zero-latency code intelligence that
complements the graph's batch-indexed structural analysis. For a trading system where
type safety is critical, LSP-powered diagnostics could catch contract violations
immediately.

**Recommendation**: Lower priority. The graph already provides most of this value.
Consider LSP as a future enhancement once hooks are implemented (a PostToolUse hook
could trigger LSP diagnostics after each edit).

---

## 4. Structural Strengths AgentScaffold Has That Claude Code Lacks

### Strength 1: Knowledge Graph with Governance Topology

Claude Code has no built-in knowledge graph. It relies on file-system tools (Read, Grep,
Glob) and MCP servers for codebase understanding. AgentScaffold's KuzuDB graph with
structure, parsing, governance, communities, and embeddings is a significant advantage.
The graph connects code topology (functions, classes, imports, calls) with governance
artifacts (plans, contracts, learnings, studies, ADRs) into a queryable whole.

No Claude Code plugin currently offers this depth of structural + governance analysis.

### Strength 2: Structured Plan Lifecycle with Gates

Claude Code has no built-in plan lifecycle. Its approach is open-ended: CLAUDE.md can
describe a workflow, but there is no enforcement beyond what the agent chooses to follow.
AgentScaffold's gate system (Draft -> Review -> Ready -> In Progress -> Complete) with
specific requirements at each transition is a structured governance layer that Claude
Code delegates entirely to user configuration.

### Strength 3: Multi-Platform Agent Generation

Claude Code's agent definitions only work in Claude Code. AgentScaffold generates
platform-specific agent instructions for Cursor, Claude Code (CLAUDE.md), Windsurf,
and generic system prompts from a single source of truth (TOOL_INTENTS). This
cross-platform capability is unique and valuable for teams using multiple AI tools.

---

## 5. Recommendation Framework: AgentScaffold Evolution Path

### 5.1 Priority 1: Hook System (Effort: Large)

**Goal**: Add lifecycle event interception to AgentScaffold so governance rules can be
enforced in real-time rather than as manual validation steps.

**Design Proposal**:

```
src/agentscaffold/
  hooks/
    __init__.py
    engine.py         # Hook dispatch engine
    events.py         # Event type definitions
    handlers.py       # Command, HTTP, prompt handler types
    config.py         # Hook configuration schema
    generator.py      # Generate hooks.json for Claude Code / platform hooks
```

**Event Types** (aligned with Claude Code for interop):

| Event | AS Equivalent | Enforcement Opportunity |
|---|---|---|
| PreToolUse | New | Block prohibited patterns, secrets, unsafe operations |
| PostToolUse | New | Auto-run linters, trigger incremental index, format checks |
| SessionStart | New | Auto-orient (run scaffold_orient), load freshness state |
| SessionEnd/Stop | New | Auto-validate, persist session summary, update workflow state |
| PlanTransition | AS-specific | Gate enforcement (is the plan ready for this transition?) |
| ReviewComplete | AS-specific | Auto-update plan metadata, create learnings |

**Key Design Decision**: AgentScaffold hooks should be both:
1. **Internal** -- executed by the `scaffold` CLI during its own operations
2. **Generative** -- able to produce `.claude/settings.json` hooks, `.cursor/` hooks,
   etc. for the hosting platform

This dual nature is critical. AgentScaffold should not try to be the runtime (that is
Claude Code / Cursor's job). Instead, it should generate the hook configurations that
the runtime executes, while also supporting its own hook dispatch for CLI operations.

**Implementation Approach**:

```python
# hooks/events.py
from enum import Enum

class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    PLAN_TRANSITION = "PlanTransition"
    REVIEW_COMPLETE = "ReviewComplete"
    PRE_VALIDATE = "PreValidate"
    INDEX_COMPLETE = "IndexComplete"

# hooks/generator.py -- generates platform-native hook configs
def generate_claude_code_hooks(config: ScaffoldConfig) -> dict:
    """Produce .claude/settings.json hooks section from scaffold.yaml."""
    hooks = {}
    if config.prohibitions.emojis:
        hooks.setdefault("PostToolUse", []).append({
            "matcher": "Write|Edit",
            "hooks": [{
                "type": "command",
                "command": "scaffold validate --check prohibitions --file $CLAUDE_TOOL_INPUT_FILE_PATH"
            }]
        })
    if config.freshness.async_enabled:
        hooks.setdefault("PostToolUse", []).append({
            "matcher": "Write|Edit",
            "hooks": [{
                "type": "command",
                "command": "scaffold index --incremental --quiet",
                "async": True
            }]
        })
    return hooks
```

### 5.2 Priority 2: Expert Reviewers as Spawnable Agents (Effort: Medium)

**Goal**: Generate `.claude/agents/` files from domain pack review personas so expert
reviewers become runtime-dispatchable subagents.

**Design Proposal**:

Add `scaffold agents claude-agents` command that produces markdown files with YAML
frontmatter for each review persona:

```markdown
---
name: quant-architect
description: Deep architectural review for trading systems. Invoke for HFT
  scalability, RL readiness, risk model correctness, and market microstructure
  analysis. Use when reviewing trading plans, risk calculations, or execution logic.
tools: Read, Grep, Glob, mcp__agentscaffold__scaffold_review_context,
  mcp__agentscaffold__scaffold_context, mcp__agentscaffold__scaffold_impact,
  mcp__agentscaffold__scaffold_record_finding
model: inherit
hooks:
  PreToolUse:
    - matcher: "Write|Edit"
      hooks:
        - type: command
          command: "echo 'Reviewer is read-only' >&2 && exit 2"
---

You are a quantitative architect reviewing trading system designs.

When you discover issues, record each finding using scaffold_record_finding
with the plan number, category, severity, and related files. This ensures
your findings persist in the knowledge graph and are surfaced to future
reviewers working on overlapping files.

[rest of quant_architect_review.md.j2 content rendered]
```

**What changes**:
- Each domain pack `prompts/*.md.j2` maps to an agent definition
- Model selection is configurable per reviewer in the domain manifest
- Tool restrictions enforce read-only for file operations during reviews
- `scaffold_record_finding` MCP tool is allowed so findings write back to the graph
- The graph serves as cross-session memory (no flat-file MEMORY.md needed)
- The agent's description enables auto-delegation by Claude Code

**New CLI**:
```bash
scaffold agents claude-agents    # Generate .claude/agents/ from domain packs
scaffold agents claude-agents --dry-run  # Preview without writing
```

### 5.3 Priority 3: SKILL.md Format for Domain Knowledge (Effort: Medium)

**Goal**: Adopt the Agent Skills open standard (agentskills.io) so AgentScaffold's
domain knowledge is discoverable across 27+ AI tools.

**Design Proposal**:

Convert domain pack standards and conventions into SKILL.md format:

```
src/agentscaffold/domains/trading/
  skills/
    trading-traceability/
      SKILL.md          # Standard for traceability in trading modules
      references/
        traceability.md # Full standard document
    risk-model-review/
      SKILL.md          # When to invoke risk model checks
      scripts/
        check_risk_bounds.py
```

`scaffold agents cursor` would generate `.claude/skills/` alongside `.cursor/rules.md`.

**Benefits**:
- Progressive disclosure (catalog metadata at startup, full content on activation)
- Cross-tool compatibility (works in Claude Code, Cursor, Codex, Gemini CLI, etc.)
- Standard packaging format that domain packs can export

### 5.4 Priority 4: External Plugin Format (Effort: Large)

**Goal**: Allow domain packs to be distributed as standalone packages.

**Design Proposal**:

Adopt a plugin manifest format compatible with (but not identical to) Claude Code's
plugin.json:

```json
{
  "name": "agentscaffold-trading",
  "version": "1.0.0",
  "description": "Trading domain pack for AgentScaffold",
  "scaffold_compatibility": ">=0.3.0",
  "components": {
    "reviews": ["quant_architect", "quant_architect_implementation"],
    "standards": ["traceability", "risk_accounting"],
    "skills": ["trading-traceability", "risk-model-review"],
    "hooks": "hooks/hooks.json",
    "agents": ["quant-architect", "risk-reviewer"]
  }
}
```

**Distribution**: pip packages (`pip install agentscaffold-trading`) or git repos.

**Installation**:
```bash
scaffold domains add trading                    # Built-in (current behavior)
scaffold domains add agentscaffold-trading      # From pip
scaffold domains add git+https://github.com/... # From git
```

### 5.5 Priority 2.5: Graph-Native ReviewFinding Write-Back (Effort: Medium)

**Goal**: Close the read-write loop so expert reviewers can record findings directly
into the knowledge graph during live review sessions, making the graph the single
persistent memory layer for all agents.

**What already exists** (more than expected):

The graph schema already defines the full ReviewFinding data model:

```
Node: ReviewFinding
  id, reviewType, planNumber, severity, category, finding, resolution, status

Edges:
  FINDING_ABOUT_FILE   (ReviewFinding -> File)
  FINDING_ABOUT_FUNC   (ReviewFinding -> Function)
  FINDING_LED_TO       (ReviewFinding -> Learning)
  FINDING_ADDRESSED_BY (ReviewFinding -> Plan)
```

The read path is already wired:
- `review.queries.get_findings_for_file(store, path)` queries findings by file
- `review.queries.get_recurring_finding_patterns(store, min=2)` finds repeated categories
- `review.challenges.generate_challenges()` incorporates past findings into new reviews

The batch write path exists in `governance._parse_review_findings()`, which extracts
structured `[CATEGORY] text` markers from plan appendices during `scaffold index`.

**What needs to be built**:

1. **New MCP tool: `scaffold_record_finding`**

```python
@server.tool()
async def scaffold_record_finding(
    plan_number: int,
    review_type: str,       # "quant_architect", "devils_advocate", "expansion", etc.
    category: str,          # "RISK", "GAP", "PATTERN", "DEPENDENCY", "CONTRACT", etc.
    finding: str,           # The actual finding text
    severity: str = "medium",  # "high", "medium", "low"
    related_files: list[str] | None = None,
    related_functions: list[str] | None = None,
) -> str:
    """Record a review finding into the knowledge graph.

    Creates a ReviewFinding node and edges to related code entities.
    Finding is immediately queryable by all subsequent review operations.
    """
```

This is the missing write path. When a quant architect review discovers that Plan 149
does not update data_contracts for a new feature, the agent calls:

```
scaffold_record_finding(
    plan_number=149,
    review_type="quant_architect",
    category="CONTRACT",
    finding="Plan adds new risk feature but does not update data_contracts/risk_feature.py",
    severity="high",
    related_files=["libs/risk/new_feature.py", "data_contracts/risk_feature.py"]
)
```

The finding is now a graph node with edges to the affected files. It persists across
sessions and is queryable by any agent reviewing plans that touch those files.

2. **New MCP tool: `scaffold_resolve_finding`**

```python
@server.tool()
async def scaffold_resolve_finding(
    finding_id: str,
    resolution: str,
    addressed_by_plan: int | None = None,
) -> str:
    """Mark a finding as resolved and record how it was addressed."""
```

This closes findings when they are fixed, preventing them from surfacing indefinitely.

3. **Enhanced review context injection**

Update `scaffold_prepare_review` and `scaffold_review_context` to automatically include
relevant past findings:

```cypher
-- When reviewing Plan 149 that impacts files A, B, C:
MATCH (rf:ReviewFinding)-[:FINDING_ABOUT_FILE]->(f:File)<-[:PLAN_IMPACTS]-(p:Plan)
WHERE p.number = 149 AND rf.status = 'open'
RETURN rf.category, rf.finding, rf.severity, rf.reviewType, rf.planNumber
```

This means every review automatically sees: "Previous reviews on files you are about to
touch found these unresolved issues." The read path already supports this query; it just
needs to be wired into the review context builder.

**How this replaces Claude Code's MEMORY.md**:

| Dimension | Claude Code MEMORY.md | Graph ReviewFindings |
|---|---|---|
| Structure | Flat markdown, unstructured | Typed nodes with severity, category, status |
| Scope | Same 200 lines regardless of task | Scoped to files/functions overlapping current plan |
| Querying | Text search only | Cypher graph traversal |
| Cross-agent | Siloed per agent | Shared across all reviewers |
| Staleness | Agent must manually curate | Auto-scoped by file overlap; resolved findings drop out |
| Capacity | 200-line limit | Unlimited graph nodes |
| Platform | Claude Code only | Any MCP client |
| Relationships | None | Edges to files, functions, learnings, plans |

The graph is not just a better memory -- it is a different category of memory. MEMORY.md
is a personal notebook. The graph is an institutional knowledge base with typed
relationships and scoped retrieval.

**How this fits into the system**:

```
Review session starts
  |
  Agent calls scaffold_prepare_review(plan=149)
  |
  Graph returns:
    - Plan metadata, file impact map, blast radius
    - Contracts and drift status
    - ADRs and past decisions
    - [NEW] Open findings on overlapping files from past reviews
    - [NEW] Recurring finding patterns (e.g., "CONTRACT issues appear 4x")
  |
  Agent performs review with full institutional context
  |
  Agent calls scaffold_record_finding() for each discovery
  |
  Findings become graph nodes with edges to files/functions
  |
  Next review of plans touching same files automatically surfaces these findings
```

The virtuous cycle: reviews produce findings, findings inform future reviews, patterns
emerge from finding aggregation, systemic issues become visible without any agent
needing to maintain a personal scratchpad.

**Implementation steps**:

| Step | Deliverable | Effort |
|---|---|---|
| 1. `scaffold_record_finding` MCP tool | Write path for findings during live sessions | Medium |
| 2. `scaffold_resolve_finding` MCP tool | Close findings when addressed | Small |
| 3. Review context enhancement | Auto-surface open findings for overlapping files | Small |
| 4. Recurring pattern detection | Surface systemic issues across reviews | Small |
| 5. Agent prompt integration | Generated agent prompts instruct reviewers to record findings | Small |

Step 1 is the critical path. Steps 2-5 leverage existing graph infrastructure.

---

### 5.6 Audit: Claude Code Primitives Not Yet Utilized

Three Claude Code primitives are not directly adopted in the rearchitecture framework:

**1. LSP-in-Plugin (Gap 7, P5 -- explicitly deferred)**

Claude Code plugins can bundle LSP servers for real-time type information, diagnostics,
and go-to-definition. AgentScaffold's graph already provides symbol resolution, import
edges, and call edges via batch indexing. LSP would add real-time diagnostics after
each edit, but the graph covers the primary use cases (blast radius, contract drift,
dependency analysis). LSP remains deferred because:
- The graph satisfies 80%+ of the code intelligence need
- LSP requires a running language server process per language
- The DuckDB migration (P1.5) and ReviewFinding write-back (P2.5) deliver more value
  per effort
- LSP can be added later as a PostToolUse hook that feeds diagnostics into the graph

If LSP is added in the future, the approach should be MCP tools (`scaffold_lsp_diagnostics`,
`scaffold_lsp_references`, etc.) behind an `LspProvider` protocol with graceful fallback
when no server is available. This keeps the intelligence in the MCP layer (Tier 1), not
in platform-specific plugin bundling.

**2. Native Claude Code subagent memory (Gap 5 -- superseded by graph)**

Claude Code's `memory: user/project/local` creates a flat MEMORY.md per agent. This is
intentionally not adopted. The graph-native ReviewFinding write-back (Section 5.5) is
categorically superior: structured, queryable, cross-agent, scoped by file overlap, and
platform-independent. See the comparison table in Section 5.5.

Generated agent definitions should omit `memory:` from frontmatter and instead instruct
agents to use `scaffold_record_finding` and `scaffold_prepare_review` for institutional
knowledge.

**3. Inline hook definitions in agent/skill frontmatter (Gap 6 -- planned, not yet realized)**

Claude Code allows hooks defined directly in agent and skill YAML frontmatter, scoped to
the component's lifetime. This is planned for Phase 2 (Section 5.2) where generated
`.claude/agents/*.md` files include `hooks:` frontmatter for read-only enforcement
during reviews. The mechanism is designed but implementation depends on Phase 1 (hook
generation) being complete first.

### 5.7 Cross-Cutting Guardrails for All Phases

These principles apply across every phase of the rearchitecture:

- **MCP-first is non-negotiable**: Core intelligence and memory loops must stay in MCP
  tools and graph schema, not platform-specific files. Platform artifacts contain
  routing mechanics only (see Section 7.5).
- **Progressive rollout**: Each phase is additive and must not break existing CLI flows.
  A user who never generates hooks or agents still gets full value from MCP tools.
- **No hard Claude Code lock-in**: Every new capability must degrade gracefully on
  platforms without hooks or subagent parity. The Tier 1/2/3 model (Section 7) ensures
  this structurally.
- **Traceability**: Findings should include source metadata (which tool, which query,
  which files) so reviewers can reconstruct why a finding was raised. This aligns with
  the traceability standard in `docs/ai/standards/traceability.md`.
- **Graph backend independence**: No phase should introduce KuzuDB-specific code outside
  the `KuzuBackend` class. All new graph operations must go through the `GraphBackend`
  protocol to support the DuckDB migration (Phase 1.5).

---

## 6. Implementation Roadmap

### Phase 1: Hook Generation + Graph Abstraction Layer (Weeks 1-3)

| Step | Deliverable | Effort |
|---|---|---|
| 1. Hook schema in scaffold.yaml | `hooks:` config section with event/matcher/handler | Small |
| 2. Claude Code hook generator | `scaffold agents hooks` produces .claude/settings.json hooks | Medium |
| 3. Built-in hook templates | Prohibition enforcement, freshness trigger, auto-orient | Medium |
| 4. PostToolUse -> incremental index | Solve freshness at the source | Small |
| 5. **GraphBackend protocol** | Formalize `graph/backend.py`, rename GraphStore to KuzuBackend | Small |
| 6. **`graph.backend` config** | Add backend selector to scaffold.yaml | Small |

**Outcome**: Governance rules enforced in real-time. Graph layer decoupled from KuzuDB.

### Phase 1.5: DuckDB + DuckPGQ Backend (Weeks 2-5, overlaps Phase 1-2)

| Step | Deliverable | Effort |
|---|---|---|
| 1. DuckPGQ schema translation | SQL CREATE TABLE + CREATE PROPERTY GRAPH from existing DDL | Medium |
| 2. DuckPGQBackend implementation | create_node, create_edge, query, node_count behind protocol | Medium |
| 3. Query translation (40-60 queries) | Cypher -> SQL/PGQ for all graph queries in codebase | Large |
| 4. Embedding migration to DuckDB vss | Replace separate embedding pipeline with native vector search | Medium |
| 5. Parallel testing harness | `scaffold graph verify --compare-backends` | Small |
| 6. Cutover: default to duckpgq | Change default in scaffold.yaml, update docs | Small |

**Outcome**: Graph runs on DuckDB with stable format, active maintenance, and native
vector search. KuzuBackend remains as fallback.

### Phase 2: Agent Definitions + ReviewFinding Write-Back (Weeks 3-6)

| Step | Deliverable | Effort |
|---|---|---|
| 1. Agent template from domain prompts | Jinja2 template producing .claude/agents/*.md | Medium |
| 2. `scaffold agents claude-agents` CLI | Generate all agent files from config | Small |
| 3. `scaffold_record_finding` MCP tool | Write path for findings during live sessions | Medium |
| 4. `scaffold_resolve_finding` MCP tool | Close findings when addressed | Small |
| 5. Review context enhancement | Auto-surface open findings for overlapping files | Small |
| 6. Agent prompt integration | Generated agents instructed to record findings | Small |
| 7. Review CLI integration | `scaffold review` delegates to spawnable agents | Medium |

**Outcome**: Expert reviewers become first-class Claude Code subagents that read from
and write back to the knowledge graph (now on DuckDB). The graph replaces flat-file
memory as the institutional knowledge layer for all agents.

### Phase 3: Skills Standard (Weeks 5-7)

| Step | Deliverable | Effort |
|---|---|---|
| 1. SKILL.md for domain standards | Convert existing .md.j2 to SKILL.md format | Medium |
| 2. Skill generation CLI | `scaffold agents skills` produces .claude/skills/ | Small |
| 3. Progressive disclosure metadata | Catalog entries for all domain knowledge | Small |

**Outcome**: Domain knowledge discoverable across all SKILL.md-compatible tools.

### Phase 4: Plugin Packaging (Weeks 7-10)

| Step | Deliverable | Effort |
|---|---|---|
| 1. Plugin manifest format | JSON schema for external domain packs | Medium |
| 2. External install flow | pip / git source installation | Large |
| 3. Extract trading pack | First external domain pack | Medium |

**Outcome**: Domain packs distributable as standalone packages.

---

## 7. Layered Capability Model: Multi-Platform Without Sub-Optimizing

The evolution proposed in Sections 5.1-5.5 is optimized for Claude Code, which has the
richest runtime primitives. To support multiple platforms without watering down the
Claude Code experience, the architecture should be organized into three capability tiers
based on how many platforms can consume each artifact.

### 7.1 Tier 1: MCP Core (universal -- any MCP client)

The intelligence layer. Every platform that connects to the AgentScaffold MCP server
gets these capabilities with zero platform-specific generation.

```
MCP Server (stdio)
  |
  +-- scaffold_prepare_review       (reads graph, surfaces findings)
  +-- scaffold_record_finding       (writes findings back to graph)
  +-- scaffold_resolve_finding      (finding lifecycle)
  +-- scaffold_context              (symbol lookup)
  +-- scaffold_impact               (blast radius)
  +-- scaffold_orient               (session context)
  +-- scaffold_validate             (governance checks)
  +-- ... (all 18+ tools)
```

This is where the graph-as-memory architecture pays its largest dividend. When an agent
calls `scaffold_record_finding` via MCP, it does not matter whether that agent is a
Claude Code subagent, a Cursor Task subagent, or a Windsurf session. The MCP tool writes
to the same graph. The next `scaffold_prepare_review` call reads from the same graph.
The virtuous cycle works on every platform.

If agent memory had been built on Claude Code's MEMORY.md, it would be locked to one
platform. By keeping it in the graph via MCP, every platform benefits equally from every
finding every agent on any platform ever recorded. This is cross-platform institutional
memory by default.

### 7.2 Tier 2: Agent Skills Standard (broad -- 27+ AI tools)

The SKILL.md format is an open standard (agentskills.io) supported by Claude Code,
Cursor, Codex, Gemini CLI, VS Code, GitHub Copilot, and others. Domain knowledge
published as skills reaches the widest audience beyond MCP.

```
.claude/skills/        (Claude Code discovers these)
.cursor/skills/        (Cursor discovers these)
```

Skills handle progressive disclosure natively. Each platform loads only the catalog
(~100 tokens per skill) at startup and full instructions on demand. AgentScaffold
generates the same SKILL.md files once; each platform discovers them in its own way.

### 7.3 Tier 3: Platform-Specific Runtime (per-platform generation)

This is where each platform gets its optimal experience. Generation is **additive** --
Tier 3 artifacts enhance the Tier 1 and Tier 2 baseline without replacing them.

| Artifact | Claude Code | Cursor | Windsurf |
|---|---|---|---|
| **Hooks** | `.claude/settings.json` (17 events, blocking, deterministic) | `.cursor/rules/` (file-pattern triggers, instructional) | N/A |
| **Expert agents** | `.claude/agents/*.md` (spawnable, isolated, parallel, model selection) | Task tool delegation (partial, via MCP tools) | Inline (via MCP tools) |
| **Rules** | `CLAUDE.md` | `.cursor/rules.md` | `.windsurfrules` |
| **MCP** | Full | Full | Full |
| **Skills** | Full (auto-invocation) | SKILL.md discovery | N/A |

On Claude Code, governance enforcement is deterministic (hooks fire automatically).
On Cursor, enforcement is instructional (rules tell the AI to use scaffold tools).
On Windsurf or any MCP client, the tools are available and the agent can be prompted
to use them.

### 7.4 How Each Initiative Decomposes Across Tiers

**Hook generation (P1)**:

| What you want enforced | Tier 1 (MCP) | Tier 3 (Claude Code) | Tier 3 (Cursor) |
|---|---|---|---|
| Prohibitions on file write | `scaffold_validate` tool (agent calls it) | PostToolUse hook auto-runs it | Rule says "always run scaffold_validate after editing" |
| Auto-orient on session start | `scaffold_orient` tool (agent calls it) | SessionStart hook auto-runs it | Rule says "start every session with scaffold_orient" |
| Block writes to protected files | `scaffold_validate --check safety` | PreToolUse hook blocks write | Rule says "never edit system_architecture.md" |
| Incremental index after edits | `scaffold index --incremental` | PostToolUse async hook | Rule says "run scaffold index --incremental after bulk edits" |

The generation layer knows what each platform supports:

```python
def generate_enforcement(config, platform):
    if platform == "claude-code":
        return generate_hooks_json(config)        # Deterministic enforcement
    elif platform == "cursor":
        return generate_cursor_rules(config)       # Instructional enforcement
    elif platform == "windsurf":
        return generate_windsurf_rules(config)     # Instructional enforcement
    else:
        return generate_mcp_instructions(config)   # Tool descriptions only
```

**Expert reviewers (P2)**:

| Platform | How expert reviews execute |
|---|---|
| Claude Code | Spawned as isolated subagents with own model, tools, parallel execution |
| Cursor | Invoked via Task tool with scaffold MCP context |
| Windsurf / Generic | Single-threaded; agent calls `scaffold_prepare_review` inline |

Review quality is comparable across platforms because the intelligence (graph queries,
finding history, governance context) comes from MCP tools. Execution efficiency varies:
Claude Code runs 3 reviewers in parallel on different models; Cursor runs them partially
parallel via Task subagents; Windsurf runs them sequentially in a single context.

**ReviewFinding write-back (P2.5)**:

The cleanest multi-platform story. Lives entirely at Tier 1.

```
Any platform --> MCP call --> scaffold_record_finding --> Graph node + edges
Any platform --> MCP call --> scaffold_prepare_review --> Reads findings from graph
```

A finding recorded by a Claude Code subagent is visible to a Cursor session reviewing
the same files next week. Cross-platform institutional memory by default.

### 7.5 The Key Principle

**Never put intelligence in the platform-specific layer.** Platform artifacts should
contain only routing and execution mechanics (how to invoke). The intelligence (graph
queries, finding history, review logic, governance validation) lives in the MCP server
and is identical across platforms.

```
Platform layer:  HOW to invoke  (hooks, agents, rules -- platform-specific)
                      |
                      v calls
MCP layer:       WHAT to invoke  (scaffold tools -- platform-agnostic)
                      |
                      v queries
Graph layer:     WHAT is known   (code topology, governance, findings)
```

Optimizing for Claude Code means adding better routing (hooks, spawnable agents) without
moving intelligence out of the MCP layer. Adding a new platform is just adding a new
routing generator. The graph, the findings, the review logic -- all of it transfers
automatically.

### 7.6 scaffold.yaml Platform Configuration

The configuration should express intent, not platform mechanics:

```yaml
enforcement:
  prohibitions_on_write: true
  auto_orient_on_session: true
  auto_index_after_edits: true
  block_protected_files: true

reviews:
  expert_reviewers:
    - name: quant_architect
      model_preference: capable        # "fast", "capable", "inherit"
      tools: read_only + mcp_review
    - name: devils_advocate
      model_preference: fast
      tools: read_only + mcp_review

platforms:
  claude_code:
    generate_hooks: true
    generate_agents: true
    generate_skills: true
  cursor:
    generate_rules: true
    generate_skills: true
  windsurf:
    generate_rules: true
```

A single command generates optimal artifacts for every configured platform:

```bash
scaffold agents generate --all-platforms
```

---

## 8. Graph Latency, Framework Risk, and Optimization Strategy

### 8.1 The Write Latency Question

With `scaffold_record_finding` as a live MCP tool, every finding write happens
synchronously during a review session. The agent calls the tool, waits for the
response, then continues. The question is whether KuzuDB can handle these writes
at interactive latency (under ~200ms per operation).

**Current write pattern analysis**:

The existing `GraphStore.create_node()` and `GraphStore.create_edge()` methods execute
Cypher INSERT statements directly against KuzuDB. A single `scaffold_record_finding`
call would execute:

1. One `CREATE` for the ReviewFinding node (~1 Cypher statement)
2. One `MATCH + CREATE` per related file edge (~1-5 Cypher statements)
3. One `MATCH + CREATE` per related function edge (~0-3 Cypher statements)

Total: 2-9 Cypher statements per finding.

**KuzuDB's write characteristics**:

KuzuDB is an embedded, columnar graph database. Its write model is:
- Single `READ_WRITE` database instance at a time (no concurrent writer processes)
- In-process execution (no network round-trip)
- Recent concurrent write improvements show ~105ms for 1M-tuple batch updates
- Single-row inserts are not extensively benchmarked, but in-process embedded writes
  for small operations are typically sub-millisecond

For the `scaffold_record_finding` use case (2-9 small inserts per call, invoked a few
times per review session), KuzuDB's write performance is more than adequate. The
bottleneck will not be the graph database -- it will be MCP transport overhead (stdio
serialization/deserialization) which is typically 10-50ms per tool call.

**The real latency concern is re-indexing, not findings**:

The `scaffold index --incremental` operation is where latency matters:
- Structure scan: walks the directory tree, computes SHA-256 hashes
- Parsing: tree-sitter extraction of functions/classes/methods
- Resolution: symbol table construction, import/call edge creation
- Governance: plan/contract/learning/ADR/study parsing

For the rebellion-trading-system (1508 files), a full index takes ~95 seconds. An
incremental index with a small changeset (5-10 files) takes 2-10 seconds. This is
already handled by the async freshness system: `maybe_schedule_async_refresh()` runs
indexing in a background thread with debounce (120s default), so MCP tool calls never
block on re-indexing.

### 8.2 The KuzuDB Risk: Building on a Dead-End Street

**KuzuDB was archived in October 2025** when its parent company (Kuzu Inc.) was
acquired by Apple. Active development has stopped on the original repository. This is
not a medium-term concern to hedge against -- it is a **committed migration trigger**.

**Why we cannot stay on KuzuDB**:

| Factor | Status | Impact |
|---|---|---|
| Original repo | Archived, read-only | No bug fixes, no security patches |
| On-disk format | Never stabilized | Any fork upgrade could require full re-index |
| Python package | Frozen at last published version | No compatibility fixes for future Python versions |
| Community forks | Bighorn (Kineviz), Vela-Engineering, LadybugDB | Uncertain longevity; single-company maintainers |
| CVE exposure | No upstream to patch | Security findings would require forking ourselves |

The Vela-Engineering fork is active and has added concurrent write support, but it is
maintained by a single venture capital firm for their specific use case. Betting the
AgentScaffold graph layer on a VC firm's side project is not materially better than
betting on an archived repo.

### 8.3 Migration Target: DuckDB + DuckPGQ (Committed)

DuckDB + DuckPGQ is the committed migration target, not a hedge.

**Why DuckDB**:

| Dimension | DuckDB | KuzuDB (archived) |
|---|---|---|
| Maintenance | Dedicated company (DuckDB Labs), 25k+ GitHub stars, MIT licensed | Archived, no maintainer |
| Release cadence | Monthly releases, active roadmap | Frozen |
| Python ecosystem | First-class Python API, pip installable, Pandas/Arrow integration | Python bindings frozen |
| Stability | On-disk format stable since 1.0, backward-compatible | Format never stabilized |
| Extensions | 100+ community extensions, official extension API | None |
| Vector support | `vss` extension for vector similarity search | Separate embedding layer |
| Graph support | DuckPGQ extension (SQL/PGQ, SQL:2023 standard) | Native Cypher |
| Adoption | Used by dbt, Motherduck, evidence.dev, thousands of production systems | Niche adoption |
| Performance | Vectorized columnar execution, OLAP-optimized | Columnar, graph-optimized |

**Why DuckPGQ specifically**:

DuckPGQ implements SQL/PGQ, the ISO SQL:2023 standard for property graph queries. This
means:
- Graph queries are standard SQL with graph pattern syntax (not a proprietary DSL)
- The underlying storage is relational tables that DuckDB manages natively
- Shortest-path, pattern matching, and graph traversal are supported
- Nodes and edges are defined as views over regular tables, so standard SQL and graph
  queries can coexist on the same data

**The migration cost**:

The primary cost is rewriting Cypher queries to SQL/PGQ syntax. The schema translation
is straightforward (node tables become regular tables, edge tables become edge views),
but the query syntax differs:

```
-- KuzuDB Cypher (current):
MATCH (rf:ReviewFinding)-[:FINDING_ABOUT_FILE]->(f:File)<-[:PLAN_IMPACTS]-(p:Plan)
WHERE p.number = 149 AND rf.status = 'open'
RETURN rf.category, rf.finding, rf.severity

-- DuckDB SQL/PGQ (target):
SELECT rf.category, rf.finding, rf.severity
FROM GRAPH_TABLE (scaffold_graph
  MATCH (rf:ReviewFinding)-[:FINDING_ABOUT_FILE]->(f:File)<-[:PLAN_IMPACTS]-(p:Plan)
  WHERE p.number = 149 AND rf.status = 'open'
  COLUMNS (rf.category, rf.finding, rf.severity)
)
```

The conceptual model (nodes, edges, pattern matching) is identical. The wrapping syntax
changes. This is a mechanical translation, not a redesign.

**What we gain beyond stability**:

- **Native vector search**: DuckDB's `vss` extension handles embeddings natively,
  replacing the separate embedding pipeline. Semantic search becomes a SQL query with
  vector similarity, not a separate system.
- **Standard SQL alongside graph**: Governance queries that mix relational aggregation
  with graph traversal (e.g., "count open findings per file, grouped by severity,
  filtered by graph path distance") are natural in SQL/PGQ but awkward in pure Cypher.
- **Ecosystem leverage**: DuckDB extensions for Parquet, JSON, HTTP, S3, PostgreSQL
  become available. The graph could read directly from external data sources.
- **Single-file database**: DuckDB 1.0+ stores everything in one file with stable
  format. No more re-index on version upgrades.

### 8.4 Migration Strategy: Abstraction Layer First, Then Swap

The migration proceeds in three phases, designed so AgentScaffold never has a broken
release and both backends can coexist during transition.

**Phase 1: Formalize the GraphBackend protocol (P1.5 priority, Weeks 1-2)**

The existing `GraphStore` already provides a backend-agnostic interface informally.
Formalize it:

```python
# graph/backend.py -- abstract interface
class GraphBackend(Protocol):
    def create_node(self, table: str, props: dict) -> None: ...
    def create_edge(
        self, rel: str, from_table: str, from_id: str,
        to_table: str, to_id: str, props: dict | None = None,
    ) -> None: ...
    def query(self, query_str: str, params: dict | None = None) -> list[dict]: ...
    def query_scalar(self, query_str: str, params: dict | None = None) -> Any: ...
    def node_count(self, table: str) -> int: ...
    def edge_count(self, rel_table: str) -> int: ...
    def clear_table(self, table: str) -> None: ...
    def close(self) -> None: ...

# graph/kuzu_backend.py -- rename existing GraphStore
class KuzuBackend:
    """Current implementation, unchanged."""
    ...

# graph/store.py -- becomes a thin router
def open_graph(db_path, backend="kuzu", read_only=False) -> GraphBackend:
    if backend == "kuzu":
        from agentscaffold.graph.kuzu_backend import KuzuBackend
        return KuzuBackend(db_path, read_only=read_only)
    elif backend == "duckpgq":
        from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
        return DuckPGQBackend(db_path, read_only=read_only)
    raise ValueError(f"Unknown backend: {backend}")
```

This is a refactor, not a rewrite. The existing code continues to work identically.
`scaffold.yaml` gains a `graph.backend` field (default: `kuzu`).

**Phase 2: Implement DuckPGQBackend (P1.5, Weeks 2-4)**

Build the DuckDB backend behind the same protocol:

| Component | KuzuBackend (current) | DuckPGQBackend (new) |
|---|---|---|
| Schema init | Cypher DDL strings | SQL CREATE TABLE + DuckPGQ CREATE PROPERTY GRAPH |
| create_node | Cypher CREATE | SQL INSERT INTO |
| create_edge | Cypher MATCH+CREATE | SQL INSERT INTO edge table |
| query | Cypher string | SQL/PGQ string |
| Embeddings | Separate pipeline | DuckDB `vss` extension |
| File format | KuzuDB directory | Single `.duckdb` file |

The query translation is the bulk of the work. There are approximately 40-60 Cypher
queries across the codebase (in `store.py`, `queries.py`, `search.py`, `governance.py`,
`verify.py`, `challenges.py`, `incremental.py`). Each needs a SQL/PGQ equivalent.

A `query_translator.py` module could handle the most common patterns mechanically:

```python
def cypher_to_sqlpgq(cypher: str, graph_name: str = "scaffold_graph") -> str:
    """Translate common Cypher patterns to SQL/PGQ."""
    # MATCH (n:Table) WHERE ... RETURN ... -> SELECT ... FROM GRAPH_TABLE(...)
    ...
```

**Phase 3: Parallel testing + cutover (Weeks 4-6)**

Run both backends against the same codebase and compare results:

```bash
scaffold index --backend kuzu
scaffold index --backend duckpgq
scaffold graph verify --backend kuzu --compare-with duckpgq
```

Once results match, change the default in `scaffold.yaml`:

```yaml
graph:
  backend: duckpgq     # was: kuzu
  db_path: .scaffold/graph.duckdb
```

KuzuBackend remains available for users who have not migrated, but new projects
default to DuckDB.

### 8.4.1 Why Not Just Rewrite Everything At Once

The abstraction-first approach costs an extra 1-2 weeks but provides:

1. **Zero-downtime migration**: Both backends work during transition
2. **Rollback path**: `graph.backend: kuzu` reverts instantly if issues emerge
3. **Testing parity**: Automated comparison catches query translation bugs
4. **Future flexibility**: If DuckPGQ proves insufficient for some workload, adding
   a third backend is just another protocol implementation
5. **Community value**: Users of AgentScaffold on other projects can choose their
   preferred embedded database

### 8.5 Write Optimization Strategies

Regardless of backend, these optimizations apply to the write-back loop:

**1. Batch finding writes**

Instead of one MCP call per finding (2-9 Cypher statements each), the
`scaffold_record_finding` tool could accept a list of findings and execute them in a
single transaction:

```python
async def scaffold_record_findings(  # Note: plural
    findings: list[FindingInput],
) -> str:
    """Record multiple findings in a single graph transaction."""
    with store.transaction():  # Single write transaction
        for f in findings:
            store.create_node("ReviewFinding", ...)
            for file in f.related_files:
                store.create_edge("FINDING_ABOUT_FILE", ...)
```

This reduces MCP round-trips from N to 1 for a review that produces N findings.

**2. Write-ahead buffer for async writes**

For PostToolUse hooks that trigger incremental indexing, writes can be buffered and
flushed periodically rather than on every file change:

```
File edit -> buffer change event -> flush every 30s or on session end
```

The existing freshness debounce (120s) already provides this behavior for full
incremental indexes. The same pattern applies to finding writes if latency ever
becomes a concern.

**3. Read replica for concurrent MCP reads during writes**

KuzuDB allows multiple `READ_ONLY` database instances alongside one `READ_WRITE`
instance. If a long re-index blocks read queries, a read replica can serve MCP tool
responses from the last-known-good state while the write instance re-indexes:

```python
class GraphStore:
    def __init__(self, db_path, read_only=False):
        self._db = kuzu.Database(str(db_path), read_only=read_only)

# MCP server: read replica for tool responses
read_store = GraphStore(db_path, read_only=True)

# Background indexer: write instance
write_store = GraphStore(db_path, read_only=False)
```

This is already partially supported -- the `read_only` parameter exists in GraphStore's
constructor.

**4. Incremental governance-only re-index**

Currently, `scaffold index --incremental` re-runs all pipeline phases on changed files
(structure, parsing, resolution, governance). For finding write-back, only the
governance phase needs to run. Adding a `--governance-only` flag would skip the
expensive parsing/resolution phases when only governance artifacts have changed:

```bash
scaffold index --incremental --governance-only  # Fast: only plans/contracts/learnings
```

### 8.6 Latency Budget Summary

| Operation | Current Latency | Acceptable? | Optimization If Needed |
|---|---|---|---|
| `scaffold_record_finding` (single) | ~10-50ms (MCP overhead + insert) | Yes | Batch multiple findings |
| `scaffold_prepare_review` (read) | ~50-200ms (graph queries) | Yes | Read replica during writes |
| `scaffold index --incremental` (small) | ~2-10s | Yes (async) | Governance-only mode |
| `scaffold index --incremental` (large) | ~30-95s | Yes (async) | Background thread, debounce |
| `scaffold index` (full) | ~95s | Acceptable for setup | Parallel pipeline phases |

None of these latencies are blocking for the proposed architecture. Finding writes are
small and fast. Re-indexing is already async. The graph is not the bottleneck.

---

## 9. What NOT to Do (unchanged from original analysis)

### Do NOT try to replace Claude Code's runtime

AgentScaffold is not a Claude Code competitor. It is a governance and knowledge layer
that generates configuration for agent runtimes. The correct architecture is:

```
AgentScaffold (governance + graph + generation)
        |
        v generates
Claude Code hooks, agents, skills, MCP config
Cursor rules, MCP config
Windsurf rules
```

Trying to implement a full hook runtime, agent spawning engine, or permission system
inside AgentScaffold would duplicate what the hosting platforms already do well.

### Do NOT abandon the MCP-first architecture

AgentScaffold's MCP server is its strongest runtime integration point. All 18 tools
are accessible from any MCP-compatible client. The recommendations above add more
*generation targets* (hooks, agents, skills) but the MCP server remains the primary
runtime interface.

### Do NOT break the multi-platform story

A key differentiator is that AgentScaffold works across Cursor, Claude Code, Windsurf,
and generic LLM setups. Every new feature should generate platform-specific artifacts
from a single source of truth, not lock into Claude Code's proprietary format.

---

## 10. Architecture Vision: Before and After

### Current Architecture (KuzuDB -- archived dependency)

```
scaffold.yaml
    |
    +-- scaffold index --> KuzuDB graph (archived, no upstream maintenance)
    |
    +-- scaffold mcp --> MCP server (18 tools, 2 resources)
    |
    +-- scaffold agents generate --> AGENTS.md (static)
    +-- scaffold agents cursor --> .cursor/rules.md (static)
    +-- scaffold agents claude --> CLAUDE.md (static)
    |
    +-- scaffold validate --> CLI validation (manual)
    |
    +-- scaffold review --> Prompt-injected reviews
```

### Target Architecture (Post-Evolution)

```
scaffold.yaml  (graph.backend: duckpgq)
    |
    +-- scaffold index --> DuckDB + DuckPGQ graph (stable, maintained, native vectors)
    |
    +-- scaffold mcp --> MCP server (20+ tools, 2+ resources)
    |       |
    |       +-- scaffold_record_finding --> Graph write-back (live findings)
    |       +-- scaffold_resolve_finding --> Finding lifecycle management
    |       +-- scaffold_prepare_review --> Reads past findings for overlapping files
    |
    +-- scaffold agents generate --> AGENTS.md (static)
    +-- scaffold agents cursor --> .cursor/rules.md (static)
    +-- scaffold agents claude --> CLAUDE.md (static)
    +-- scaffold agents claude-agents --> .claude/agents/*.md (spawnable)
    +-- scaffold agents skills --> .claude/skills/*/SKILL.md (discoverable)
    +-- scaffold agents hooks --> .claude/settings.json hooks (enforceable)
    |
    +-- scaffold validate --> CLI validation (also generated as hooks)
    |
    +-- scaffold review --> Delegates to spawnable expert agents
    |       |               that read from and write back to graph
    |       +-- Findings feed back into graph for future reviews
    |
    +-- scaffold domains add <external> --> pip/git installable domain packs
```

The key architectural shift is from **generating static instruction documents** to
**generating runtime-composable agent components** -- hooks that enforce, agents that
specialize, skills that teach -- all generated from a single `scaffold.yaml`
configuration. The knowledge graph serves as the **unified memory layer** for all
agents, replacing platform-specific flat-file memory with structured, queryable,
cross-agent institutional knowledge that accumulates through a closed read-write loop.

---

## 11. Quick-Win Opportunities (Can Implement Now)

These require no architectural changes and can be done immediately:

1. **Generate `.claude/agents/` from existing domain prompts** -- The quant architect
   review prompt already exists as a Jinja2 template. Rendering it into a
   `.claude/agents/quant-architect.md` with appropriate frontmatter is a small CLI
   addition.

2. **Add `scaffold_record_finding` MCP tool** -- The ReviewFinding node type, edges,
   and read-path queries already exist in the graph. The write path is a single new
   MCP tool handler that creates a node and wires edges to related files. This is the
   highest-leverage quick win because it closes the read-write loop that makes the
   graph a live memory layer.

3. **Generate SessionStart hook for auto-orient** -- A simple hook in
   `.claude/settings.json` that runs `scaffold orient` on session start.

4. **Generate PostToolUse hook for auto-format/lint** -- Generate a hook that runs
   ruff after Write/Edit operations.

5. **Publish `SKILL.md` files for domain standards** -- The trading traceability
   standard, error handling standard, etc. can be published as SKILL.md files with
   minimal reformatting.

6. **Add `hooks:` section to `scaffold.yaml`** -- Even before implementing the full
   hook engine, add the configuration schema so users can express desired hooks and
   `scaffold agents hooks` can generate platform-specific hook configurations.

---

## 12. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Claude Code hooks API changes | Medium | Medium | Generate from abstraction layer, not direct format |
| SKILL.md standard evolves incompatibly | Low | Low | Standard is maintained by Anthropic and is stable |
| Plugin marketplace fragmentation | Medium | Low | Focus on pip distribution first, marketplace later |
| Over-engineering the hook system | Medium | High | Generate platform hooks, don't build a runtime |
| Domain pack extraction breaks existing users | Low | High | Maintain backward compatibility with built-in packs |
| ReviewFinding write-back noise / low-quality findings | Medium | Medium | Severity filtering; resolved findings drop from context; periodic pruning via `scaffold graph verify` |
| Graph schema version bump for write-back changes | Low | Medium | ReviewFinding schema already exists; no migration needed for initial implementation |
| KuzuDB archived / dependency risk | **Certain** | **High** | **Committed migration to DuckDB + DuckPGQ. Phase 1.5 in roadmap. Abstraction layer enables zero-downtime cutover. See Section 8.3** |
| DuckPGQ query translation bugs | Medium | Medium | Parallel testing harness compares both backends before cutover |
| DuckPGQ feature gaps vs Cypher | Low | Medium | SQL/PGQ covers all current query patterns; test during Phase 1.5 |

---

## 13. Decision Matrix for Prioritization

| Initiative | Value to This Repo | Value to External Users | Effort | Priority |
|---|---|---|---|---|
| Hook generation + graph abstraction | Very High (real-time governance + migration prep) | High | Medium | **P1** |
| **DuckDB + DuckPGQ migration** | **Very High (eliminate dead dependency)** | **Very High** | **Large** | **P1.5** |
| Expert agents from domain packs | High (better reviews) | High | Medium | **P2** |
| ReviewFinding write-back loop | Very High (graph becomes live memory) | High | Medium | **P2.5** |
| SKILL.md standard adoption | Medium (cross-tool) | Very High | Medium | **P3** |
| External plugin packaging | Low (single repo) | Very High | Large | **P4** |
| LSP integration | Low (graph covers this) | Medium | Large | **P5** |

---

## 14. Conclusion

AgentScaffold and Claude Code are complementary, not competing. AgentScaffold's
knowledge graph, plan lifecycle governance, and multi-platform generation are
capabilities Claude Code does not have. Claude Code's runtime primitives (hooks,
spawnable agents, progressive-disclosure skills, plugin marketplace) are capabilities
AgentScaffold does not have.

The optimal evolution is to make AgentScaffold a **first-class generator of Claude Code
(and other platform) runtime components**, bridging its governance intelligence into the
runtime where agents actually operate. The knowledge graph informs what hooks to
generate, what agent personas to create, and what skills to surface.

Critically, the knowledge graph should serve as the **unified memory layer** for all
agents, replacing Claude Code's flat-file MEMORY.md with structured, queryable,
cross-agent institutional knowledge. The ReviewFinding node type and its edges already
exist in the graph schema; the missing piece is the MCP write-back tool that lets agents
record findings during live sessions. Closing this read-write loop creates a virtuous
cycle where reviews produce findings, findings inform future reviews, and systemic
patterns emerge from aggregation -- all within the graph, independent of any hosting
platform's memory features.

The graph itself must be migrated from KuzuDB (archived October 2025) to DuckDB +
DuckPGQ. This is not optional -- continuing to build on an abandoned dependency is a
dead-end street. The migration is made safe by introducing a GraphBackend protocol
that allows both engines to coexist, parallel testing to validate query parity, and a
zero-downtime cutover. DuckDB brings long-term stability (dedicated company, MIT
license, stable on-disk format), native vector search (replacing the separate embedding
pipeline), and ecosystem leverage (100+ extensions, Parquet/Arrow integration) that
strengthen the graph layer beyond what KuzuDB offered.

This positions AgentScaffold as the *governance brain* that produces *runtime artifacts*
for any compatible agent platform, with a DuckDB-backed knowledge graph as persistent
institutional memory that transcends individual sessions, individual agents, and
individual platforms.
