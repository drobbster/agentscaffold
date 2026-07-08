# AgentScaffold Async Embedding Lane and Resident Embedder

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-async-embedding-lane
- Author: AI-assisted (Dave Robb)
- Reviewers: Dave Robb
- Approval Required: Yes (introduces a new long-lived runtime lane and an optional resident model in the MCP server; this is an orchestration/topology change requiring an architectural_design_changelog amendment and human approval before Ready)
- Security Review: None (local embedding model + local DuckDB only; no secrets, no external API, no schema migration)
- Architecture Layer(s): Cross-Cutting (orchestration / observability / dev tooling)
- Uncertainty: Medium (SPIKE-2026-06-16-agentscaffold-resident-embedding-lane validated the resident-embedder direction; implementation still needs careful scheduler/concurrency tests)
- Depends on: Plan 231 (changed-file embedding scope on `generate_embeddings`; `graph.embedding_min_interval_seconds` knob)
- Superseded By: None

## 1. Objective
Keep semantic/hybrid retrieval fresh without putting embedding generation on the
per-edit hot path. Today embeddings only run on an explicit
`scaffold index --embeddings`, so after structural edits retrieval silently
degrades to keyword (observed: MCP meta `retrieval_effective_mode: keyword`,
reason "no embeddings indexed"). This plan adds a policy-driven async embedding
lane and, optionally, a resident embedder hosted by the already long-lived MCP
server so the dominant fixed cost (model load per invocation) is paid once.

Success is testable:
- A new `graph.async_embeddings` policy (`off | idle | interval | commit`,
  default `off`) selects when embeddings refresh; `off` preserves today's
  behavior exactly.
- Under a non-`off` policy, a scoped incremental embed (reusing Plan 231's
  `file_paths` scope and content-hash skip) runs in the background on a debounce
  (`graph.embedding_min_interval_seconds`) and never runs inside the per-edit
  structural hook.
- When retrieval is degraded (embeddings missing or stale) and policy is not
  `off` and the system is idle, exactly one background embed is scheduled
  (coalesced, single-flight); MCP meta reports the scheduled/last-run state.
- If the resident-embedder option is adopted: the MCP server lazy-loads a single
  warm model, performs embedding in-process on the debounce, never blocks request
  handling, and degrades gracefully when the `search` extra is not installed.
- Embedding model and retrieval ranking are unchanged (no quality regression).

## 2. Non-Goals
- No change to the embedding model, embedding text builders, or retrieval ranking
  / reranking behavior (quality is held constant).
- No embeddings in the per-edit structural hook (`scaffold index --incremental`
  stays structural-only).
- No knowledge-graph schema migration.
- Not changing the manual `scaffold index --embeddings` path, which remains the
  authoritative full reconcile.
- Not building a general-purpose background job framework; only the embedding lane.

## 3. Constraints / Invariants
- Must not break: structural incremental indexing, full index, MCP request
  latency, or retrieval correctness.
- Backward compatibility: `async_embeddings` defaults to `off`; with the default,
  behavior is identical to today. Embeddings remain optional (`search` extra).
- Performance constraints: the async lane must be single-flight and coalesced
  (like the structural hook), must honor the debounce, and must not contend with
  the structural indexer (respect the existing `.scaffold/index.lock` discipline
  or a sibling lock).
- Resource constraints: a resident model must be lazy-loaded, single-instance,
  and bounded; it must not be loaded at all under `async_embeddings: off` or when
  the `search` extra is absent.
- Memory guard: the MCP process must not import/load the embedding model until an
  embedding run is actually scheduled under a non-`off` policy. The scheduler
  must surface load/error state in MCP meta.
- Security constraints: none introduced (local model, local DB).
- Data integrity constraints: scoped embeds must not delete or orphan out-of-scope
  embeddings; a full `scaffold index --embeddings` remains the reconcile path.
- Breaking change: No.

