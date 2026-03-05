# User Guide: Working with an AI Agent Using AgentScaffold

This guide documents proven interaction patterns for human-AI collaboration using the AgentScaffold framework. These patterns were extracted from hundreds of real implementation sessions and represent the most effective ways to communicate with your AI coding agent.

## The Canonical Session Flow

Every plan implementation session follows a predictable arc. Learning this arc makes your sessions faster and more consistent.

```
Open -> Assess -> Branch -> Review -> Gaps Sweep -> Execute -> Steer -> Close Out -> Commit
```

Each phase has specific trigger phrases and expectations. The sections below detail each one.

But first -- if you don't have any plans yet because you're starting a brand new project, read the Greenfield Onboarding section below.

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

The graph is stored at `.scaffold/graph.db` by default (configurable in `scaffold.yaml` under `graph.db_path`). It requires the `[graph]` optional dependency:

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

### Incremental Indexing

After the first full index, use `--incremental` for fast re-indexing:

```bash
scaffold index --incremental
```

Incremental mode compares SHA-256 content hashes of files on disk against those stored in the graph. Only files that were added, modified, or deleted since the last index are processed. On a large codebase where only a handful of files changed, this is dramatically faster than a full re-index.

The changeset output shows exactly what changed:
```
Incremental index -- computing changeset...
  3 added, 2 modified, 1 deleted, 847 unchanged
```

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
# Start a session (associate with plan numbers)
scaffold session start --plan 42 --summary "Implementing data pipeline"

# Record which files you modified (usually done automatically)
# The session tracks modifications via SESSION_MODIFIED edges

# End the session with a summary
scaffold session end <session-id> --summary "Completed phase 1"

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
scaffold graph query "MATCH (f:File) RETURN count(f)"  # Raw Cypher
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
# Hybrid search (Cypher + semantic -- default)
scaffold graph search "data routing strategy"

# Pure structural search (name/path matching)
scaffold graph search "router" --mode cypher

# Pure semantic search (vector similarity)
scaffold graph search "how is data loaded" --mode semantic

# Limit results
scaffold graph search "risk" --top 5

# Restrict to a single table
scaffold graph search "base class" --table Class
```

Hybrid mode uses **reciprocal rank fusion** (RRF) to merge structural and semantic results, giving the best of both worlds: exact name matches from graph traversal and conceptual matches from embeddings.

Embeddings are generated automatically during indexing when `--embeddings` is passed:

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

When running the MCP server (`scaffold mcp`), graph-powered tools are available to AI agents:

| Tool | What It Does |
|------|-------------|
| `scaffold_stats` | Codebase health dashboard (files, functions, edges, governance) |
| `scaffold_query` | Execute raw Cypher queries against the knowledge graph |
| `scaffold_search` | Hybrid search (cypher, semantic, or hybrid mode) |
| `scaffold_context` | Full context for a symbol (definition, callers, layer, plan history) |
| `scaffold_impact` | Blast radius analysis for a file or symbol |
| `scaffold_validate` | Validation checks (layers, contracts, staleness) |
| `scaffold_review_context` | Review context (brief, challenges, gaps, verify, retro) for a plan |

The MCP tools return both structured JSON and formatted markdown, so agents can parse the data programmatically or display it directly.

### Graph Quality

The graph includes verification mechanisms:

- **Content hashing**: Each file node stores a SHA-256 hash. `scaffold graph verify` compares these against current files to detect staleness.
- **Staleness detection**: Files modified since last index are flagged.
- **Missing file detection**: Files deleted since last index are reported.
- **Deep verification**: `--deep` re-parses a sample of files and compares function/class counts against stored data.

Run `scaffold graph verify` periodically or after significant codebase changes. Re-index with `scaffold index` to refresh.

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
