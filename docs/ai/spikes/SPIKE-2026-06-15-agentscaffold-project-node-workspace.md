# Spike: AgentScaffold Project-node / namespaced workspace ergonomics

### Metadata

| Field | Value |
|-------|-------|
| Parent Plan | Phase 2, Thread 5 of STU-2026-06-14-agentscaffold-multiproject-collab-durability (backlog B-149-5) |
| Time-box | 2-4 hours |
| Created | 2026-06-15 |
| Author | daverobb (AI-assisted) |
| Status | Complete |

### Goal

**One-sentence goal:**
> Validate that a *namespaced* multi-project model (one shared `docs/ai/` tree
> and one graph, with a `Project` node and project-scoped IDs) gives acceptable
> per-project and cross-project query ergonomics, and can absorb an existing
> single-project repo without breaking its IDs, paths, or governance artifact,
> to determine whether Plan 225 should proceed with the namespaced design.

### Questions to Answer

| # | Question | Success Criteria |
|---|----------|------------------|
| 1 | What graph-schema change namespaces nodes by project (a `Project` node + a `project` property and/or `BELONGS_TO` edge on Plan/ReviewFinding/Session/BacklogItem)? Is it additive/backward-compatible with the Plan 217 schema? | Concrete schema sketch + migration assessment |
| 2 | Can existing reads (`scaffold graph search`, governance reads, MCP handlers) default to one project while still allowing explicit cross-project views? What is the query-rewrite surface? | Callsite catalog + a default-scope rule |
| 3 | How do the Plan 221 path model and the Plan 222 `governance.json` extend to N projects in one workspace (one artifact per project vs one shared, prefixed IDs)? | A recommended layout with trade-offs |
| 4 | Can a single-project repo become "project 1 of N" without breaking existing plan IDs, file paths, or the committed governance artifact? | Yes/No + a backward-compatible default (un-namespaced repos behave as today) |

### Constraints

- Time-box: do not exceed 4 hours.
- Scope: only the four questions; no production schema change in the spike.
- Build on the shipped foundation: `resolve_root()`/`ResolvedPaths` (Plan 221),
  the `governance.json` codec (Plan 222), env-aware `db_path` (Plan 223). Do not
  re-litigate the system-of-record-vs-derived-cache principle.
- Output: clear findings + a go/no-go decision for Plan 225, including whether a
  follow-up sub-study on cross-project query views is warranted.

### Approach

**Steps:**
1. [x] Review the Plan 217 node/edge schema (`duckpgq_schema.py` `EDGE_DEFS`, `NODE_TABLES`) and identify where a `project` property / `Project` node would attach.
2. [x] Catalog read callsites that would need project scoping (graph search, governance reads, MCP handlers, validate/metrics).
3. [x] Sketch the namespaced layout: shared `docs/ai/` vs per-project subtrees, prefixed IDs, one vs many `governance.json`.
4. [x] Prototype (analysis-only) the default-scope query rewrite and a backward-compatible default for un-namespaced repos.
5. [x] Compare against the federated alternative on the four questions to confirm the namespaced lean still holds.

### Findings

#### Question 1: Project-namespacing schema change

**Finding:** Plan 217 made `duckpgq_schema.py` a single source of truth, so the
schema change is mechanically small: add a `Project` node table
(`id, name, root, createdAt`) to `NODE_TABLES`, add a `project VARCHAR` column to
the governance + code node tables, optionally add a `PROJECT_OWNS` edge to
`EDGE_DEFS`, and bump `SCHEMA_VERSION` (7 -> 8). The `CREATE PROPERTY GRAPH`
clause regenerates automatically.

