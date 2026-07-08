---
study_id: STU-2026-06-14-agentscaffold-multiproject-collab-durability
title: "AgentScaffold multi-project, multi-user, and durable-storage design"
study_type: exploratory
status: in_progress
started: 2026-06-14
completed: null

tags: [agentscaffold, architecture, multi-project, collaboration, storage, ephemeral]
related_plans: [149, 217, 218, 219, 220, 221, 222, 223]
related_studies: []

variants: []
metrics: []
artifacts: []

outcome: null
confidence: null
recommendation: null
---

# Study: AgentScaffold multi-project, multi-user, and durable-storage design

## Overview

**Background**: AgentScaffold today is a single-project, cwd-sensitive tool. It
works well for one developer in one repository, but three forces stress that
model: (1) using AgentScaffold across many projects (in one monorepo or many
repos), (2) multiple people or agents collaborating on the same plans/feature,
and (3) ephemeral dev environments (e.g. Dropsuite/Codespaces-style containers
on AWS) that can be deleted with all local contents after inactivity. This study
captures the design options and trade-offs for six threads identified in a
2026-06-14 design discussion (logged as backlog item B-149-5) and recommends a
phased sequence so we can derive concrete plans.

**Hypothesis**: Most of the multi-user and ephemeral-storage pain resolves once
we (a) make explicit the boundary between the durable *system of record* (git)
and the disposable *derived cache* (the DuckDB graph), and (b) unify path/root
resolution. The multi-project and config-sharing work then layers on top of that
foundation.

**Non-goals**: This study does not implement anything. It does not propose a
shared live multi-writer graph database (rejected below). It does not change the
6-layer trading-system architecture; it concerns the AgentScaffold package only.

## Methodology

### Current-state grounding

A read-only codebase audit (the AgentScaffold package at
`agentscaffold`) established the following facts that constrain the
design:

- **Config discovery** is walk-up for `scaffold.yaml` (`find_config()`), but
  many CLI commands use `Path.cwd()` instead, and some take an explicit
  directory argument. There are effectively three competing notions of
  "project root."
- **Two path systems coexist.** `GraphConfig` exposes configurable paths
  (`plans_dir`, `workflow_state_file`, `contracts_dir`, ...), honored by the
  graph/MCP layer. But CLI commands (`scaffold plan create`, plan lint/status,
  spike/study create, metrics, validate) **hardcode** `docs/ai/plans` and
  friends and ignore the config.
- **`open_graph()` resolves `db_path` relative to process cwd**, while
  `run_pipeline()` resolves it relative to the index root. This is a latent bug
  for subdir and ephemeral workflows.
- **The graph is a derived cache**: gitignored under `.scaffold/`, single-writer
  per developer, rebuilt from code + governance markdown. BUT agent-generated
  `ReviewFinding` and `Session` nodes currently live *only* in that cache and
  are serialized to git nowhere.
- **No multi-project/workspace model exists.** One `scaffold.yaml` per tree;
  the MCP "workspace key" is only an in-process refresh-dedup detail.
- **Consumer `paths:` blocks in `scaffold.yaml` are ignored** by Python (no
  `PathsConfig`); only `graph.*` paths are read at runtime.

### Framing lens

The unifying idea is to name two kinds of state explicitly:

- **System of record (durable, shared, must survive):** plans,
  `workflow_state.md`, backlog, contracts, ADRs, standards. Git already provides
  durability, history, multi-user merge, and review.
- **Derived cache (rebuildable, local, disposable):** the DuckDB graph. Rebuilt
  on demand; losing it costs time, not data -- *except* for the agent-generated
  knowledge that currently leaks into it with no git-backed copy.

Drawing that boundary cleanly is the single highest-leverage move; it is the
common root of both the collaboration gap and the ephemeral-storage risk.

## Results

This section enumerates the six threads as design options with trade-offs. (For
an exploratory study these are "results" in the sense of analysis outputs, not
empirical measurements.)

