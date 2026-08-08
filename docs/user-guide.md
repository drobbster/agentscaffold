# User Guide: Working with an AI Agent Using AgentScaffold

This guide documents proven interaction patterns for human-AI collaboration using the AgentScaffold framework. These patterns were extracted from hundreds of real implementation sessions and represent the most effective ways to communicate with your AI coding agent.

## The Canonical Session Flow

Every plan implementation session follows a predictable arc. Learning this arc makes your sessions faster and more consistent.

```
Open -> Assess -> Branch -> Review -> Gaps Sweep -> Execute -> Steer -> Close Out -> Commit
```

Each phase has specific trigger phrases and expectations. The sections below detail each one.

But first -- if you don't have any plans yet because you're starting a brand new project, read the Greenfield Onboarding section below.

### Canonical Session Flow (NL + MCP Variant)

If MCP is configured and indexed, you can run the same lifecycle with less command
choreography. Instead of naming each tool, describe the outcome:

| Phase | Command-Heavy Directive | NL + MCP Directive |
|-------|-------------------------|--------------------|
| Open | "Run review brief for plan 042" | "Let's prepare to review plan 042 with evidence." |
| Assess | "Run staleness check" | "Is this plan stale after recent architecture changes?" |
| Review | "Run critique + expansion + domain review" | "Pressure-test this plan and surface edge cases before implementation." |
| Gaps Sweep | "Re-run all review outputs and list gaps" | "Do a full second-pass gap sweep across all review findings." |
| Execute | "Proceed with step-by-step implementation" | "Begin implementation and follow plan steps in order." |
| Close Out | "Run retro and update state files" | "Prepare retro context and complete close-out updates." |

Use explicit commands when you need deterministic verification, reproducible outputs, or
platform fallback.

### The Two-Phase Governed Lifecycle

The canonical flow above is wrapped by two composite lifecycle tools that the agent
should run at the start and end of implementation. They bundle the review and retro
work into a single governed step and write their results to the knowledge graph so
nothing is lost between sessions.