The real design crux is **identity, not the column**. Node IDs today are global
and collidable across projects: `plan::{number}` (governance.py:764),
`file::{path}` (sessions.py:69), `rf::{sha1(plan_number, type, category, finding)}`
(findings.py:33), `bi::{sha1(plan_number, title)}` (backlog.py:37),
`session::{uuid}` (unique already). Two projects each with a Plan 224 or a
`src/app.py` would collide on the single-column primary key. DuckPGQ uses
single-column `id` PKs and every edge references `src`/`dst` by `id`, so a
composite `(project, id)` PK is expensive (it breaks the FK convention in
`EDGE_DEFS`). The pragmatic answer is to **project-qualify the colliding IDs**
(e.g. `{project}::plan::224`, `{project}::file::src/app.py`) so the PK stays
single-column and edges still resolve, **and** carry the `project` column purely
for cheap filtering and the `Project` join. Session/UUID ids need no change.

**Evidence:** `duckpgq_schema.py` (NODE_TABLES, EDGE_DEFS, single-column PKs, FK-on-id convention); id generators in governance.py:764, sessions.py:69, findings.py:33, backlog.py:37.
**Confidence:** High on the schema mechanics; Medium on the exact id-prefixing rollout (needs care in every generator + ingest).

#### Question 2: Default-scope vs cross-project query surface

**Finding:** The read surface that must learn about projects is bounded but not
trivial: ~28 governance read `SELECT`s across `review/queries.py` (13),
`graph/backlog.py` (5), `graph/sessions.py` (4), `graph/prune.py` (3),
`graph/findings.py` (2), `mcp/server.py` (1), plus the 4 code-node `SELECT`s in
`graph/search.py` (`FROM Function|Class|Method|File LIMIT ...`). All are raw SQL
strings, so scoping means injecting `WHERE project = :current` (or `IN (...)`).
Editing ~32 callsites by hand is the wrong move; the clean design is a thin
read-helper/query-builder that takes an optional `project` (default = the current
project from `resolve_root()` -> Project name) and appends the predicate, with an
explicit `project=None` / `--all-projects` for cross-project views. The
system-of-record-vs-derived-cache model is untouched -- this is read-path
ergonomics only.

**Evidence:** `rg "FROM Plan|FROM ReviewFinding|FROM Session|FROM BacklogItem|FROM Study|FROM ADR|FROM Spike"` (28 hits / 6 files) + `search.py` code-node selects.
**Confidence:** High on the count; Medium on whether a query-builder cleanly covers the MCP handlers (they assemble strings ad hoc).

#### Question 3: Path model + governance artifact layout for N projects

**Finding:** DuckPGQ property graphs are process-global (per `init_schema`
docstring), so **one shared `.scaffold/graph.duckdb` indexing all projects is
natural** -- no per-project graph file is needed. For the durable artifact, the
clean option is **one `governance.json` per project** (reusing the Plan 222 codec
unchanged, anchored at each project root) ingested into the shared graph with the
project tag, rather than one shared artifact with a `project` field per row. Per-
project artifacts preserve Plan 222/223 behavior exactly, give natural ownership,
and avoid one global merge-conflict magnet. The Plan 221 `resolve_root()` finds
the *nearest* project; a workspace adds an outer "workspace root" notion, so
Plan 225 likely needs a `resolve_workspace_root()` (outermost config or a
`workspace.yaml`) alongside the existing per-project `resolve_root()`.

**Evidence:** `init_schema` process-global note (duckpgq_schema.py:464); Plan 222 `governance_store.resolve_governance_artifact` already resolves per-root; Plan 221 `resolve_root`.
**Confidence:** High.

#### Question 4: Backward-compatible absorption of an existing single-project repo

**Finding:** Yes, and it can be zero-migration. Namespacing is **opt-in**: a lone
repo with no workspace declaration keeps today's un-namespaced ids
(`plan::224`, `file::...`) and behaves identically; the `project` column simply
defaults to the project name (from `framework.project_name` or the directory) and
no id-prefixing occurs. ID prefixing activates **only** when a workspace declares
more than one project. So existing graphs and committed `governance.json` files
remain valid as-is, and the read-helper's default-scope predicate is a no-op when
there is a single project. Migration to a multi-project workspace would re-index
(the cache is derived) and re-key ids under the project prefix at that point.

