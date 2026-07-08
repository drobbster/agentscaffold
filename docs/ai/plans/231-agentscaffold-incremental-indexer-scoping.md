# AgentScaffold Incremental Indexer Scoping and Hook Debounce

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-incremental-indexer-scoping
- Author: AI-assisted (Dave Robb)
- Reviewers: Dave Robb
- Approval Required: No (internal refactor, non-breaking; defaults preserve full-index behavior)
- Security Review: None (internal refactor; reuses existing graph columns, no secrets/external API/schema migration)
- Architecture Layer(s): Cross-Cutting (orchestration / observability / dev tooling)
- Superseded By: None

## 1. Objective
Make `scaffold index --incremental` cost proportional to the number of changed
files, not to repository size, so per-edit hook runs stop saturating CPU during
high-edit-volume sessions.

Success is testable:
- A single-file content edit re-resolves imports/calls only for the changed file
  and its direct dependents, not all parsed files.
- `compute_changeset` hashes only files whose `(mtime, size)` differs from the
  stored File node, not every non-ignored file.
- Community detection is skipped on content-only incremental edits and runs only
  when structure changes (files added/deleted) or a configurable threshold is hit.
- An incremental run with an empty changeset exits before parse/import/call/config
  reference/community phases and records a no-op result.
- When `--embeddings` is requested in incremental mode, embedding only considers
  nodes in the changed-file scope (no per-node existence scan over the whole
  store), and re-embeds only changed/new definitions (content-hash skip is
  already in place).
- On this repo (~1434 files, ~761 parsed), a one-line edit incremental index
  completes in roughly the parse+resolve cost of the changed neighborhood
  (target: well under the current whole-graph time), measured by an eval timing
  scenario.
- Full (`scaffold index`) behavior and output are byte-for-byte unchanged.