## 4. Current State
- Embeddings are produced only by `scaffold index --embeddings`
  (`graph/pipeline.py` -> `graph/embeddings.py::generate_embeddings`). The
  per-edit hook (`.cursor/hooks/scaffold-index.sh`) runs `--incremental` only.
- `generate_embeddings` is content-hash incremental: it skips any node whose
  `(node_id, node_type, model)` embedding already exists, so steady-state cost is
  low. The dominant fixed cost is loading the `SentenceTransformer` model on each
  process invocation.
- The MCP server (`scaffold mcp`) is a long-lived process that is otherwise idle
  between requests (observed: ~3h uptime at 0.0% CPU; live RSS before resident
  model load: ~64 MB).
- Retrieval already reports its effective mode and a reason in MCP meta
  (`retrieval_effective_mode`, `retrieval_reason`), so degradation is detectable
  programmatically.
- Plan 231 (dependency) adds an optional `file_paths` scope to
  `generate_embeddings` and a `graph.embedding_min_interval_seconds` knob
  (forward-declared there, consumed here).
- SPIKE-2026-06-16-agentscaffold-resident-embedding-lane validates the preferred
  direction: an in-process resident embedder in a background worker. Evidence:
  cached model ready; cold load 1.743s; cached reload 0.000234s; RSS high-water
  delta +35.8 MB after load and ~504.7 MB after first encode in the measurement
  process; same-process dual `DuckPGQBackend` connections can write/read an
  `EmbeddingStore` row. The scheduler must still yield to `.scaffold/index.lock`.

Data source analysis (state this lane reads):
1. Source: `EmbeddingStore` table (counts/staleness) + `File`/definition tables
   (changed-file scope), plus MCP retrieval meta.
2. Fields available: embedding presence by `(node_id, node_type, model)`; File
   `path`, `contentHash`; retrieval mode/reason from the oracle.
3. Granularity: per-node embeddings; per-file change scope; sufficient to schedule
   a scoped, coalesced embed.
4. Sample validation: confirm `EmbeddingStore` count and the retrieval
   degradation reason are readable from the MCP process before wiring auto-schedule.
5. Gaps identified: there is no current notion of "embeddings stale vs missing";
   define staleness as "changed-file nodes lacking a current-hash embedding".

## 5. Target State
1. New `GraphConfig` field `async_embeddings: "off" | "idle" | "interval" |
   "commit"` (default `"off"`). Reuses `embedding_min_interval_seconds` (Plan 231)
   as the debounce.
2. An embedding scheduler (new module, e.g. `graph/embedding_scheduler.py`) that,
   under a non-`off` policy, runs a scoped incremental embed (Plan 231
   `file_paths` scope + content-hash skip), single-flight and coalesced, honoring
   the debounce. It never runs inside the structural hook and never blocks it.
   It should reuse/parallel the existing `mcp/freshness.py` coordinator shape:
   per-root state, debounce, single-flight, coalesced pending run, daemon worker,
   and state surfaced in MCP meta.
3. Degradation-aware auto-schedule: when retrieval is degraded and the system is
   idle and policy is not `off`, schedule exactly one background embed; expose the
   scheduled/last-run/last-error state in MCP meta.
4. Trigger policies:
   - `idle`: schedule after a quiet period with no pending structural index request.
   - `interval`: schedule at most once per `embedding_min_interval_seconds`.
   - `commit`: a generated git `post-commit` (and/or `post-merge`) hook requests a
     scoped embed at commit boundaries.
   - `off`: nothing runs; no model is loaded.
5. Preferred resident embedder (spike-approved): the MCP server lazy-loads a
   single warm `SentenceTransformer` and performs embedding in-process on a
   background worker, eliminating per-invocation model load. Guarded so it
   (a) never blocks request handling, (b) loads at most once, (c) is not loaded
   under `off` or without the `search` extra, and (d) defers while the structural
   index lock is held. Keep a short-lived subprocess path as a fallback only if
   resident load/write errors prove unrecoverable in tests or production hardening.