**Evidence:** ids are derived at ingest from files, and the graph is a derived cache (Plan 222/223), so re-keying happens on rebuild, not via data migration.
**Confidence:** High.

### Unexpected Discoveries

| Discovery | Impact on Parent Plan |
|-----------|----------------------|
| Node IDs are global and collidable (`plan::number`, `file::path`); identity (prefix vs composite key) is the crux, not the `project` column | Plan 225 must specify id-prefixing in every generator + ingest, gated on multi-project workspaces; keep single-column PK |
| DuckPGQ PKs are single-column and edges reference `id`; composite `(project,id)` PK is costly | Favor id-prefixing over composite keys; `project` column is a filter aid, not the identity |
| DuckPGQ property graphs are process-global; one shared graph indexes all projects | No per-project DB file; per-project `governance.json` feeds one shared derived cache |
| The read-scoping surface is ~32 raw-SQL callsites across 7 files | Plan 225 needs a query-builder/read-helper, not 32 manual edits; MCP string-assembly handlers are the trickiest |

### Blockers Discovered

| Blocker | Severity | Resolution Path |
|---------|----------|-----------------|
| None critical | Minor | The ~32-callsite read-scoping surface is the main effort; mitigate with a scoping helper. The cross-project query-VIEWS design (per-project vs federated views) is large enough to warrant the follow-up sub-study the parent study already flagged. |

### Decision

Based on spike findings:

- [x] **Proceed (modify plan)** -- the namespaced model is feasible and
  backward-compatible (opt-in; lone repos unchanged). Derive Plan 225 with:
  (1) additive schema (`Project` node + `project` column + `SCHEMA_VERSION` bump);
  (2) id-prefixing in the generators/ingest, gated on multi-project workspaces;
  (3) a read-helper/query-builder that defaults to the current project and allows
  explicit cross-project views; (4) per-project `governance.json` feeding one
  shared derived graph; (5) a `resolve_workspace_root()` alongside `resolve_root()`.
  Confirmed: namespaced is preferred over federated (daverobb 2026-06-15 -- matches
  the architecture they work in).
- A short follow-up sub-study on cross-project query *views* (per-project vs
  federated retrieval ergonomics) is **warranted** before Plan 225 finalizes the
  read-helper design, as the parent study anticipated.

### Plan Modifications Required

| Section | Change Required |
|---------|-----------------|
| File Impact Map | `duckpgq_schema.py` (Project node + project column + version bump); the ~32 read callsites via a new scoping helper; the 4 id generators (governance/sessions/findings/backlog) for opt-in prefixing; `paths.py` (`resolve_workspace_root`); `governance_store.py` (per-project artifact wiring) |
| Execution Steps | (1) additive schema; (2) id-prefixing gated on multi-project; (3) read-helper with default-scope + cross-project opt-in; (4) per-project governance artifacts; (5) workspace-root resolution; (6) backward-compat tests for a lone repo |
| Risks | ID re-keying on workspace migration; ~32-callsite scoping surface; MCP ad-hoc query strings; mitigate with the helper + re-index-on-migration (derived cache) |

### Time Tracking

| Activity | Planned | Actual |
|----------|---------|--------|
| Setup | 0.25h | 0.1h |
| Exploration | 2h | ~0.8h |
| Documentation | 0.75h | ~0.5h |
| **Total** | ~3h | ~1.4h |

---

## Spike Cleanup

- [x] No prototype code committed (analysis-only spike)
- [x] Findings recorded here; parent study references this spike
- [x] No new workflow_state blockers (none critical)
- [x] Discovered work folded into Plan 225 scope (Plan Modifications Required); cross-project query-views follow-up sub-study confirmed warranted