### Thread 1 (Foundation): Unify path/root resolution

**Problem**: Three notions of root and two path systems mean a setting like
`graph.plans_dir` changes indexing/MCP but not `scaffold plan create`. Nothing
multi-project is safe until "where do files live" has one answer.

**Option A -- single resolved-paths object + one root rule.** Introduce a
`PathsConfig` (or fold into a resolved-paths accessor) and one project-root rule
(nearest `scaffold.yaml`, fallback git root), and route *every* CLI command and
the graph/MCP layer through it. Pro: removes the latent cwd bugs, prerequisite
for everything else. Con: breaking refactor; touches many modules; needs a
refactor-template plan and careful migration of hardcoded paths.

**Option B -- minimal patch (only fix `open_graph` cwd bug).** Pro: small. Con:
leaves the two-path-system divergence, so multi-project remains unsafe. Rejected
as insufficient.

**Recommendation**: Option A, but de-risk with a spike first (high uncertainty:
how many hardcoded callsites, how to stay backward-compatible for existing
single-project repos).

### Thread 2: Serialize agent knowledge to git

**Problem**: `ReviewFinding`/`Session`/`BacklogItem` (agent-generated) live only
in the local graph, so they are invisible to teammates and die with the devbox.

**Option A -- promote the Plan 219 `export_governance`/`import_governance`
machinery into the durable serialization.** Write governance to a git-committed
JSONL (or per-item files) as the system of record; the graph becomes a pure
index built from them. Pro: reuses code we already shipped in 0.6.0; fixes
collaboration and durability at once; git handles merge/history. Con: need a
stable on-disk schema and a render/ingest step; decide file granularity.

**Option B -- keep knowledge only in the graph and share the DuckDB file.**
Rejected: DuckDB is single-writer and a binary cache; sharing it via sync/network
FS risks corruption and defeats git review.

**Recommendation**: Option A. This is the highest-value thread overall.

### Thread 3: Durable / ephemeral storage

**Problem**: An ephemeral devbox can be deleted with `.scaffold/`. The graph is
rebuildable, so the only true loss is not-yet-serialized agent knowledge (Thread
2). Remaining needs: make the cache location portable and bootstrap a fresh box.

**Option A -- configurable + env-expandable `db_path` and export/restore.**
Support absolute paths (already works), add `${ENV}` expansion and an
`AGENTSCAFFOLD_DB_PATH` override so one committed `scaffold.yaml` works in both
ephemeral and persistent environments; auto-export governance to a durable
location (git, mounted volume, or object store) and auto-restore on first index
in a fresh box. Pro: respects DuckDB locking (live cache stays local/fast);
reuses 219 export/import; directly answers the Dropsuite constraint. Con: small
hardening + a restore path.

**Option B -- run the live DuckDB on a synced/network FS (e.g. laptop mount).**
Rejected: DuckDB locking + sync filesystems risk corruption.

**Recommendation**: Option A. Largely falls out of Thread 2.

### Thread 4 (Phase 2): Config inheritance for shared policy

**Problem**: Standards, templates, prompts, rigor presets are *policy* -- they
should be shareable across repos, but today they are copied into each project's
`docs/ai/` tree and drift.

**Option A -- layered config cascade** (eslint/tsconfig style): an org/user-level
home (`$AGENTSCAFFOLD_HOME` or `~/.agentscaffold`) holds shared policy; a project
`scaffold.yaml` does `extends:` and overrides locally. Pro: single source for
shared policy across many repos. Con: resolution precedence and offline behavior
need care; depends on the unified path model (Thread 1).

**Recommendation**: Option A, but only after the foundation lands.

### Thread 5 (Phase 2): Multi-project workspace model

**Problem**: One repo may host several sub-projects (the monorepo case -- note
AgentScaffold itself lives inside `rebellion-trading-system/packages/`).

**Option A -- federated**: each sub-project gets its own `docs/ai/` subtree and
its own graph. Pro: clean isolation, no ID collisions. Con: cross-project search
and backlog fragmented.

