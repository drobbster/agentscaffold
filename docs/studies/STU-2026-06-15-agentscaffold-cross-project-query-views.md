---
study_id: STU-2026-06-15-agentscaffold-cross-project-query-views
title: "AgentScaffold cross-project query views (namespaced workspace retrieval)"
study_type: exploratory
status: complete
started: 2026-06-15
completed: 2026-06-15

tags: [agentscaffold, architecture, multi-project, graph, retrieval]
related_plans: [221, 224, 225]
related_studies: [STU-2026-06-14-agentscaffold-multiproject-collab-durability]

variants: []
metrics: []
artifacts: []

outcome: needs_followup
confidence: medium
recommendation: "Scope reads with a parameterized query-helper (default current project, explicit federation), not physical per-project DB views; physical views cannot cover the GRAPH_TABLE-over-base-tables majority. Feeds Plan 225."
---

# Study: AgentScaffold cross-project query views (namespaced workspace retrieval)

## Overview

**Hypothesis**: In the namespaced multi-project workspace (one shared,
process-global DuckPGQ graph; project-tagged nodes), cross-project retrieval is
best served by **parameterized project-scoping inside the existing read helpers**
-- default to the current project, with an explicit opt-in for federation --
rather than by **physical per-project database views**. Physical views cannot
serve the majority of reads because the DuckPGQ property graph is defined over
*base* tables and `GRAPH_TABLE MATCH` cannot target views.

**Background**: SPIKE-2026-06-15-agentscaffold-project-node-workspace decided
"proceed (modify)" with the namespaced model and explicitly flagged that the
~32-callsite read surface plus the per-project-vs-federated *view* question
deserved a short sub-study before Plan 225 finalizes the read-helper design. This
study answers that question so Plan 225 can specify the helper concretely.

## Methodology

This is a design study (not an empirical A/B run): it catalogs the actual read
surface, enumerates the candidate scoping mechanisms, and evaluates them against
the constraints the spike established (single process-global graph;
project-prefixed IDs in multi-project mode; lone repos must stay un-namespaced
with zero migration).

### The read surface (evidence)

Two query shapes dominate, both dispatched through `ql()` / `ql_scalar()` /
`store.query()`:

1. **`GRAPH_TABLE MATCH` over the property graph `agentscaffold_graph`** -- the
   majority of `review/queries.py` (plans-impacting-file, findings, learnings,
   studies, ADRs, spikes, plan dependencies, hot/volatile files). These traverse
   edges and reference base node tables through the property graph.
2. **Plain SQL table `SELECT`s** -- `get_all_plans`, `get_recurring_finding_patterns`,
   `get_all_studies/adrs/spikes`, the four code-node selects in `graph/search.py`,
   and the backlog/sessions/prune helpers.

Approximate counts: ~28 governance reads across `review/queries.py` (13),
`graph/backlog.py` (5), `graph/sessions.py` (4), `graph/prune.py` (3),
`graph/findings.py` (2), `mcp/server.py` (1), plus 4 code-node selects in
`graph/search.py`. The functions are uniform: each takes a `GraphBackend` and
builds a SQL string, so a scoping parameter can be threaded consistently.

## Results

This is a design study, so the "result" is a mechanism decision rather than a
measured metric. Summary verdict across the candidate scoping mechanisms:

| Option | Covers graph queries? | Covers plain SQL? | Single-repo no-op? | Verdict |
|--------|-----------------------|-------------------|--------------------|---------|
| A. Physical per-project DB views | No (property graph is over base tables) | Yes | Yes | Rejected |
| B. Parameterized scoping helper | Yes | Yes | Yes | **Recommended** |
| C. Per-project attached databases | No (no cross-DB graph traversal) | Partial | Yes | Rejected |

Logical view modes layered on Option B: current (default) / targeted
(`--project X`) / federated (`--all-projects`).

## Analysis

### Options considered

**Option A -- physical per-project DB views.** Define `Plan`, `File`, `ReviewFinding`,
etc. as SQL views filtered by `project`, swap the connection's search path per
project, and leave query text unchanged. **Rejected**: `CREATE PROPERTY GRAPH
agentscaffold_graph` is defined over the *base* tables (see `duckpgq_schema.py`),
and `GRAPH_TABLE MATCH` runs against that property graph, not arbitrary views.
You cannot point the property graph at per-project views without maintaining one
property graph per project, which conflicts with the spike's process-global,
single-graph finding. Views would cover only the plain-SQL minority and silently
leave every graph-traversal query unscoped -- the worst failure mode.