6. `scaffold index --embeddings` is unchanged and remains the authoritative manual
   reconcile.

## 6. File Impact Map
| File | Change Type | Notes |
|-----|------------|-------|
| src/agentscaffold/config.py | Modify | add `async_embeddings` policy field to `GraphConfig` (default `"off"`); reuse `embedding_min_interval_seconds` from Plan 231 |
| src/agentscaffold/graph/embedding_scheduler.py | Add | single-flight, coalesced, debounced scheduler; scoped embed via `generate_embeddings(file_paths=...)`; staleness/degradation detection; background worker modeled after `mcp/freshness.py` |
| src/agentscaffold/graph/embeddings.py | Modify | expose a lightweight "embeddings stale/missing for scope" query; preserve process-level model cache as the resident warm model |
| src/agentscaffold/graph/pipeline.py | Modify | allow `--incremental --embeddings` to reconcile missing embeddings when no structural files changed |
| src/agentscaffold/mcp/server.py | Modify | wire degradation-aware idle scheduling; host the resident model off the request path via scheduler; report lane state in meta |
| src/agentscaffold/agents/generate.py | Modify | generate commit-boundary embedding hooks when `graph.async_embeddings: commit` |
| src/agentscaffold/agents/cursor.py | Modify | generate commit-boundary embedding hooks from the Cursor-specific generator when `graph.async_embeddings: commit` |
| src/agentscaffold/hooks/generators/*.py | Modify | optional `commit` policy: generate a git post-commit/post-merge hook that requests a scoped embed (single-flight, non-blocking) |
| src/agentscaffold/templates/scaffold_yaml.yaml.j2 | Modify | include `graph.async_embeddings: off` default in generated configs |
| docs/ai/spikes/SPIKE-2026-06-16-agentscaffold-resident-embedding-lane.md | Add | feasibility spike evidence and in-process resident decision |
| docs/configuration.md | Modify | document `graph.async_embeddings` and how it pairs with `embedding_min_interval_seconds` |
| CHANGELOG.md | Modify | document the async embedding lane + (if adopted) resident embedder |
| docs/ai/architectural_design_changelog.md | Modify (append) | amendment: new long-lived embedding lane / resident model in MCP (requires human approval) |

Consumer audit (config class change): run
`rg "GraphConfig\(" --type py agentscaffold` and add every instantiation
/ test to this map before implementing the config field.

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_embedding_scheduler.py | new logic | policy routing (off/idle/interval/commit), debounce, single-flight/coalesce, degradation-aware schedule |
| tests/test_embedding_lane_mcp.py | integration | MCP meta reports lane state; scheduling never blocks request handling; `off` loads no model |
| tests/test_incremental_and_sessions.py | regression | `--incremental --embeddings` reconciles embeddings even when the structural changeset is empty |
| tests/test_hooks_generators.py | regression | `commit` policy emits a single non-blocking git hook; no duplicates; absent under other policies |

Test approach:
- [x] Unit: scheduler honors each policy; `off` performs no work and does not import/load the embedding model.
- [x] Unit: debounce + single-flight + coalescing (back-to-back requests collapse).
- [x] Unit: degradation detection schedules exactly one embed when degraded + idle.
- [x] Integration: MCP metadata scheduling returns immediately while background work is scheduled.
- [x] Lifecycle (resident path): model is only loaded by the background embedding worker; missing `search` extra
  degrades to keyword with a clear reason instead of erroring.
- [x] Edge cases: structural index in flight (lane must defer while
  `.scaffold/index.lock` is held); `search` extra absent; empty changed-file scope
  is a no-op; model load failure is surfaced in MCP meta without crashing MCP.

## 8. Execution Steps
- [x] Step 0: Spike (2-4 hrs) -- resident embedder feasibility: resident memory
  footprint of `all-MiniLM-L6-v2`, interaction with the MCP event loop, and
  concurrency with DuckDB writes / the structural index lock. Decide in-process
  vs subprocess. Record decision in the plan and (if architectural) the changelog.
- [x] Step 1: Consumer Audit -- `rg "GraphConfig\(" --type py agentscaffold`; update File Impact Map.
- [x] Step 2: Add `async_embeddings` policy field to `GraphConfig` (default `off`) + config docs.
- [x] Step 3: Add a "stale/missing embeddings for scope" query in `embeddings.py`.
- [x] Step 4: Implement `embedding_scheduler` (single-flight, coalesced, debounced; scoped embed) + unit tests.
- [x] Step 5: Wire degradation-aware idle scheduling into the MCP server; surface lane state in meta + integration test.
- [x] Step 6: Host the resident warm model off the request path in the scheduler background worker; lifecycle tests.
- [x] Step 7: (Commit policy) extend hook generators to emit a non-blocking git post-commit/post-merge embed request; extend `test_hooks_generators`.
- [x] Step 8: Append the architectural_design_changelog amendment; obtain human approval (Approval Required: Yes).
- [x] Step 9: Update CHANGELOG + docs; run full validation.

## 9. Validation
```bash
cd .
uv run ruff format --check src/agentscaffold/graph src/agentscaffold/mcp src/agentscaffold/hooks
uv run ruff check src/agentscaffold
uv run python -m mypy src/agentscaffold/graph/embedding_scheduler.py src/agentscaffold/graph/embeddings.py src/agentscaffold/mcp/server.py
uv run python -m pytest tests/test_embedding_scheduler.py tests/test_embedding_lane_mcp.py tests/test_embeddings_resident.py tests/test_hooks_generators.py -q
uv run python -m pytest tests/ -q
```

Expected results:
- Ruff/mypy: no errors.
- Pytest: all tests pass; `off` policy is a strict no-op (no model load, no scheduling).
- MCP request latency is unaffected while a background embed runs.

## 10. Rollback Plan
The lane defaults to `async_embeddings: off`, so shipping the code changes nothing
until a project opts in. Rollback is `git revert` of the feature commit(s). No
schema migration, so a reverted binary reads the same graph. If retrieval behaves
unexpectedly, set `async_embeddings: off` and run a manual
`scaffold index --embeddings` to reconcile.

## 11. Risks & Mitigations
- Risk: resident model inflates MCP memory. Mitigation: lazy single-instance load,
  only under a non-`off` policy with the `search` extra; spike measured the live
  MCP at ~64 MB RSS before load and the measurement process at ~505 MB after first
  encode; subprocess fallback remains available if resident behavior is
  unacceptable in tests or production hardening.
- Risk: background embed contends with the structural indexer. Mitigation: respect
  the existing `.scaffold/index.lock` (or a sibling lock); single-flight + debounce;
  the lane yields to structural indexing.
- Risk: embedding work blocks MCP request handling. Mitigation: run off the request
  path (background thread/subprocess); integration test asserts latency is
  unaffected.
- Risk: auto-schedule storms (repeated scheduling). Mitigation: coalesce to one
  pending run; honor `embedding_min_interval_seconds`; schedule only when idle.
- Risk: hidden behavior change for existing installs. Mitigation: default `off`;
  no model load and no scheduling unless explicitly enabled.
- Risk: architectural drift (new long-lived lane). Mitigation: changelog amendment
  + human approval gate before Ready; keep the lane narrowly scoped to embeddings.

## 12. Completion Checklist
- [x] Spike completed and decision recorded (in-process resident preferred; subprocess fallback only)
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff clean; mypy target blocked by pre-existing `mcp/server.py` strict-typing debt, not new scheduler code)
- [x] Architectural changelog amendment added and approved
- [x] workflow_state.md updated
- [x] Session log entry added (if multi-session)
- [x] Code reviewed (self or peer)
- [x] Approval obtained (Approval Required: Yes)

## Appendix A: Pre-Implementation Review Summary (2026-06-16)

Pre-implementation review completed via the governed begin-plan chain. The graph
recorded 3 findings.

### Review Brief

The graph-oriented brief only recognized one impacted file from the plan:
`docs/ai/architectural_design_changelog.md`. It did not extract the package source
and test entries from the markdown File Impact Map, so file-based verification is
required before any implementation. The graph noted that the architecture
changelog has been modified by 9 prior plans, which is expected for a durable
architecture-history document but still means amendments should stay concise and
durable.

### Findings Recorded

#### HISTORY: Changelog Frequency

`docs/ai/architectural_design_changelog.md` has been touched by several prior
plans. Disposition: accepted, non-blocking. If this plan proceeds beyond the
spike, the changelog entry must be limited to the durable topology/lane decision
and avoid routine implementation detail.

#### PATTERN: Prior Findings Around Architecture Changelog / Test Coverage

Prior review findings exist around the changelog and test coverage. Disposition:
accepted, non-blocking. Plan 232 already requires scheduler, MCP, resident-model,
and hook-generator tests; before implementation, verify the File Impact Map
against the source tree because the graph did not parse all rows.

#### TEST_COVERAGE: Graph Did Not Find Tests For The Changelog Row

The graph flagged no tests for `docs/ai/architectural_design_changelog.md`.
Disposition: accepted, non-blocking. The changelog amendment itself is docs-only,
but the runtime lane must be covered by the test files listed in Section 7.

### Gate Status

Plan 232 is **not approved for implementation** yet. Metadata requires:
- Spike first (`Uncertainty: High`) to decide resident in-process embedder vs
  subprocess fallback.
- Human approval before Ready/In Progress because the plan introduces a new
  long-lived runtime lane and requires an architectural changelog amendment.

Recommended next action: run Step 0 as a time-boxed spike and update this plan
with the decision before requesting implementation approval.

## Appendix B: Implementation Notes / Validation Results (2026-06-16)

### Implementation Summary

Plan 232 was implemented after human approval following the Step 0 spike. The
implementation keeps the default path behavior-preserving: `graph.async_embeddings`
defaults to `"off"`, and no embedding model is loaded unless a project opts into
`idle`, `interval`, or `commit`.

Key implementation points:
- Added `GraphConfig.async_embeddings` with defensive normalization for YAML
  boolean `off` / `on` parsing. Generated `scaffold.yaml` quotes `"off"` so fresh
  projects do not trip YAML's boolean coercion.
- Added `graph/embedding_scheduler.py`: per-root runtime state, debounce,
  single-flight scheduling, coalesced pending work, structural lock deferral, and
  a daemon background worker that calls incremental embedding reconciliation.
- Wired MCP response metadata to include embedding lane state and to schedule a
  background embedding refresh when retrieval is degraded.
- Adjusted incremental `--embeddings` so a no-structure-change run can still
  reconcile missing embeddings; changed-file runs remain scoped to the affected
  neighborhood.
- Added commit-boundary embedding hook generation for `graph.async_embeddings:
  commit` via non-blocking `post-commit` and `post-merge` scripts.
- Updated package configuration docs, generated config template, package
  changelog, and architecture changelog.

### Validation Results

Commands run:
- `uv run python -m pytest tests/test_embedding_scheduler.py tests/test_embedding_lane_mcp.py tests/test_hooks_generators.py tests/test_incremental_and_sessions.py::TestIncrementalPipeline -q`
  - Result: **56 passed**, 2 dependency warnings.
- `uv run ruff check src/agentscaffold/config.py src/agentscaffold/graph/embedding_scheduler.py src/agentscaffold/graph/embeddings.py src/agentscaffold/graph/pipeline.py src/agentscaffold/mcp/server.py src/agentscaffold/hooks/generators/cursor.py src/agentscaffold/agents/generate.py src/agentscaffold/agents/cursor.py tests/test_config.py tests/test_embedding_scheduler.py tests/test_embedding_lane_mcp.py tests/test_hooks_generators.py tests/test_incremental_and_sessions.py`
  - Result: **pass**.
- `uv run python -m pytest tests/test_config.py tests/test_init.py -q`
  - Result: **20 passed**. This caught and verified the YAML `off` boolean fix.
- `uv run python -m pytest tests/ -q`
  - Initial result: **834 passed / 1 failed**, 2 dependency warnings.
  - Follow-up fix: isolated `tests/test_graph_migration.py::test_pipeline_migration_preserves_governance` from the repo-level governance artifact by pointing the test config at a temp `governance.json`.
  - Final result after follow-up: **835 passed**, 2 dependency warnings.
- `uv run python -m mypy src/agentscaffold/graph/embedding_scheduler.py src/agentscaffold/graph/embeddings.py src/agentscaffold/mcp/server.py`
  - Initial result: **blocked by pre-existing `mcp/server.py` strict-typing debt** (39 errors in old MCP decorators/helper signatures).
  - Follow-up fix: added typed MCP definition/resource helpers, typed metadata helper signatures, resource URI coercion, and plan-number narrowing.
  - Final result after follow-up: **Success: no issues found in 3 source files**.
- `uv run scaffold plan lint -p 232`
  - Result: **PASS**.

### Retrospective

What worked well:
- The Step 0 spike paid off: it made the implementation choice concrete and kept
  the resident embedder lazy, opt-in, and backgrounded.
- Reusing the existing freshness coordinator shape reduced design risk and made
  the scheduler behavior easy to test.
- The full suite caught a real YAML edge case (`off` parsed as `False`) that
  targeted tests missed; the fix is now covered by `test_config.py`.

What was harder than expected:
- The graph-oriented implementation gate did not parse the package source rows in
  the markdown File Impact Map, so direct file verification was necessary.
- `mcp/server.py` strict mypy debt made the plan-level mypy target noisy, but the
  old decorator/helper-signature errors were narrow enough to resolve in the
  follow-up hardening pass.

Discoveries not in the plan:
- YAML boolean coercion is a package-install user experience hazard for policy
  names like `off`; generated configs should quote such values.
- A no-change incremental embedding run needed special handling to repair the
  exact degraded state Plan 232 targets: no embeddings indexed, no structural
  changes pending.

What would we do differently:
- Add config-template parse tests whenever introducing string policy values that
  overlap YAML's boolean/null vocabulary.
- Keep scoped mypy targets in plans, but budget time for narrow legacy type fixes
  when a touched file is large and previously unchecked.

Actionable follow-ups:
- None added to the backlog.

## Appendix C: Post-Implementation Verification Tool Output (2026-06-16)

Governed closeout completed via the Plan 232 completion chain. The graph recorded
2 retrospective findings and no backlog items.

### Post-Implementation Verification

[PASS] **plan_compliance**: All 2 planned files recognized by the graph exist.

[WARN] **signatures**: 0 definitions found across graph-recognized planned files.
Disposition: accepted. The closeout graph only recognized the docs/spike rows from
the File Impact Map, not the package source/test rows, so direct source validation
and pytest/ruff results in Appendix B are authoritative.

[PASS] **wiring**: 0 import/call references verified.

[WARN] **test_delta**: Tests found for 0/2 graph-recognized source files
(`docs/ai/spikes/SPIKE-2026-06-16-agentscaffold-resident-embedding-lane.md`,
`docs/ai/architectural_design_changelog.md`). Disposition: accepted. These are
documentation artifacts; runtime behavior is covered by the test files listed in
Section 7.

### Graph-Generated Retrospective Context

[VOLATILITY] `docs/ai/architectural_design_changelog.md` has been modified by
10 plans including this one. Disposition: accepted. The Plan 232 amendment is
kept narrowly focused on the durable embedding-lane topology.

[HOT_FILE] `docs/ai/architectural_design_changelog.md` is among the most
frequently modified files touched by this plan. Disposition: accepted; no backlog
item added because this is expected for the architecture-history document and no
near-term concrete cleanup was identified.