**Option B -- namespaced**: one shared `docs/ai/`, plan/backlog IDs prefixed by
project, and a `Project` node in the graph with a `project` property on
plans/findings. Pro: unified retrieval and backlog; one index serves filtered
per-project and cross-project views -- turns multi-project into a query problem
the graph is good at. Con: needs disciplined namespacing to avoid clutter.

**Recommendation**: Lean Option B (let the graph carry the load), decided in a
plan after the foundation. Keep federated as the fallback for hard-isolation
needs.

### Thread 6 (Phase 2): Collaboration ergonomics

**Problem**: `workflow_state.md` and `backlog.md` are single append-heavy files
(merge-conflict magnets); no notion of who/which agent owns a plan in flight.

**Option A -- shard high-contention files** (towncrier/changeset style):
`workflow_state/` as per-plan fragments, backlog as one-file-per-item, assembled
by a render command. Plus a lightweight `scaffold plan claim <id>` ownership
convention (git-backed). Pro: drastically fewer conflicts; cheap coordination.
Con: more files; needs an aggregation/render step.

**Option B -- a shared live multi-writer graph (server/Postgres).** Rejected:
large lift, and unnecessary because git is the system of record and the graph is
derived per-developer.

**Recommendation**: Option A, last in the sequence.

## Analysis

### Key observations

1. Threads 2 and 3 collapse into the same two fixes: draw the system-of-record
   vs derived-cache boundary and serialize agent knowledge to git (reusing the
   Plan 219 export/import primitive shipped in 0.6.0).
2. Thread 1 (path/root unification) is a hard prerequisite for Threads 4-5 and
   removes existing latent bugs regardless of multi-project ambitions.
3. The DuckDB graph should stay an explicitly disposable, local, single-writer
   cache. Every "shared/durable" requirement should be satisfied via git (or an
   exported artifact), never by sharing the live DB file.

### Dependency / sequencing