**Option B -- parameterized scoping helper (recommended).** Add a small
`graph/scoping.py` exposing a `current_project()` resolver (from `resolve_root()`
-> the `Project` name) and predicate builders for both shapes: a plain-SQL
`project_predicate(project)` (`AND project = '...'`) and a graph-aware variant
that injects `n.project = '...'` into the `GRAPH_TABLE ... WHERE` clause. Each
read function gains an optional `project: str | None` argument (default = current
project); `project=None` means "no predicate" (federation). **Preferred**: it
covers both query shapes uniformly, is explicit and unit-testable, and is a
low-variance change because the read functions are already homogeneous.

**Option C -- one attached DuckDB database per project.** `ATTACH` a separate DB
file per project and qualify names. **Rejected**: contradicts the spike's single
shared cache and Plan 223's one-cache model, and cross-project graph traversal
across attached databases is not supported by the property graph.

### The "views" question, answered as logical (not physical) scoping

The per-project-vs-federated *view* is best expressed as three logical modes on
top of Option B, not as physical DB objects:

- **Current (default, no flag)**: predicate = the current project resolved from
  cwd. This is the common case and, crucially, a **no-op for a single-project
  repo** (one project -> the predicate matches everything / can be omitted),
  preserving the spike's "lone repos unchanged" guarantee.
- **Targeted (`--project X`)**: predicate = `X`.
- **Federated (`--all-projects` / `project=None`)**: no predicate; results span
  the workspace, and federated result dicts gain a `project` column so rows stay
  attributable.

### Key observations

1. The property-graph-over-base-tables constraint is decisive: it eliminates
   physical view federation for the graph-traversal majority and forces a
   predicate-injection design.
2. The read functions are already uniform (all route through `ql`/`store.query`),
   so a single helper plus an optional parameter is a small, mechanical change
   rather than a redesign.
3. Because IDs are project-prefixed in multi-project mode (spike Q1), by-id
   lookups are already implicitly scoped; the `project` predicate matters most
   for **by-attribute and aggregate** queries.
4. The genuine risk is **aggregate/list queries** (`get_all_plans`,
   `get_hot_files`, `get_recurring_finding_patterns`, `get_all_studies`, the
   `search.py` selects): without scoping these silently blend projects. They are
   the priority callsites for Plan 225.
5. Backward compatibility is free: with one project the predicate is a no-op, so
   single-project repos behave exactly as today.

### Limitations

- Injecting a predicate into a `GRAPH_TABLE ... WHERE` clause is string
  templating; each query needs a test for escaping and alias correctness.
- The MCP handlers assemble SQL ad hoc, so they need explicit wiring rather than
  a blanket decorator.
- This is design-level: it does not benchmark predicate latency. Expected
  negligible (small governance tables; a scanned/indexed `project` column), but
  Plan 225 should add a `project` column index if profiling shows otherwise.

## Conclusions

Cross-project retrieval should be implemented as **parameterized project-scoping
in the existing read helpers** (Option B) exposing three logical modes (current /
targeted / federated), defaulting to the current project. Physical per-project
views (A) and per-project attached databases (C) are rejected because the
single, process-global property graph is defined over base tables and graph
traversal cannot be redirected to views or spanned across attached DBs. The
change is mechanical thanks to the homogeneous read layer, and it is a no-op for
single-project repos.

## Recommendations

### Immediate actions

- [ ] Plan 225: add `graph/scoping.py` (`current_project()` resolver + plain-SQL
      and `GRAPH_TABLE`-aware predicate builders) and thread an optional
      `project: str | None` through the ~32 read functions, defaulting to the
      current project.
- [ ] Plan 225: prioritize the aggregate/list queries (`get_all_plans`,
      `get_hot_files`, `get_recurring_finding_patterns`, `get_all_studies`,
      `search.py` code-node selects) where unscoped blending is the real risk.
- [ ] Plan 225: expose `--project` / `--all-projects` on the CLI + MCP read paths
      and include a `project` column in federated result dicts.
- [ ] Plan 225: add per-query tests for predicate injection (escaping, alias) and
      a single-project no-op regression test.

### Follow-up studies

- [ ] None anticipated. Revisit only if predicate latency proves non-negligible
      at workspace scale (then study a `project` index / partitioning).

## Appendix

### Source

SPIKE-2026-06-15-agentscaffold-project-node-workspace (read-surface catalog and
the process-global-graph constraint); parent study
STU-2026-06-14-agentscaffold-multiproject-collab-durability (Thread 5).

### Evidence

- `src/agentscaffold/review/queries.py` -- the two query
  shapes (`GRAPH_TABLE MATCH` and plain-SQL table selects).
- `src/agentscaffold/graph/search.py` -- code-node selects.
- `src/agentscaffold/graph/duckpgq_schema.py` --
  `CREATE PROPERTY GRAPH` defined over base tables (the decisive constraint).
- `src/agentscaffold/graph/{backlog,sessions,prune,findings}.py`,
  `mcp/server.py` -- remaining governance reads.

### Timeline

| Date | Event |
|------|-------|
| 2026-06-15 | Sub-study started and completed (design-level; feeds Plan 225) |