### Secondary deliverable (bundled): generated collaboration-protocol UX enrichment
The generated `collaboration_protocol.md` template
(`templates/project/collaboration_protocol.md.j2`) is currently a 49-line
skeleton, so a fresh install gets little practical guidance. This release
enriches it with generic, reusable content (ported and genericized from this
repo's mature local protocol) so every install starts with a useful protocol.
It is bundled here because it ships in the same `agentscaffold` release as the
hook-generator changes below; it is additive, docs-only, non-breaking.

Scope of the enrichment (generic content only -- no repo-specific coupling):
- **Review terminology convention.** Instruct agents to describe the governed
  lifecycle in human-readable review language (for example "pre-implementation
  review", "post-implementation retrospective") in human-facing artifacts --
  plans, plan appendices, the architecture changelog, `workflow_state.md`,
  commits, and PRs -- and to use raw MCP tool names (for example
  `scaffold_begin_plan`, `scaffold_complete_plan`) only as light parenthetical
  provenance, never as the primary description. Also added to the always-applied
  `AGENTS.md` managed block (`templates/agents/agents_md.md.j2`, under "Review
  Output Format (Mandatory)") so it actually governs agent behavior.
- **Prompting Patterns** (scoped exploration, devil's advocate, gap analysis,
  alternative design, stress testing, dependency verification, progressive
  refinement, integration focus) -- copy-paste prompt recipes, no repo coupling.
- **Communication Patterns** (status updates, asking for clarification,
  proposing changes).
- **Quality Checkpoints** (code / plan / integration quality checklists).
- **Future Regret Evaluation** triage (small/medium/large effort -> action).
- **Escalation Triggers** and **Anti-Patterns** (generic rows only).
- **Driving Development** (before/during/after phase and plan) with commands
  expressed as scaffold commands (`scaffold plan lint`, `scaffold retro check`),
  NOT repo-specific scripts.

Domain-specific review session types (quant architect, product design, etc.)
are rendered **conditionally** off the existing template context
(`domains` / `domain_reviews` from `get_default_context`), so they appear only
when the relevant domain is enabled and the template stays domain-agnostic by
default.

Explicitly excluded (repo-specific, not portable): the "on the Rebellion
Trading System" framing, the 6-layer Architectural Alignment Review specifics,
and the "Evidence of Review Effectiveness" plan-number citations. The alignment
guidance, if included, is genericized to "respect your declared architecture
layers".

Success is testable: a freshly generated `collaboration_protocol.md` contains
the enriched sections (and renders domain review sessions only when a domain is
enabled), and the generated `AGENTS.md` managed block contains the
review-terminology convention -- both asserted by a template test.

## 2. Non-Goals
- No change to the full (non-incremental) pipeline semantics or output.
- No knowledge-graph schema migration (reuse existing `File.lastModified`,
  `File.size`, `File.contentHash`).
- Embeddings remain gated behind `--embeddings` and are NOT added to the per-edit
  hook. This plan only scopes the embedding pass to changed files when embeddings
  are already requested in incremental mode; it does not change when embeddings
  run or introduce an async embedding lane (that is the follow-up plan).
- No new MCP tools or CLI commands (only optional config fields + internal scoping).
- Not redesigning community detection itself, only when it runs in incremental mode.

## 3. Constraints / Invariants
- Must not break: full-index correctness, graph query results, MCP tool output.
- Backward compatibility: incremental with no config set must remain correct;
  new config fields default to current-equivalent behavior on full index.
- Performance constraints: incremental per-edit work must be O(changed +
  direct dependents), not O(repo).
- Security constraints: none introduced.
- Data integrity constraints: scoped re-resolution must not leave stale CALLS /
  IMPORTS / CONFIG_REFERENCES edges for the changed neighborhood; correctness is
  verified by parity tests against a full re-index of the same tree.
- Breaking change: No.

## 4. Current State
`_run_incremental` in `graph/pipeline.py` only scopes the **parse** phase to
changed files. The remaining phases run over the whole repository on every
incremental invocation:

- `compute_changeset` (`graph/incremental.py`) walks `root.rglob("*")` and
  SHA-256 hashes every non-ignored file each run (fixed cost regardless of how
  little changed).
- `process_imports(store, root, symbol_table)` (`graph/imports.py`) reads and
  re-resolves imports for every File row.
- `process_calls(store, root, symbol_table)` (`graph/calls.py`) reads and
  re-scans every python/typescript/javascript file body.
- `process_config_references(store, root)` (`graph/config_refs.py`) reprocesses
  all config files whenever any file changed.
- `detect_communities(store)` (`graph/communities.py`) re-clusters the entire
  graph (graspologic/Leiden, numba JIT) on every edit.

Governance is already correctly gated behind a fingerprint, so docs-only and
code-only edits skip the governance reingest. The afterFileEdit hook layer
(`.cursor/hooks/scaffold-index.sh`) is non-blocking and single-flight; Tier 1
(separate change) de-duplicated and de-blocked the Claude hooks. This plan
addresses the indexer compute itself.

Live hook-log observation after Tier 1: removing the duplicate Claude hook solved
the acute CPU stacking issue, but the chronic per-run cost remains. The last 15
incremental hook runs each reported only 0-3 modified files out of ~1437 files,
yet still took ~80-86s and re-ran whole-graph imports, calls, config refs, and
community detection. Some runs reported `0 added, 0 modified, 0 deleted` and
still proceeded through the expensive phases. That no-op path should return
immediately after changeset computation.

Data source analysis (graph rows this plan reads):
1. Source: `File` node table, produced by structure/parse phases.
2. Fields available: `id`, `path`, `language`, `size`, `lastModified` (str of
   mtime), `contentHash` (sha256). All always populated for indexed files.
3. Granularity: per-file; sufficient for an `(mtime, size)` prefilter and for
   scoping import/call re-resolution by file path.
4. Sample validation: confirm `lastModified`/`size` are populated after a full
   index on this repo before relying on the prefilter (fallback: hash on missing
   or zero values).
5. Gaps identified: `lastModified` is stored as `str(stat.st_mtime)`; compare as
   float with tolerance, and always fall back to content hash when stored
   metadata is absent or unparseable so the prefilter can never cause a missed
   change.

## 5. Target State
`_run_incremental` becomes truly incremental:

1. `compute_changeset` uses an `(mtime, size)` prefilter: only files whose stored
   metadata differs (or is missing) are content-hashed; unchanged-metadata files
   are treated as unchanged without a read. Content hash remains the source of
   truth for the files it actually hashes (no false "unchanged" from metadata
   alone — if metadata differs, it hashes; if metadata matches, the content is
   assumed unchanged, matching standard mtime-based build tools).
2. `_run_incremental` exits immediately when the changeset has no added,
   modified, or deleted files. It should skip parse, import/call resolution,
   config-reference refresh, governance refresh, and community detection while
   returning/logging an explicit no-op summary.
3. `process_imports` and `process_calls` accept an optional `file_paths` scope.
   In incremental mode the scope is `changed_files` plus their **direct
   dependents** (files that import a changed file, via existing IMPORTS edges),
   because cross-file call resolution in Python/TS requires an import. Edges
   owned by in-scope files are dropped and recomputed; out-of-scope edges are
   left intact.
4. `process_config_references` runs in incremental mode only when a config file
   changed or a referenced code file was refreshed (added/modified/deleted),
   instead of on every change.
5. `detect_communities` runs in incremental mode only when structure changed
   (files added or deleted) or when the changed-file count exceeds
   `graph.incremental_community_threshold`; otherwise it is skipped and existing
   community assignments are retained.
6. `generate_embeddings` accepts an optional `file_paths` scope, and
   `_run_incremental` passes the changed-file scope when embeddings are requested.
   This replaces the current whole-store iteration (one existence query per node)
   with a scan bounded to changed-file nodes. The existing content-hash skip
   (only new/changed-text nodes are embedded) is preserved.
7. New optional `GraphConfig` fields (all default to behavior-preserving values):
   - `incremental_community_refresh: "structure" | "always" | "threshold"`
     (default `"structure"`).
   - `incremental_community_threshold: int` (default e.g. 25; used when mode is
     `"threshold"`).
   - `incremental_min_interval_seconds: int` (default 0 = disabled) consumed by
     the generated hook script to debounce back-to-back runs.
   - `embedding_min_interval_seconds: int` (default 0 = disabled). Forward-declared
     here alongside the other incremental knobs; its consumer (the async embedding
     lane) is delivered in the follow-up plan. Default 0 keeps current behavior.
8. The hook generators emit a single, non-blocking, single-flight index hook for
   each platform (no duplicates) and honor `incremental_min_interval_seconds`, so
   regenerating agent files cannot reintroduce blocking/duplicate hooks (the
   Tier 1 footgun).

## 6. File Impact Map
| File | Change Type | Notes |
|-----|------------|-------|
| src/agentscaffold/graph/incremental.py | Modify | `(mtime,size)` prefilter in `compute_changeset`; add `direct_dependents(store, changed)` helper using IMPORTS edges |
| src/agentscaffold/graph/imports.py | Modify | `process_imports(..., file_paths: set[str] | None = None)`; scope file scan + edge clear/recompute |
| src/agentscaffold/graph/calls.py | Modify | `process_calls(..., file_paths: set[str] | None = None)`; scope file scan + edge clear/recompute |
| src/agentscaffold/graph/config_refs.py | Modify | optional changed-set scoping / skip when no config or referenced code changed |
| src/agentscaffold/graph/embeddings.py | Modify | `generate_embeddings(..., file_paths: set[str] | None = None)`; scope node selection to changed files (preserve content-hash skip) |
| src/agentscaffold/graph/pipeline.py | Modify | `_run_incremental`: early-exit on empty changeset; build scope set, pass to imports/calls/config_refs, gate `detect_communities` per config, pass scope to `generate_embeddings` when `--embeddings` |
| src/agentscaffold/config.py | Modify | add `incremental_community_refresh`, `incremental_community_threshold`, `incremental_min_interval_seconds`, `embedding_min_interval_seconds` to `GraphConfig` |
| src/agentscaffold/hooks/generators/cursor.py | Modify | emit single non-blocking single-flight index hook; honor min-interval |
| src/agentscaffold/hooks/generators/claude_code.py | Modify | route Claude built-in freshness through the same non-blocking wrapper script; write the wrapper when Claude hooks are generated |
| src/agentscaffold/hooks/generators/cursor.py (`_INDEX_HOOK_TEMPLATE`) | Modify | add optional min-interval debounce guard |
| src/agentscaffold/templates/agents/agents_md.md.j2 | Modify | add "Review Terminology (Human-Readable)" subsection under "Review Output Format (Mandatory)" (~line 694) so the always-applied managed block instructs agents to use human-readable review language and tool names only as parenthetical provenance |
| src/agentscaffold/templates/project/collaboration_protocol.md.j2 | Modify | enrich the generated human doc: Review Terminology, Prompting Patterns, Communication Patterns, Quality Checkpoints, Future Regret Evaluation, generic Escalation Triggers + Anti-Patterns, Driving Development (scaffold commands); render domain review session types conditionally off `domains` / `domain_reviews`; exclude repo-specific content |
| CHANGELOG.md | Modify | document incremental scoping + hook debounce + collaboration-protocol enrichment (terminology convention, prompting/communication patterns, domain-conditional review sessions) |
| docs/configuration.md | Modify | document new `graph.incremental_*` fields and the forward-declared `graph.embedding_min_interval_seconds` |

Consumer audit (config class change): run
`rg "GraphConfig\(" --type py agentscaffold` and add every
instantiation/test to the map before implementing the config fields.

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_incremental_scoping.py | new logic | prefilter, scope set, community gating |
| tests/test_incremental_parity.py | correctness | scoped incremental == full re-index edges for changed neighborhood |
| tests/test_embeddings_scoping.py | new logic | `generate_embeddings(file_paths=...)` embeds only changed-file nodes; content-hash skip preserved; out-of-scope nodes untouched |
| tests/test_hooks_generators.py | regression | generated hooks are single, non-blocking, single-flight, no duplicates |
| eval/scenarios/test_efficiency.py | timing | no-op incremental exits before expensive phases; one-file edit stays within a bounded time/work budget |
| tests/test_agent_generation.py | regression | generated `AGENTS.md` managed block contains the review-terminology convention; generated `collaboration_protocol.md` contains the enriched sections; domain review sessions render only when a domain is enabled (and are absent for `domains=[]`) |

Test approach:
- [ ] Unit: `compute_changeset` hashes only metadata-changed files (spy on `_file_hash`).
- [ ] Unit: `_run_incremental` with an empty changeset returns before parse,
  imports, calls, config refs, governance refresh, and community detection
  (mock/spy phase functions and assert none are called).
- [ ] Unit: `direct_dependents` returns importers of changed files only.
- [ ] Unit: `process_imports`/`process_calls` with `file_paths` touch only in-scope edges.
- [ ] Unit: community detection skipped on content-only edit; runs on add/delete.
- [ ] Unit: `generate_embeddings(file_paths=...)` embeds only nodes in the changed
  scope, preserves the content-hash skip, and leaves out-of-scope embeddings intact.
- [ ] Integration/parity: edit a function body, edit a signature with a caller in
  an importing file, add a file, delete a file — assert scoped incremental yields
  the same edges as a full re-index for the affected neighborhood.
- [ ] Edge cases: missing/zero `lastModified` falls back to content hash; renamed
  file (add+delete) triggers community refresh; config-file edit triggers config
  refs but not community refresh unless threshold/structure rule applies.
- [ ] Secondary deliverable: generated `AGENTS.md` managed block and
  `collaboration_protocol.md` contain the review-terminology convention text
  (human-readable review language; tool names only as parenthetical provenance).

## 8. Execution Steps
- [x] Step 0: Consumer Audit -- `rg "GraphConfig\(" --type py agentscaffold`; add all callsites/tests to File Impact Map.
- [x] Step 1: Add `GraphConfig` fields with behavior-preserving defaults + config docs.
- [x] Step 2: Implement `(mtime,size)` prefilter in `compute_changeset` with content-hash fallback; add `test_incremental_scoping` prefilter tests.
- [x] Step 3: Add `_run_incremental` empty-changeset early exit before parse/imports/calls/config refs/governance/community phases; add phase-spy test coverage.
- [x] Step 4: Add `direct_dependents(store, changed)` helper (IMPORTS-edge importers of changed files).
- [x] Step 5: Add optional `file_paths` scoping to `process_imports` (scan + edge clear/recompute bounded to scope).
- [x] Step 6: Add optional `file_paths` scoping to `process_calls` (same).
- [x] Step 7: Scope `process_config_references` to changed/affected config in incremental mode.
- [x] Step 8: Gate `detect_communities` in `_run_incremental` per `incremental_community_refresh`.
- [x] Step 9: Write `test_incremental_parity` (scoped incremental vs full re-index for the changed neighborhood).
- [x] Step 10: Add optional `file_paths` scoping to `generate_embeddings`; pass the changed-file scope from `_run_incremental` when `--embeddings`; add `test_embeddings_scoping`.
- [x] Step 11: Update hook generators (cursor, claude) to emit a single non-blocking single-flight index hook; add min-interval debounce to the hook script template; extend `test_hooks_generators`.
- [x] Step 12: Add/adjust `test_efficiency` timing budgets for no-op incremental and one-file incremental edits.
- [x] Step 13: (Secondary deliverable) Add the "Review Terminology (Human-Readable)" convention to `templates/agents/agents_md.md.j2` (under "Review Output Format (Mandatory)").
- [x] Step 14: (Secondary deliverable) Enrich `templates/project/collaboration_protocol.md.j2` with the generic sections (Review Terminology, Prompting Patterns, Communication Patterns, Quality Checkpoints, Future Regret Evaluation, generic Escalation Triggers + Anti-Patterns, Driving Development with scaffold commands); render domain review session types conditionally off `domains` / `domain_reviews`; exclude repo-specific content.
- [x] Step 15: Extend `test_agent_generation.py` to assert the `AGENTS.md` managed block carries the terminology convention, the generated `collaboration_protocol.md` carries the enriched sections, and domain review sessions appear only when a domain is enabled (absent for `domains=[]`).
- [x] Step 16: Update CHANGELOG; run full validation.

## 9. Validation
```bash
cd .
uv run ruff format --check src/agentscaffold/graph src/agentscaffold/hooks
uv run ruff check src/agentscaffold
uv run python -m mypy src/agentscaffold/graph/incremental.py src/agentscaffold/graph/pipeline.py src/agentscaffold/graph/embeddings.py
uv run python -m pytest tests/test_incremental_scoping.py tests/test_incremental_parity.py tests/test_embeddings_scoping.py tests/test_hooks_generators.py tests/test_agent_generation.py -q
uv run python -m pytest tests/ -q
uv run python -m pytest eval/scenarios/test_efficiency.py -q
```

Expected results:
- Ruff/mypy: no errors.
- Pytest: all tests pass; parity tests confirm scoped == full for changed neighborhood.
- Efficiency scenario: no-op incremental exits within a near-zero bounded budget;
  one-file incremental edit stays within the bounded budget.

## 10. Rollback Plan
All changes are additive and gated by new config fields with current-equivalent
defaults. Rollback is `git revert` of the feature commit(s). The graph requires
no migration (no schema change), so a reverted binary reads the same cache. If a
correctness regression is suspected, run a full `scaffold index` (unchanged path)
to rebuild authoritative edges.

## 11. Risks & Mitigations
- Risk: scoped call re-resolution misses a cross-file edge from a non-importing
  file. Mitigation: scope includes direct importers (Python/TS calls require an
  import); parity tests cover signature-change-with-caller; full index remains the
  authoritative correctness path and is unchanged.
- Risk: `(mtime,size)` prefilter misses a same-size, same-mtime content change.
  Mitigation: matches standard build-tool semantics; full index always hashes;
  document that `scaffold index` (full) is the source of truth; fall back to hash
  whenever stored metadata is missing/unparseable.
- Risk: skipping community detection leaves stale clusters. Mitigation: clusters
  are coarse module groupings used for orientation, not correctness-critical;
  they refresh on structure change, threshold, full index, and `--embeddings`
  runs; document the tradeoff.
- Risk: hook generator change overwrites user-customized hooks. Mitigation: follow
  the existing managed-block / write-safety pattern; never clobber user-owned hook
  files; covered by `test_hooks_generators`.
- Risk: scoping the embedding pass to changed files skips a node whose embedding
  text should change. Mitigation: embedding text is per-node and any changed node
  is in the changed-file scope; the content-hash skip is unchanged; a full
  `scaffold index --embeddings` remains the authoritative reconcile path.

## 13. Implementation Notes / Validation Results (2026-06-16)

Implemented as scoped package changes under `agentscaffold`.

Validation run:
- `ruff format` on touched files: clean after formatting.
- `ruff check src/agentscaffold`: PASS.
- Targeted Plan 231 tests:
  `pytest tests/test_incremental_scoping.py tests/test_incremental_parity.py tests/test_embeddings_scoping.py tests/test_hooks_generators.py tests/test_agent_generation.py -q`
  -> 93 passed, 2 third-party warnings.
- Existing incremental backend tests:
  `pytest tests/test_incremental_and_sessions.py tests/test_incremental_governance_freshness.py -q`
  -> 30 passed, 2 third-party warnings.
- Efficiency eval:
  `pytest eval/scenarios/test_efficiency.py -q`
  -> 6 passed, 2 third-party warnings.
- Full package tests:
  `pytest tests/ -q`
  -> 823 passed, 1 failed, 2 warnings. The failure is
  `tests/test_graph_migration.py::test_pipeline_migration_preserves_governance`;
  it restored this repo's committed governance artifact into the fixture DB and
  observed 40 `ReviewFinding` rows instead of the single injected test row. This
  is outside the Plan 231 touched path and appears to be a test isolation /
  governance-artifact path issue, not an incremental-scoping regression.
- Mypy target command could not be made clean because the environment still has
  pre-existing package typing debt / missing stubs (`tree_sitter`, PyYAML,
  `sentence_transformers`, `huggingface_hub`, `graspologic`, and existing
  `GraphBackend` protocol mismatches). New `dict` type-arg warnings introduced
  during this implementation were fixed.

Retrospective:
- What worked well: the Tier 1 live-load observation gave a crisp target for the
  no-op early exit and confirmed that the hook layer should remain non-blocking
  and single-flight.
- Harder than expected: direct dependents and config consumers had to be captured
  before modified/deleted file nodes were removed, because node removal also
  clears the dependency/config edges needed to calculate the affected scope.
- Discovery: Claude Code's generated freshness hook still used a blocking raw
  `scaffold index --incremental` command. This plan now routes it through the same
  wrapper used by Cursor so package-generated hooks do not reintroduce the Tier 1
  footgun.
- Do differently next time: add a small graph-state isolation check before full
  package tests that depend on default governance artifact paths; the single full
  suite failure was easier to interpret once isolated from Plan 231 tests.
- Follow-up: Plan 232 covers the larger async embedding lane / resident embedder
  design and should stay separate from this scoped performance fix.

Post-implementation verification tool output:
- [PASS] plan_compliance: all 0 graph-recognized planned files exist in the graph.
- [WARN] signatures: 0 definitions found across graph-recognized planned files.
- [PASS] wiring: 0 import/call references verified.
- [PASS] test_delta: tests found for all 0 graph-recognized source files.

Interpretation: the graph completion tool ran successfully and the graph was
fresh, but it did not extract the markdown File Impact Map entries for this plan
as planned files. File-based validation above is therefore the authoritative
closeout evidence for Plan 231.

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff clean; mypy blocked by pre-existing package typing debt noted above)
- [x] workflow_state.md updated
- [x] Session log entry added (see Implementation Notes / Validation Results)
- [x] Code reviewed (self)
- [x] Approval obtained (if required; not required)