Phase 1 (foundation chain, in order):
1. Path/root unification (spike first, then a refactor-template plan).
2. Serialize agent knowledge to git (depends on 1 for path resolution).
3. Durable/ephemeral storage: env-expandable `db_path` + auto-export/restore
   (depends on 2's serialization format).

Phase 2 (build on the foundation):
4. Config inheritance for shared policy.
5. Multi-project workspace model (`Project` node; namespaced vs federated).
6. Collaboration ergonomics (file sharding + `plan claim`).

### Limitations

- Path-model unification is a breaking change; existing single-project repos
  must keep working. Backward-compatible defaults and a migration note are
  required (refactor plan template, Approval Required likely Yes).
- `gh`/API and credential-helper auth can bypass local git gating; any
  collaboration/security assumptions must be validated separately (not in scope
  here).
- File granularity for serialized governance (JSONL vs per-item files) is
  unresolved and should be decided in the Thread 2 plan.

## Conclusions

The recommended approach is a two-phase program anchored on one principle:
**git is the system of record; the DuckDB graph is a derived, disposable cache.**
Phase 1 unifies path/root resolution, then serializes agent knowledge to git
(reusing Plan 219 export/import), then makes storage portable and
ephemeral-safe. Phase 2 adds shared-policy inheritance, a multi-project
workspace model, and collaboration ergonomics. A spike on path/root unification
should precede Phase 1 implementation because it is the highest-uncertainty,
highest-blast-radius change.

## Recommendations

### Immediate actions

- [x] Create a spike (`docs/ai/spikes/`) to scope path/root unification: count
      hardcoded path callsites, prototype a resolved-paths accessor, and confirm
      a backward-compatible default for existing single-project repos.
      DONE: `docs/ai/spikes/SPIKE-2026-06-14-agentscaffold-path-root-unification.md`
      -- decision: feasible + backward-compatible; proceed with a refactor plan.
- [x] Derive Phase 1 plans from this study after the spike: (1) path/root
      unification (refactor template, Approval Required), (2) git-backed
      governance serialization, (3) durable/ephemeral storage.
      DONE: Plans 221, 222, 223 -- all implemented, tested (634 pass),
      lint+mypy clean, marked COMPLETE 2026-06-14 (see Update 2026-06-15 below).

### Follow-up studies

- [x] Decision: the namespaced multi-project model (Thread 5 Option B) is the
      chosen direction, so a short spike on `Project`-node query ergonomics
      (per-project vs cross-project views) is required before the Thread 5 plan.
      DONE: SPIKE-2026-06-15-agentscaffold-project-node-workspace -- decision:
      proceed (modify) with the namespaced design (additive `Project` node +
      `project` column; id-prefixing gated on multi-project; a read-scoping
      helper over ~32 callsites; per-project `governance.json`; a
      `resolve_workspace_root()`). Lone repos stay un-namespaced (zero migration).
- [x] Confirmed warranted by the spike: a short follow-up sub-study on
      cross-project query *views* (per-project vs federated retrieval ergonomics)
      before Plan 225 finalizes the read-helper design.
      DONE: STU-2026-06-15-agentscaffold-cross-project-query-views -- decision:
      a parameterized scoping helper (default current project, explicit
      federation), not physical per-project DB views (the property graph is over
      base tables, so `GRAPH_TABLE` cannot target views). Three logical modes:
      current / targeted / federated. Feeds Plan 225.

## Update 2026-06-15: Phase 1 complete; Phase 2 decisions locked

**Phase 1 shipped.** The foundation chain (Plans 221 path/root unification, 222
git-backed governance serialization, 223 durable/ephemeral storage) is
implemented, tested (634 pass), lint+mypy clean, and marked COMPLETE. The study's
core principle held in implementation: git is the system of record; the DuckDB
graph is a derived, disposable cache. No recommendation was invalidated.

**Phase 1 learnings that shape Phase 2:**
- `agentscaffold/paths.py` now provides `resolve_root()`, a `ResolvedPaths`
  accessor over `GraphConfig`, and `resolve_db_path()` (env-expandable). Thread 4
  (`extends:`) layers config resolution *under* this same root rule; Thread 5
  reuses `resolve_root()` to locate each project.
- A committed `governance.json` artifact now exists with a versioned
  export/import codec (`graph/governance_store.py`). Thread 5's `project`
  tagging and Thread 6's file sharding build on this artifact rather than the
  live DB.
- `GraphConfig` gained additive path fields; Thread 4's cascade must merge these
  field-by-field (deep-merge already exists in `config.apply_rigor_preset`).

**Phase 2 decisions locked (2026-06-15):**
- Thread 4 (config inheritance): **Option A** -- layered cascade with an
  org/user home (`$AGENTSCAFFOLD_HOME` / `~/.agentscaffold`) and `extends:` in
  `scaffold.yaml`. Becomes **Plan 224** (standalone, drafted now).
- Thread 5 (multi-project workspace): **Option B (namespaced)** is the chosen
  direction, but gated behind a spike on `Project`-node query ergonomics before
  the plan (highest Phase 2 uncertainty). Spike queued; Plan 225 follows it.
- Thread 6 (collaboration ergonomics): **Option A** -- shard
  `workflow_state`/`backlog` + `scaffold plan claim`. Becomes **Plan 226**, last.

**Phase 2 sequencing:** Plan 224 (inheritance) -> SPIKE Thread 5 ->
Plan 225 (workspace, namespaced) -> Plan 226 (collaboration).

## Appendix

### Source

Design discussion 2026-06-14; backlog item B-149-5. Builds on the 0.6.0 Trust &
Safety Hardening batch (Plans 217-220), notably Plan 219's
`export_governance`/`import_governance`, which this study proposes to promote
from a migration-only mechanism into the durable system of record.

### Timeline

| Date | Event |
|------|-------|
| 2026-06-14 | Study started (design discussion captured) |