**Phase 1 -- Pre-implementation (`scaffold_begin_plan`).** Triggered by "begin plan X",
"kick off plan X", or "follow the collab protocol to begin plan X". The tool chain runs
orient, then the full pre-review (devil's advocate, expansion, and gap analysis),
auto-writes the challenges and gaps as `ReviewFinding` nodes, and stamps
`Plan.reviewedAt`. The agent then presents the three perspectives, writes the review
summary to the plan appendix, and asks for explicit confirmation before coding.

**Phase 2 -- Post-implementation (`scaffold_complete_plan`).** Triggered by "wrap up
plan X", "close out plan X", or "follow the collab protocol to close plan X". The tool
chain runs the retro, auto-writes retro insights as findings, and optionally records
backlog items. The agent then updates `learnings_tracker.md`, `backlog.md`,
`workflow_state.md`, marks completed steps, and writes the retro summary to the plan
appendix.

**Strict-mode gate.** When `freshness.gate_strict: true` in `scaffold.yaml`,
`scaffold_prepare_implementation` checks that `scaffold_begin_plan` has run
(`Plan.reviewedAt` is set) and defers implementation until the pre-review is complete.

The boundary is deliberate: the lifecycle tools own graph state (findings, backlog
items, review stamps); the agent owns file state (plan appendix, `backlog.md`,
`learnings_tracker.md`, `workflow_state.md`).

---

## Greenfield Onboarding: Starting from Scratch

Not every project starts with a clear architecture. If you just ran `scaffold init` and are staring at blank templates, this section walks you through using your AI agent to discover your system design, define your architecture layers, and create your first plans.

### Step 1: Describe Your Vision

Open your IDE with the agent and describe what you want to build in plain language. Don't worry about architecture layers, module boundaries, or technical specifics yet. Focus on the *what* and the *why*.

```
I want to build a personal finance dashboard that aggregates
data from multiple bank accounts, categorizes transactions,
and shows spending trends over time. Eventually I want to add
budget alerts and maybe a mobile app.
```

Or more technically:

```
I'm building an internal tool that ingests sensor data from
IoT devices, runs anomaly detection, and sends alerts to a
Slack channel. We have about 200 devices sending data every
30 seconds.
```

The agent will ask clarifying questions about scale, users, data sources, and constraints. Answer honestly -- including "I don't know yet."

### Step 2: Architecture Discovery Session

Once the agent understands your vision, ask it to help define the architecture:

```
based on what I've described, help me define my system
architecture layers. what would a clean separation of concerns
look like for this project?
```

The agent will propose layers based on your domain. For example, a typical web application might get:

| Layer | Purpose |
|-------|---------|
| Layer 1: Data Ingestion | External APIs, data feeds, storage |
| Layer 2: Business Logic | Rules, calculations, domain models |
| Layer 3: Presentation | UI, API endpoints, notifications |

A more complex system might need 4-6 layers. The right number depends on your project's complexity and your team's experience. There is no universally correct answer.

**Key questions to ask during this conversation:**

```
is this too many layers for the scope of this project?
```

```
what would happen if we combined layers 2 and 3?
```

```
where does authentication fit in this model?
```

```
what are the interfaces between these layers? what data
flows between them?
```

### Step 3: Fill In the System Architecture Document

Once you agree on layers, ask the agent to populate the generated template:

```
lets fill in the system architecture document with the layers
we just discussed. for each layer, describe the current state
as "not started" and list the components we identified.
```

The system architecture document lives at `docs/ai/system_architecture.md`. It was generated with blank layer stubs when you ran `scaffold init`. Now you're filling it in with real content.

If you chose 3 layers during init but your discovery session produced 5, update `scaffold.yaml` and regenerate:

```bash
# Edit scaffold.yaml: change architecture_layers from 3 to 5
scaffold agents generate
```

### Step 4: Create a Product Vision and Roadmap

Before diving into plans, establish the big picture:

```
based on our architecture discussion, help me create a product
vision document. what are the key milestones to get from zero
to a working MVP?
```

The agent will draft content for `docs/ai/product_vision.md` and `docs/ai/strategy_roadmap.md`. These become the strategic guardrails for all future plans.

### Step 5: Create Your First Plans

Now you're ready to create plans. Start with the foundation:

```
what should our first 3-5 plans be to get the foundation
layers working? lets start with the most critical path.
```

For each plan the agent suggests:

```bash
scaffold plan create setup-database --type feature
scaffold plan create data-ingestion-pipeline --type feature
scaffold plan create core-domain-models --type feature
```

Then review and implement each one using the canonical session flow described in the rest of this guide.

### Step 6: Iterate on the Architecture

Your initial architecture is a hypothesis. As you implement plans, you'll discover things that don't fit. This is expected and healthy.

**When something doesn't fit:**

```
this component doesn't seem to belong in layer 2. it feels
more like a cross-cutting concern. should we restructure?
```

**When you need a new layer:**

```
we keep adding things to layer 3 that don't really belong
together. should we split it into two layers?
```

**When a layer is overkill:**

```
layer 4 only has one component and it's trivial. should we
merge it into layer 3?
```

The agent will propose changes. If they affect the architecture document, the agent should add an entry to `docs/ai/architectural_design_changelog.md` and ask for your approval before modifying the architecture.

### Quick Start Paths

Depending on your project type, here are suggested starting configurations:

| Project Type | Layers | Domain Pack | Rigor | First Plans |
|-------------|--------|-------------|-------|-------------|
| Simple web app | 3 | webapp | minimal | DB setup, API routes, UI shell |
| Data pipeline | 3-4 | data-engineering | standard | Ingestion, transforms, storage, scheduling |
| ML/AI project | 4-5 | mlops | standard | Data prep, training pipeline, evaluation, serving |
| Trading system | 5-6 | trading | strict | Market data, strategy engine, risk, backtesting, execution |
| API service | 3 | api-services | standard | Schema design, core endpoints, auth |
| Mobile app | 3-4 | mobile | standard | Data layer, business logic, UI components |
| Side project / prototype | 2-3 | (none) | minimal | Core feature, basic UI |

These are starting points, not prescriptions. Your agent will help you adjust as the project evolves.

### Common Onboarding Mistakes

**Trying to define everything upfront.** You don't need a perfect architecture before writing code. Start with 3 layers and let them evolve. The framework's changelog and retrospective system is designed to track architectural evolution.

**Choosing too many layers for a simple project.** A personal blog doesn't need 6 layers. If your project is small, 2-3 layers is fine. You can always add more later.

**Skipping the architecture document.** Even for prototypes, a lightweight architecture document prevents the agent from making contradictory design decisions across sessions. It takes 10 minutes and saves hours.

**Not installing a domain pack.** Domain packs add review prompts that catch domain-specific mistakes. A `webapp` pack catches accessibility and performance issues. A `data-engineering` pack catches schema evolution risks. Pick the one closest to your project even if it's not a perfect fit.

---

## Phase 1: Opening a Session

### Pattern: Plan Pull-Up with Protocol Reference

The most effective way to start an implementation session is to name the plan and invoke the collaboration protocol in a single sentence. This tells the agent exactly what to do: read the plan, check its status, verify dependencies, and begin the review sequence.

**Examples:**

```
lets bring up plan 015 and review it following the collaboration protocol
```

```
lets review plan 042 using the collab protocols
```

```
prepare to implement plan 008 following the collab protocols,
and create a new feature branch for it
```

**When to use:** Start of every plan implementation session.

**What the agent does:** Reads the plan file, checks workflow_state.md for blockers, verifies dependencies are complete, then begins pre-implementation reviews.

### Pattern: Status Inquiry Opener

When resuming a session or checking where things stand, open with a targeted status question.

**Examples:**

```
plan 089 phase 9 is incomplete yes?
```

```
where are we on plan 110?
```

```
I want to work on plan 118, but I am working on plan 108 with
a different agent. Can we keep our work separate?
```

### Pattern: Operational Triage Opener

Not all sessions are about plan implementation. When something is broken or you need to investigate an issue, open directly with the problem.

**Examples:**

```
it looks like our infrastructure is down. will you redeploy it
```

```
I need a complete review of what plans remain and what's in our backlog
```

### Pattern: Handoff Summary Opener

When resuming work from a previous session (especially if background processes are running), provide a structured handoff.

**Example:**

```
Handoff Summary:
- Current State: Active flow running on PID 10099
- Last completed: Steps 1-14 of Plan 120
- Known issues: CI timeout on integration tests
- Next steps: Complete Step 15 (model evaluation), then run retro
```

**When to use:** When starting a new chat session that continues work from a prior session. Especially important when background jobs (training, pipelines) are running.

---

## Phase 2: Staleness Assessment

Plans can go stale if they were written weeks ago and the codebase has changed. Always check.

**Examples:**

```
assess this plan to see if it needs to be revised due to all
our system architectural changes
```

```
please read the system architecture doc to see if we need to
add anything to this plan after gathering context from that doc
```

```
check the date of its creation to see if it needs to be
refactored for architectural changes
```

**When to use:** Any time you are picking up a plan that was written more than a week ago, or after significant architectural work has been completed.

---

## Phase 3: Branch Management

Be explicit about branch state. The agent needs to know where it is in the git tree.

**Examples:**

```
create a new branch for this work. we are on staging and its up to date
```

```
also create a feature branch for this work. we are on staging
and its up to date. then proceed
```

```
can we change the name of the branch to 105-rl-policy-optimization
since it was improperly named
```

**Key pattern:** Always state your current branch and whether it is up to date. This prevents the agent from making assumptions about git state.

---

## Phase 4: Pre-Implementation Reviews

The collaboration protocol triggers three reviews before execution: devil's advocate, expansion, and (if a domain pack is installed) a domain-specific review. Sometimes the agent tries to skip these.

### Enforcing Reviews

If the agent jumps ahead to implementation, pull it back:

```
hold on. we have to do the pre-reviews
```

```
pre reviews first.
```

```
you normally share all three reviews with me, and we confirm
the additional todos. why did you change your approach?
```

### Engaging with Review Findings

Don't just rubber-stamp reviews. Probe the findings:

```
talk to me about the alternative approaches
```

```
lets discuss these. I'm not sure if I agree.
```

```
I approve. but explain to me what ADX 20-25 is?
```

**Tip:** Ask "why" questions during reviews. This is where you catch design mistakes before they become code.

---

## Phase 5: The Gaps Sweep

This is the most distinctive and important pattern. After the agent delivers its reviews, demand a comprehensive sweep across all concern categories. Do not skip this step -- it consistently catches issues that individual reviews miss.

### The Formula

Use a comprehensive list of concern categories:

```
make sure we have ALL gaps, mitigations, future regret items,
silent failure modes, edge cases, error conditions, config gaps,
monitoring gaps, integration gaps, security gaps, interface
consumer items, state synchronization issues, failure modes,
and data corruption mitigations. EVERYTHING.
```

### Variations

```
rereview all three reviews for all gaps, mitigations,
recommendations, error conditions, edge cases, future regret
items, and update your todo list accordingly
```

```
circle back to the reviews and make sure we have all gaps,
mitigations, future regret items, silent failure modes, edge
cases, error conditions, etc.
```

### The Compound Gaps Directive

The most effective version combines the gaps sweep with plan updates and execution approval:

```
rereview the 3 reviews. make sure all gaps, mitigations and
recommendations are added to your todo list. including future
regret solutions, silent failures, integration gaps, edge cases
and errors, config gaps, monitoring and observability
recommendations. EVERYTHING. document the reviews in the plan
appendix, and proceed.
```

**Why this works:** The agent's initial reviews are good but not exhaustive. The gaps sweep forces a second pass that catches cross-cutting concerns the individual reviews missed. The word "EVERYTHING" signals to the agent that this is not a cursory re-check.

---

## Phase 6: Execution Triggers

After reviews are accepted and the plan is updated, trigger implementation with short, decisive phrases.

**Examples:**

```
ok proceed
```

```
begin implementation
```

```
build!
```

```
ok begin implementation following the collab protocol
```

```
yes please apply now, then begin implementation
```

For multi-phase plans, explicitly manage phase transitions:

```
proceed with step 2 when complete
```

```
is phase A complete then? do we move on to phase B?
```

```
yes continue with phase 4
```

---

## Phase 7: Steering During Execution

Execution is not hands-off. Actively steer the agent with domain knowledge, quality challenges, and boundary enforcement.

### Domain Knowledge Injection

Provide context the agent cannot know from the codebase alone:

```
we have data already backfilled from vendor X
```

```
All production data should be coming from the feast feature store
```

```
we are only paying for X data from Y provider
```

```
oh wait the market isn't open
```

### Quality Challenges

Challenge the agent when something looks wrong:

```
are you sure you are following the same implementation pattern?
```

```
no I want you to check your code, and make sure it follows the
same design pattern as the others. they are currently running
and I don't want you to mess it up
```

```
I want complete work not lightweight
```

```
why is this called phase6_meta.yaml? phase 6 seems inappropriate
```

### Boundary Enforcement

Set hard limits when the agent oversteps:

```
hold on you cant push without my permission
```

```
hey! you are not to change the system architecture document
```

```
we are not executing any plans now. only revising them
```

```
dont commit changes yet
```

### Wiring Verification

The most important validation question during execution:

```
did you stub anything out or is everything wired up?
```

```
please double check everything is wired up correctly
```

```
did you run them? is everything wired up?
```

### Test Verification

Probe whether real tests were run, not just written:

```
have you run integration tests and/or e2e tests on these new features?
```

```
did you run any integration tests? with real data?
```

```
yes. but first did you double check if everything is wired up
correctly? integration or smoke tests?
```

---

## Phase 8: The Close-Out Sequence

After implementation is complete, run a multi-step close-out. This is highly formulaic and should be followed every time.

### Trigger the Post-Implementation Review and Retrospective

```
ok lets do the post implementation review and retro
```

```
can we do the post implementation review and the retro per the
collab protocols
```

### The Full Close-Out Directive

The most effective close-out combines everything in one message:

```
lets do the post implementation review and retro. add them to
the plan appendix. add learnings from the retro to the learnings
tracker. add any backlog items to the backlog. update workflow
state and plan completion log.
```

### State Management Checklist

After the retro, verify all state files are updated:

```
please update the status of this plan in the workflow state,
plan completion log, and changelog if necessary
```

```
did you move completed backlog items to the backlog archive?
```

```
is all the documentation updated?
```

---

## Phase 9: Commit and Housekeeping

Short, directive commit requests:

```
lets commit all this work
```

```
commit all changes
```

```
please commit your changes if you haven't already
```

Combine with housekeeping:

```
move completed backlog items to the backlog archive, and commit changes
```

---

## Additional Patterns

### Deep Questioning

Don't hesitate to ask the agent to explain concepts or design decisions:

```
what will this plan provide us in terms of data? also what is CUSIP?
```

```
doesn't the RL agent use the strategies? Am I not understanding
the way the system works?
```

```
what does a best in class trading system architecture look like
and how does it compare to what we currently have?
```

**When to use:** Whenever you don't fully understand a design choice or domain concept. The agent should explain, not just build.

### Error and Incident Handling

Report errors with specific output and challenge assumptions:

```
I ran [command] and am seeing many failures in the terminal.
is that ok?
```

```
that command you gave me doesn't work. can you investigate?
```

```
hold on... when the pipeline runs daily, it can't be pulling
90 days because that would violate the 1 month historical limit
```

### Side Quests and Returns

Sometimes you need to investigate something tangential. Be explicit about diverging and returning:

```
sure lets check the training code to see what triggers promotion
to the model registry. but don't take action.
```

Then later:

```
excellent. thank you. now lets return to the plan and run our
post implementation review and retro
```

### Process Improvement

When you notice the framework itself could be better, capture it immediately:

```
why didn't you catch these gaps when implementing the plan? what
didn't we do well? is there something we can change in our
planning process to mitigate these issues on future plans?
```

```
can we update the collab protocol to make sure before we begin
implementing a new plan we review the system architecture doc
```

```
lets review the learnings tracker to see what hasn't been
evaluated for continuous process improvement
```

### Backlog Management

Actively manage backlog items during and between sessions:

```
tell me about these backlog items. are any of them blocked?
which ones can be done now?
```

```
can we do B-049-9, B-049-10, B-049-11, and B-049-12 right now
and update the status for them in the backlog
```

```
great. lets do B-139-2 and B-141-M7 now. And mark B-139-3 complete.
```

### Study and Experiment Management

When implementation reveals the need for empirical validation:

```
once you're done implementing this plan, lets discuss the
functionality enhancements and whether or not we need to set up a study
```

```
lets also create another study to explore this approach
```

```
the flow has completed. lets review the findings
```

---

## Migration Guide for Governance-First Users

If you used AgentScaffold before knowledge graph/MCP integration, the safest shift is:

1. **Hybrid first**: use NL prompts for orchestration, keep CLI verification explicit.
2. **Verify behavior**: confirm the agent is routing to MCP context/review tools first.
3. **Keep rigor fixed**: pre-reviews, gap sweep, validation, retro, and state updates stay mandatory.

Phase-by-phase translation:

| Old Structural Pattern | NL Prompt Pattern | Expected Tool Family |
|------------------------|-------------------|----------------------|
| "run review brief/challenges for plan X" | "prepare to review plan X with evidence" | composite review tools |
| "run staleness check on plan X" | "is plan X stale after recent changes?" | staleness/validation tools |
| "run impact on file/symbol Y" | "what is the blast radius of Y?" | impact/context tools |
| "gather ADR/spike/study history" | "show the decision chain behind this plan" | decision context tools |
| "run retro prep and findings pull" | "prepare retro context for this plan" | retro/studies tools |

Fallback and override guardrails:

- If MCP is unavailable, fall back to direct read/search and keep governance sequence intact.
- If graph might be stale, run `scaffold index --incremental` before continuing.
- Keep explicit validation commands (`scaffold validate`, `scaffold graph verify`) before completion.

The steps above cover the full migration path. Governance rigor is preserved
throughout -- the shift is from explicit CLI commands to conversational intent.

---

## NL Intent Routing Reference

AgentScaffold's MCP server maps natural language trigger phrases to specific tools.
When you use one of the phrases below in chat, the agent should route to the corresponding
MCP tool. Use this table to verify routing behavior, write CLAUDE.md / AGENTS.md rules,
or understand what context each workflow produces.

| NL Trigger Phrase | Routes To | What It Returns |
|-------------------|-----------|----------------|
| "review plan X" / "critique plan X" / "devil's advocate on plan X" / "pressure-test plan X" | `scaffold_prepare_review` | Brief + adversarial challenges + gap analysis + governing ADRs + spikes |
| "implement plan X" / "start plan X" / "begin building plan X" / "approved to go on plan X" | `scaffold_prepare_implementation` | Dependency brief + blast radius per file + contract obligations + consumer audit |
| "compare plan X and plan Y" / "do plans X and Y overlap" / "check for conflicts between X and Y" | `scaffold_compare_plans` | Shared files, supersession candidates, conflict summary |
| "is plan X stale" / "is plan X still valid" / "has anything changed since plan X" | `scaffold_staleness_check` | Overlapping completions, missing files, changed dependencies, contradicting studies |
| "rewrite plan X" / "update plan X" / "refresh plan X with current state" | `scaffold_prepare_rewrite` | Staleness analysis + new dependency landscape + new contracts since writing |
| "retro on plan X" / "post-implementation review" / "retrospective for plan X" | `scaffold_prepare_retro` | Verification results + retro enrichment + modification frequency + related studies |
| "where did we leave off" / "what's the current state" / "what's blocked" / "what are the next steps" | `scaffold_orient` | Codebase stats + recent plans + hot files + active ADRs + workflow state |
| "any studies on X" / "experiments related to X" / "show me studies about X" | `scaffold_find_studies` | Studies filtered by topic keyword or outcome |
| "prior experiments for plan X" / "has this been tested" / "what experiments relate to plan X" | `scaffold_prior_experiments` | Directly referenced studies + tag-matched + file-overlap studies |
| "any ADRs about X" / "what ADR governs X" / "which architecture decision governs X" | `scaffold_find_adrs` | ADRs filtered by topic keyword or status |
| "decision history for plan X" / "trace the decisions for plan X" / "what ADR governs plan X" | `scaffold_decision_context` | Governing ADRs + validation spikes + supporting studies + dependency status |
| "record finding" / "log this review finding" / "I found an issue in plan X" | `scaffold_record_finding` | Creates ReviewFinding node in graph, linked to plan + files + functions |
| "mark finding resolved" / "resolve this finding" / "fix has been addressed" | `scaffold_resolve_finding` | Updates finding status to resolved; retained in graph for audit |
| "context for symbol X" / "what calls X" / "what does X depend on" | `scaffold_context` | Full symbol context: definition, callers, callees, layer, plan history, contracts |
| "blast radius for file X" / "who imports X" / "impact of changing X" | `scaffold_impact` | Transitive consumers, affected layers, governance context |
| "search for X" / "find code related to X" | `scaffold_search` | Hybrid search results (keyword + semantic, configurable mode) |
| "what did we decide about X" / "recall prior work on X" / "have we discussed X before" | `scaffold_recall_governance` | Semantic recall across plans, findings, learnings, ADRs, studies, spikes, backlog |
| "begin plan X" / "kick off plan X" / "follow the collab protocol to begin plan X" | `scaffold_begin_plan` | Phase 1 lifecycle: orient + full pre-review, writes findings, stamps `reviewedAt`, returns a proceed prompt |
| "wrap up plan X" / "close out plan X" / "follow the collab protocol to close plan X" | `scaffold_complete_plan` | Phase 2 lifecycle: retro, writes retro findings, optional backlog items, returns completion checklist |
| "record all findings" / "log these findings" / "save all review findings" | `scaffold_record_findings_batch` | Creates multiple ReviewFinding nodes in one transaction |
| "add backlog item" / "record backlog item" / "track backlog item" | `scaffold_record_backlog_item` | Creates one or more BacklogItem nodes (graph-side, additive to `backlog.md`) |
| "resolve backlog item" / "mark backlog item done" / "archive backlog item" | `scaffold_resolve_backlog_item` | Marks a BacklogItem archived; retained in graph for retrospective queries |

### Configuring Intent Routing in CLAUDE.md

If your project uses Claude Code, generate a routing policy file:

```bash
scaffold agents claude
```

This creates or updates `CLAUDE.md` with the full intent map. If you already have `CLAUDE.md`
content, merge or append the generated policy. The routing rules are what cause the agent
to call these tools automatically when you use trigger phrases.

For Cursor, the routing policy goes into `.cursor/rules/agentscaffold.mdc`:

```bash
scaffold agents cursor
```

---

## Knowledge Graph: Codebase Intelligence

AgentScaffold can build a knowledge graph of your codebase using `scaffold index`. This graph powers several features: auto-enriched templates, graph-backed reviews, MCP tool integration, and a living Codebase Intelligence section in AGENTS.md.

### Building the Graph

```bash
scaffold index                 # Full index from current directory
scaffold index /path/to/repo   # Index a specific path
scaffold index --incremental   # Only re-index changed files (fast)
scaffold index --embeddings    # Generate code embeddings for semantic search
scaffold index --audit         # Log all resolution decisions
```

The graph is a DuckDB + DuckPGQ database stored at `.scaffold/graph.duckdb` by default (configurable in `scaffold.yaml` under `graph.db_path`). It requires the `[graph]` optional dependency:

```bash
pip install agentscaffold[graph]          # Python, JS, TS grammars
pip install agentscaffold[graph-go]       # Add Go support
pip install agentscaffold[graph-rust]     # Add Rust support
pip install agentscaffold[graph-java]     # Add Java support
pip install agentscaffold[graph-c]        # Add C support
pip install agentscaffold[graph-cpp]      # Add C++ support
pip install agentscaffold[graph-all-languages]  # All language grammars
pip install agentscaffold[all]            # Everything
```

### Multi-Project Workspaces

If you work across several repos that share one graph, register them as a workspace.
A `workspace.yaml` at the workspace root lists the projects; manage it with:

```bash
scaffold workspace onboard ../market-data-service --name market-data-service
scaffold workspace list
```

Once registered, reads default to the **current** project (resolved from the working
directory), so plan numbers and file paths from a sibling project never leak into your
results. To look elsewhere, pass `--project <name>`; to federate across all of them,
pass `--all-projects` (federated results carry a `project` provenance field):

```bash
scaffold graph search "symbol normalization" --project market-data-service
scaffold graph search "symbol normalization" --all-projects
scaffold graph duplicates --table Function   # cross-project near-duplicate definitions
```

Scoping is a relevance boundary within one trust domain, not a security boundary. When
unsure which project you are in, run `scaffold workspace list`. Full semantics are in
[Configuration](configuration.md). A lone repo (no multi-project `workspace.yaml`) is
unaffected — everything is implicitly the single current project.

### Incremental Indexing

After the first full index, use `--incremental` for fast re-indexing:

```bash
scaffold index --incremental
```

Incremental mode keeps per-edit work proportional to what actually changed:

- **`(mtime, size)` prefilter.** Files whose modification time and size match the
  stored metadata are skipped without re-hashing. Only candidates that look changed
  are SHA-256 hashed to confirm.
- **Empty-changeset early exit.** If nothing changed, the run exits as an explicit
  no-op instead of walking the whole graph.
- **Scoped re-resolution.** Import, call, and config-reference edges are recomputed
  only for changed files plus their direct importers — not the entire repo. Community
  detection is skipped on content-only edits by default.

The changeset output shows exactly what changed:

```
Incremental index -- computing changeset...
  3 added, 2 modified, 1 deleted, 847 unchanged
```

On a large codebase where only a handful of files changed, this is dramatically faster
than a full re-index. Tuning knobs (`incremental_community_refresh`,
`incremental_min_interval_seconds`) are documented in
[Configuration](configuration.md#incremental-index-policy).

### Async Freshness for MCP (Large-Repo UX)

For large repositories, even incremental re-indexing can still take too long to run
inline with tool calls. Async freshness mode separates freshness checks from refresh work:

- Request path performs a cheap freshness oracle check.
- Eligible composite tools schedule background incremental refreshes.
- Debounce and single-flight locking avoid refresh storms.
- Responses include freshness state so the agent can communicate confidence.

Enable in `scaffold.yaml`:

```yaml
freshness:
  async_enabled: true
  debounce_seconds: 120
  gate_strict: false
  background_queue_enabled: true
```

If you need strict lifecycle control, set `gate_strict: true` so gate transitions defer
when graph freshness is stale or unknown.

### Async Embeddings (Semantic Freshness)

Structural freshness (above) and embedding freshness are **two separate lanes**. The
`freshness.*` settings keep the structural graph current; `graph.async_embeddings`
controls whether embedding vectors are refreshed in the background so semantic and
hybrid search stay fresh without blocking the per-edit hot path.

```yaml
graph:
  async_embeddings: "off"        # off | idle | interval | commit
  embedding_min_interval_seconds: 0
```

- `off` (default): no background embedding work, and the embedding model is never
  loaded. Historical behavior is preserved.
- `idle` / `interval` / `commit`: opt into background refresh. The MCP server can then
  schedule a single-flight, debounced embedding reconcile when retrieval is degraded
  (for example, no embeddings are indexed yet) and the structural index lock is idle.
  For the `commit` policy, generated `post-commit` / `post-merge` git hooks request a
  non-blocking reconcile.

See [Configuration](configuration.md#incremental-index-policy) for the full policy
semantics. If you only ever index from the CLI, leaving this `off` and running
`scaffold index --embeddings` when you want to refresh embeddings is perfectly fine.

### Supported Languages

Tree-sitter grammars are used for parsing. The following languages extract functions, classes, methods, and interfaces:

| Language | Functions | Classes | Methods | Interfaces | Import/Call Resolution |
|----------|-----------|---------|---------|------------|----------------------|
| Python | Yes | Yes | Yes | - | Yes |
| TypeScript | Yes | Yes | Yes | Yes | Yes |
| JavaScript | Yes | Yes | Yes | - | Yes |
| Go | Yes | Structs | Yes | Yes | Partial |
| Rust | Yes | Structs | Impl methods | Traits | - |
| Java | - | Yes | Yes | Yes | Partial |
| C | Yes | Structs | - | - | - |
| C++ | Yes | Yes | Yes | - | - |

Languages without import/call resolution still get full structural indexing (definitions, edges to files, embeddings, community membership).

### Cross-Session Memory

AgentScaffold tracks coding sessions to provide context continuity:

```bash
# Start a session — positional shorthand or full options
scaffold session start "Implementing data pipeline"
scaffold session start --plan 42 --summary "Implementing data pipeline"

# Record which files you modified (usually done automatically)
# The session tracks modifications via SESSION_MODIFIED edges

# End the session — omit ID to auto-end the most recent session
scaffold session end --summary "Completed phase 1"
scaffold session end abc123 --summary "Completed phase 1"   # explicit ID

# List recent sessions
scaffold session list

# View cross-session context (hot files, recent plans)
scaffold session context
```

Session context is automatically injected into templates when available, showing agents which files have been frequently modified across sessions and which plans are actively being worked on.

### What Gets Indexed

The graph captures six layers of information:

| Phase | What It Captures |
|-------|-----------------|
| Structure | Files, folders, CONTAINS edges, content hashes, languages |
| Parsing | Functions, classes, methods, interfaces, DEFINES edges (via Tree-sitter) |
| Resolution | Import edges (IMPORTS), call edges (CALLS) with confidence scores |
| Governance | Plans, contracts, learnings, review findings, IMPACTS/REFERENCES edges |
| Communities | Leiden algorithm clusters of tightly coupled files |
| Embeddings | Vector embeddings for semantic similarity search (optional) |

### Querying the Graph

```bash
scaffold graph stats                        # Health dashboard
scaffold graph query "SELECT count(*) FROM File"  # Raw SQL
scaffold graph verify                       # Spot-check accuracy
scaffold graph verify --deep                # Re-parse sample files
```

### Auto-Enriched Templates

When the graph is available, two commands auto-inject graph context:

**`scaffold plan create`** -- New plans include a "Codebase Context" section showing:
- Hot spots (most-modified files) that might be affected
- Volatile modules (3+ plans) that warrant stability review

**`scaffold agents generate`** -- AGENTS.md includes a Codebase Intelligence section with:
- File/function/class/edge counts
- Architecture layer map
- Hot spots and volatile modules
- Active contracts and versions
- Graph command reference

Both degrade gracefully -- without a graph, output is identical to before.

### Dialectic Engine: Graph-Powered Reviews

The Dialectic Engine generates evidence-based review context from the knowledge graph. Instead of relying on an LLM to speculate about risks, it queries actual codebase data.

**Review commands:**

```bash
scaffold review brief 42         # Pre-review brief: plan summary, impacted files,
                                 # related plans, learnings, contracts
scaffold review challenges 42    # Adversarial challenges grounded in graph evidence
scaffold review gaps 42          # Gap analysis: missing consumers, integration points,
                                 # test coverage holes
scaffold review verify 42        # Post-implementation compliance check
scaffold review retro 42         # Retrospective enrichment: volatility, patterns,
                                 # complexity changes
scaffold review history src/foo  # All findings and plan history for a file
```

**Template mode** -- generates the full review prompt pre-populated with evidence:

```bash
scaffold review challenges 42 --template   # Full devil's advocate prompt + evidence
scaffold review gaps 42 --template         # Full expansion prompt + evidence
scaffold review retro 42 --template        # Full retrospective prompt + evidence
```

This is particularly useful for agents: instead of running the review tool and then composing the prompt manually, `--template` gives a ready-to-use prompt.

### Using Reviews in Sessions

Integrate graph-powered reviews into your session flow:

```
lets bring up plan 042. run the graph review brief and challenges
before we do the devil's advocate review
```

```
generate the expansion review for plan 042 with graph evidence
```

```
we just finished plan 042. run the retro enrichment and use it
in our retrospective discussion
```

The graph evidence makes reviews more concrete. Instead of "this plan might affect downstream consumers," the challenges say "src/data/router.py has 5 direct importers that are not in your File Impact Map."

### Hybrid Search

Search across code definitions using natural language. Three modes are available:

```bash
# Hybrid search (keyword + semantic -- default)
scaffold graph search "data routing strategy"

# Pure structural search (name/path matching)
scaffold graph search "router" --mode keyword

# Pure semantic search (vector similarity)
scaffold graph search "how is data loaded" --mode semantic

# Limit results
scaffold graph search "risk" --top 5

# Restrict to a single table
scaffold graph search "base class" --table Class
```

Hybrid mode uses **reciprocal rank fusion** (RRF) to merge structural and semantic results, giving the best of both worlds: exact name matches from graph traversal and conceptual matches from embeddings.

Semantic and hybrid search require the `[search]` extra:

```bash
pip install "agentscaffold[search]"
```

Then generate embeddings during indexing:

```bash
scaffold index --embeddings
```

This uses `all-MiniLM-L6-v2` (384-dim) from sentence-transformers. Each function, class, method, and file node gets an embedding vector stored in the graph.

### Module Communities

Community detection uses the **Leiden algorithm** to cluster tightly coupled files based on import and call edges:

```bash
# View detected communities
scaffold graph communities
```

Communities are detected automatically during indexing. The output shows:
- Community label (derived from common path prefixes)
- File count and function count per community
- Member files (preview)

This helps identify natural module boundaries, tightly coupled clusters that should be refactored together, and architectural groupings.

### MCP Integration

When running the MCP server (`scaffold mcp`), 26 tools are available to AI agents across three groups.

**Graph Intelligence Tools** — direct codebase queries:

| Tool | What It Does |
|------|-------------|
| `scaffold_stats` | Codebase health dashboard (files, functions, edges, governance) |
| `scaffold_query` | Execute raw SQL queries against the knowledge graph |
| `scaffold_search` | Hybrid search (keyword, semantic, or hybrid mode) |
| `scaffold_recall_governance` | Semantic recall across plans, findings, learnings, ADRs, studies, spikes, backlog |
| `scaffold_context` | Full context for a symbol (definition, callers, layer, plan history) |
| `scaffold_impact` | Blast radius analysis for a file or symbol |
| `scaffold_validate` | Validation checks (layers, contracts, staleness) — see [The `layers` check](#the-layers-check) |
| `scaffold_review_context` | Low-level review context (brief, challenges, gaps, verify, retro) for a plan |

**Governance & Review Tools** — composite workflows triggered by natural language:

| Tool | NL Trigger | What It Does |
|------|-----------|-------------|
| `scaffold_prepare_review` | "review plan X" / "critique plan X" / "devil's advocate on plan X" | Full pre-review package: brief, gap analysis, adversarial challenges, governing ADRs, spikes |
| `scaffold_prepare_implementation` | "implement plan X" / "start plan X" / "begin building plan X" | Implementation readiness: dependency brief, per-file blast radius, contract obligations, consumer audit |
| `scaffold_compare_plans` | "compare plan X and Y" / "do plans X and Y overlap" | Overlap and conflict detection between two plans |
| `scaffold_staleness_check` | "is plan X stale" / "is plan X still valid" | Checks overlapping completions, missing files, changed dependencies, contradicting studies |
| `scaffold_prepare_rewrite` | "rewrite plan X" / "update plan X" / "refresh plan X" | Staleness check + new dependency landscape + contracts added since plan was written |
| `scaffold_prepare_retro` | "retro on plan X" / "post-implementation review" | Retrospective context: verification results, retro enrichment, modification frequency, related studies |
| `scaffold_orient` | "where did we leave off" / "what's the current state" / "what's blocked" | Session-start orientation: codebase stats, recent plans, hot files, workflow state, blockers, next steps |
| `scaffold_find_studies` | "any studies on X" / "experiments related to X" | Search studies and A/B tests by topic or outcome |
| `scaffold_prior_experiments` | "prior experiments for plan X" / "has this been tested" | Find experiments linked to a plan via direct reference, tag overlap, or file overlap |
| `scaffold_find_adrs` | "any ADRs about X" / "what ADR governs X" | Search architectural decision records by topic or status |
| `scaffold_decision_context` | "decision history for plan X" / "trace the decisions for plan X" | Full decision chain: governing ADRs, validation spikes, supporting studies, dependency status |
| `scaffold_record_finding` | "record finding" / "log this review finding" | Create a ReviewFinding node linked to a plan, files, and functions — persists across sessions |
| `scaffold_resolve_finding` | "mark finding resolved" / "resolve this finding" | Mark a finding as resolved; retained in graph for audit trail |
| `scaffold_record_findings_batch` | "record all findings" / "log these findings" | Create multiple ReviewFinding nodes in a single transaction (efficient for post-review batches) |
| `scaffold_record_backlog_item` | "add backlog item" / "track backlog item" | Create one or more BacklogItem nodes (additive to `backlog.md`; enables backlog queries in orient/prepare_review) |
| `scaffold_resolve_backlog_item` | "resolve backlog item" / "archive backlog item" | Mark a BacklogItem archived; retained in graph for retrospective queries |

**Governed Lifecycle Tools** — the two-phase chain that wraps implementation:

| Tool | NL Trigger | What It Does |
|------|-----------|-------------|
| `scaffold_begin_plan` | "begin plan X" / "kick off plan X" | Phase 1: orient + full pre-review, auto-writes findings, stamps `Plan.reviewedAt`, returns a proceed prompt |
| `scaffold_complete_plan` | "wrap up plan X" / "close out plan X" | Phase 2: retro, auto-writes retro findings, optional backlog items, returns a completion checklist |

The MCP tools return both structured JSON and formatted markdown, so agents can parse the data programmatically or display it directly.

### The `layers` check

`scaffold_validate` with `check="layers"` enforces the layering rule your
`AGENTS.md` states: a component consumes the layer directly below it and does not
bypass intermediate ones. It reads the numbered layers and their path patterns
from `docs/ai/system_architecture.md`, maps files to layers, and examines every
import that crosses a layer boundary.

Two shapes are reported. An **inversion** runs upward — a lower layer importing a
higher one, so the foundation depends on what is built on top of it. A **skip**
reaches past an intermediate layer, which is the bypass the rule names directly.
Imports inside one layer, and imports into the layer immediately below, are
permitted and never flagged.

**A third answer: `not_evaluable`.** This is the one to understand, because it is
common and it is not a failure. The check needs both halves in the same graph:
layer definitions from the architecture document, and code files whose paths match
those layers' patterns. If either is missing it returns `not_evaluable` with a
reason and a remediation, rather than reporting zero violations.

That distinction is deliberate. A graph containing no layered files would produce
an empty violation list, and "no violations found" is indistinguishable from a
clean architecture while being a claim about nothing at all. For a check meant to
catch structural drift, answering "clean" on the strength of having looked at
nothing is the most convincing way it could mislead you.

The usual cause is a split repository — the architecture document governing one
codebase while the code lives in another — so neither graph holds both halves. If
you see `not_evaluable` with "no files are mapped", check that the path patterns
in `system_architecture.md` match your actual layout, then re-run `scaffold
index`. Layer counts and the number of imports skipped for want of a mapping are
included in the report, so you can tell how much the check could see.

| `status` | Means |
|---|---|
| `pass` | Every cross-layer import consumes the layer below |
| `fail` | At least one inversion or skip; each violation names both files |
| `not_evaluable` | The check could not see enough to answer; read `reason` |

Treat `not_evaluable` as "unknown", never as "fine".

### Review Findings: Continuous Improvement Feedback Loop

`scaffold_record_finding` and `scaffold_resolve_finding` close the loop between reviews and
implementation. Findings are persisted as graph nodes and surface automatically in every
subsequent review of the same plan — the agent cannot forget a finding because it lives in
the graph, not in context.

**The full cycle:**

1. **During review** — agent (or human) identifies an issue and records it:
   ```
   "record finding: plan 149 has a missing error handler in the retry path, severity high"
   ```
   This calls `scaffold_record_finding` and creates a `ReviewFinding` node linked to the
   plan, affected files, and functions.

2. **Next review of the same plan** — `scaffold_prepare_review` automatically includes all
   open findings in its `open_findings` list, ordered by severity. The reviewing agent sees
   the finding without needing to re-read prior session history.

3. **After the fix ships** — mark it resolved:
   ```
   "mark finding rf::abc123 resolved -- added retry backoff in commit abc456"
   ```
   The finding status flips to `resolved`. It is retained in the graph for retrospective
   audit but filtered from active review output.

4. **Retrospective** — `scaffold_prepare_retro` surfaces resolved findings as part of the
   post-implementation record, showing what was caught in review and how it was addressed.

**Practical usage:**

```
# Record during a review session
"I found an issue in plan 42 -- log this review finding: the session end command
 requires an explicit session ID which breaks automation scripts. Severity: medium."

# Later, after the fix
"resolve finding rf::90cd4acdb447 -- fixed in 0.3.1, session ID is now optional"
```

Findings are linked to specific files and functions when provided, so future
`scaffold_impact` calls on those files also surface related open findings.

### Graph Quality

The graph includes verification mechanisms:

- **Content hashing**: Each file node stores a SHA-256 hash. `scaffold graph verify` compares these against current files to detect staleness.
- **Staleness detection**: Files modified since last index are flagged.
- **Missing file detection**: Files deleted since last index are reported.
- **Deep verification**: `--deep` re-parses a sample of files and compares function/class counts against stored data.

Run `scaffold graph verify` periodically or after significant codebase changes. Re-index with `scaffold index` to refresh.

---

## Multi-Project Workspaces and Shared Asset Layout

A `workspace.yaml` at the workspace root lets several projects share one graph
cache and, optionally, one copy of reusable process assets.

### Shared asset layout

By default each project keeps a full `docs/ai` tree. In a multi-project
workspace you can opt into `asset_layout.layout: shared_workspace` so reusable
process assets (prompts, standards, templates, collaboration protocol, commands,
shared security templates) live once at the workspace root, while each project
keeps its own plans, ADRs, contracts, backlog, architecture, and vision. See the
configuration guide for the full schema and the escape hatch for per-project
customizations.

On a fresh workspace, enable it while registering projects:

```bash
scaffold workspace onboard services/api --shared-layout
scaffold workspace onboard apps/web
```

### Nested IDE focus and MCP anchors

Each registered project root keeps a **stub** `AGENTS.md` (pointers to the shared
process assets), and the workspace root gets a thin router `AGENTS.md`. When your
IDE opens a parent folder, pin the MCP resolution anchor with `scaffold mcp
--workspace <root> --project <name>` or the `AGENTSCAFFOLD_WORKSPACE_ROOT` /
`AGENTSCAFFOLD_PROJECT` env vars (see the platform-integration guide).

Personalize with `*.local` overlays (`AGENTS.local.md`,
`.cursor/rules/local.*.mdc`) -- never by gitignoring the team `AGENTS.md`.

### Migrating an existing workspace (brownfield)

An existing multi-project workspace that already duplicated process trees can
adopt the shared layout without hand-editing paths. Agent-facing checklist:

1. Confirm a `workspace.yaml` with two or more projects exists (else run
   `scaffold workspace onboard` first). This migrator moves *files*; it is
   distinct from `workspace onboard --migrate-existing`, which re-keys graph IDs.
2. Inspect (safe, non-mutating):

   ```bash
   scaffold workspace migrate-layout --dry-run --json
   ```

3. Summarize the report: identical count, diverged paths (which projects
   differ), unique promotions, and confirm project SoR is untouched.
4. **Stop and ask** the human to approve apply. For each diverged path choose
   `--prefer-project NAME`, `--keep-diverged`, or merge manually first.
5. Apply after approval:

   ```bash
   scaffold workspace migrate-layout --apply --prefer-project api
   # or keep diverged copies project-local:
   scaffold workspace migrate-layout --apply --keep-diverged
   ```

6. Regenerate agents if needed (`scaffold agents generate-all`), run `scaffold
   index` / orient smoke for one project, and open a PR listing promoted,
   deleted, and kept-diverged paths.

The migrator refuses to apply on a dirty git worktree (pass `--force` to
override), never moves project system-of-record files (plans, ADRs, contracts,
state, backlog, architecture), and is idempotent on re-run. Exit codes: `0`
success / already migrated; `2` diverged conflicts unresolved without policy; `3`
dirty worktree without `--force`.

---

## Anti-Patterns to Avoid

Based on observed sessions, these patterns lead to poor outcomes:

**Letting the agent skip pre-reviews.** The agent sometimes tries to jump straight to implementation. Always enforce: "pre reviews first."

**Accepting reviews without reading them.** The reviews exist to catch problems. Probe the findings, ask about alternatives, challenge assumptions.

**Skipping the gaps sweep.** Individual reviews catch most issues. The gaps sweep catches the rest. It consistently finds 3-5 additional items per plan.

**Not verifying wiring.** Ask "is everything wired up?" before moving to tests. Stubs and incomplete integrations are the most common source of post-implementation bugs.

**Not providing git context.** Always tell the agent which branch you are on and whether it is up to date. The agent cannot safely create branches without this information.

**Skipping the close-out.** The retrospective and state updates are not optional. They are how the framework learns and improves. Every session that skips the retro loses learnings.

---

## Quick Reference: Key Phrases

| Phase | Phrase | What It Does |
|-------|--------|-------------|
| Open | "lets review plan X following the collab protocols" | Starts full review sequence |
| Branch | "create a new branch. we are on staging and its up to date" | Sets git context |
| Enforce | "pre reviews first" | Stops agent from skipping reviews |
| Gaps | "make sure we have ALL gaps, mitigations, future regrets... EVERYTHING" | Triggers comprehensive second pass |
| Execute | "proceed" / "begin implementation" / "build!" | Green-lights coding |
| Validate | "is everything wired up?" | Catches stubs and missing integrations |
| Test | "did you run integration tests? with real data?" | Catches untested code |
| Boundary | "you cant push without my permission" | Enforces safety boundaries |
| Close-out | "post implementation review and retro" | Triggers full close-out |
| State | "update workflow state, plan completion log, and changelog" | Ensures all state files are current |
| Commit | "commit all changes" | Triggers git commit |
| Housekeep | "move completed backlog items to the backlog archive" | Keeps backlog clean |

---

## Troubleshooting

### Semantic search not working

`scaffold graph search --mode semantic` and `--mode hybrid` require:

1. `pip install "agentscaffold[search]"` (installs sentence-transformers)
2. `scaffold index --embeddings` (generates embedding vectors)

Without both, search falls back to keyword-only with a "No embeddings found" warning.

### Graph is stale or showing wrong results

Run `scaffold graph verify` to check staleness:

```bash
scaffold graph verify       # Fast hash check
scaffold graph verify --deep  # Re-parses a sample of files
```

If many files are stale, do a full re-index:

```bash
scaffold index
```

For large repos where incremental is too slow, enable async freshness in `scaffold.yaml`:

```yaml
freshness:
  async_enabled: true
  debounce_seconds: 120
```

### DuckDB file locked or corrupted

The knowledge graph is a single DuckDB file with a **single-writer** model:
only one process may hold it open for writing at a time. The MCP server holds
the graph open, and `scaffold index` opens it for writing, so running an index
while the MCP server (or another `scaffold` command) is using the same
`.scaffold/graph.duckdb` will fail.

As of 0.6.0 a lock conflict raises a clear `GraphLockError` after a short
automatic retry (instead of a raw DuckDB `IOException`), and MCP tool calls
return `{"error": ..., "graph_locked": true}` rather than crashing. The async
freshness refresh serializes *scheduling* per workspace, but it does not make
concurrent writers safe -- it still assumes a single writer.

To resolve a lock, stop any running MCP server first (`Ctrl-C` or kill the
process) and ensure no other `scaffold` command is running, then re-run your
command.

**Abandoned write-lock directory.** AgentScaffold also uses a small filesystem
lock beside the database (`.scaffold/graph.write.lock/`, or next to a migrated
graph under the platform state directory). If a writer crashes, that directory
can be left behind. As of 0.10.3 the next waiter removes it when `owner.json`
names a process that is no longer alive. If you still see
`graph_locked` / `Timed out waiting for graph write lock` and no AgentScaffold
process is running, remove the lock directory named in the error and retry:

```bash
rm -rf .scaffold/graph.write.lock
```

If the DuckDB file itself is genuinely corrupted, rebuild it:

```bash
rm .scaffold/graph.duckdb
scaffold index
```

### Schema upgrades preserve your findings and sessions

> **Upgrading to 0.10.0 rebuilds your graph on the first `scaffold index`.**
> Nothing is required of you beyond running it as usual, but expect a full
> rebuild's time rather than an incremental one, and see below for why this
> particular version bump matters more than most.

When AgentScaffold's graph schema version changes (after an upgrade), the next
`scaffold index` rebuilds the graph. As of 0.6.0 this is a **safe, recoverable**
operation: before the rebuild, preserved governance (review findings, backlog
items, sessions and their edges) is exported to
`.scaffold/graph_export_v{old}.json`, and after the rebuild the compatible data
is re-imported automatically.

The migration is **fail-closed**: if the export step fails, the rebuild is
aborted and the existing graph is left intact, so your knowledge is never lost.
If some data is schema-incompatible and cannot be re-imported, the export file
is kept and a message tells you where it is. The export file contains only
project governance text (no secrets) and is safe to delete once you have
confirmed the rebuild succeeded.

**Why 0.10.0 bumps the version without changing any table.** Before 0.10.0,
relative Python imports (`from .module import name`) produced no import edge at
all. The path built for them was subtly malformed, the check for its existence
normalised the malformation and reported success, and the resulting string then
failed to match anything — so the import was silently filed as unresolved. Any
project using relative imports has a graph that is missing real dependencies.

That matters most for `scaffold_impact`, which walks import edges to answer "what
else does this change affect?". A missing edge means the answer is too small, and
an under-reported blast radius looks exactly like a genuinely contained change.
There is no warning to notice, which is why the version bump exists: rather than
leaving those graphs quietly incomplete until someone thought to rebuild, the
version change routes them through the normal preserving rebuild automatically.

If your project has no relative imports, the rebuild costs you time and changes
nothing. If it does, the graph gains edges it should always have had, and impact
results will legitimately grow.

**If you see "Aborting schema rebuild ... failed to export preserved governance":**
the rebuild was halted and nothing was deleted. The message includes the graph
file path and the underlying error; the full traceback is in the logs (logged at
ERROR). The cause is almost always a transient I/O problem:

1. **Disk full** -- free up space, then re-run `scaffold index`.
2. **`.scaffold/` is read-only** -- fix directory permissions, then re-run.
3. **Graph file open in another process** -- close other AgentScaffold
   processes / editors holding the DuckDB file, then re-run.

Once the underlying cause is fixed, simply re-run `scaffold index` -- the
migration retries from scratch.

If the export error is unrecoverable and you do not need the existing findings,
sessions, and backlog items, you can force the rebuild:

```bash
scaffold index --force-rebuild
```

With `--force-rebuild`, an export failure is downgraded from an abort to a
warning and the graph is rebuilt anyway. This **permanently discards** the
preserved governance, so it is opt-in and never the default. (Deleting the graph
file shown in the error is the equivalent manual alternative.)

### Pruning old governance data

Over time, resolved findings, archived backlog items, and old sessions
accumulate. Use `scaffold graph prune` to trim them. It is **dry-run by
default** and only ever selects status-eligible rows (resolved findings,
archived backlog, sessions past the cutoff):

```bash
# Preview what would be deleted (no changes made)
scaffold graph prune --sessions-before 90d --archived-backlog-before 180d

# Actually delete the selected rows
scaffold graph prune --sessions-before 90d --archived-backlog-before 180d --apply
```

Options:

- `--resolved-findings-before <Nd>`: select resolved findings. (Findings carry
  no timestamp, so all resolved findings are selected regardless of the age value.)
- `--sessions-before <Nd>`: select sessions older than `N` days.
- `--archived-backlog-before <Nd>`: select archived backlog items older than `N` days.
- `--apply`: required to actually delete; without it the command only reports
  what it would remove.

There is no automatic TTL -- pruning is always explicit.

### Tree-sitter grammar not loading for a language

A warning like `No language_c() in tree_sitter_c` usually means the grammar package for
that language is not installed. Install it with the appropriate extra:

```bash
pip install "agentscaffold[graph-c]"    # C
pip install "agentscaffold[graph-cpp]"  # C++
pip install "agentscaffold[graph]"      # Python, JS, TS
```

Supported languages: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++.

### `scaffold graph query` returns a SQL error

The graph uses DuckDB with DuckPGQ — queries must be SQL. Example:

```bash
scaffold graph query "SELECT count(*) FROM File"
```

Use standard SQL `SELECT` statements. Property graph traversals use `FROM GRAPH_TABLE(...)` syntax.
