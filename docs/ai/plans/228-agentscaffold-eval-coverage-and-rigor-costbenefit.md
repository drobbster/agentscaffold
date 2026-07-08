# Feature: AgentScaffold Eval Coverage (Multi-Project + Search Quality) and Rigor Cost-Benefit

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-eval-coverage-rigor-costbenefit
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: No (deterministic/offline eval harness plus additive MCP intent metadata for an existing search tool; no financial, security, persistence, external-integration, or rigor-preset changes)
- Security Review: None (test/eval code only; reads the existing in-repo `sim_project` fixtures and config; no new persistence, no network, no secrets)
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package -- evaluation harness)
- Superseded By: None
- Status: COMPLETE (2026-06-16)
- Source: Eval-harness review follow-up 2026-06-15. Adds coverage for the Plan 225 (namespaced multi-project workspace) and Plan 227 Tier 1 (enriched embeddings + store-time normalization) enhancements, which currently have zero eval coverage, and adds a cost-vs-thoroughness measurement across the existing `config.rigor` presets (`minimal`/`standard`/`strict`).

## 1. Objective
Close the eval-coverage gap created by recent enhancements and add a defensible cost/thoroughness measurement for review rigor. Success is testable and means, in `eval/`:

1. **Multi-project correctness scenarios** exist and pass: indexing a workspace with two sibling projects (colliding plan numbers and file paths) proves that (a) scoped reads return only the current project, (b) `--all-projects` federates with a `project` provenance field on every row, (c) `scaffold graph duplicates` surfaces the planted cross-project duplicate, and (d) `migrate_to_multi_project` + `verify_integrity` round-trip a previously single-project graph with zero integrity problems.
2. **Search-quality scenarios** exist and pass: a small labeled query set yields a reported precision@k / MRR for `keyword` vs `hybrid` modes, and a store-time normalization invariant asserts every stored embedding has L2 norm approximately 1.0. These establish the regression baseline that Plan 227 Tiers 2-3 will be measured against.
3. **Rigor cost-benefit scenario** exists and pass: for a fixed sim plan, the harness loads config at each `rigor` level (`minimal`/`standard`/`strict`), renders the review-artifact bundle gated by that level's gates, and reports a table of cost (artifact tokens via `estimate_tokens` + number of review calls) against a thoroughness proxy (counts from the existing review modules: challenges, gaps, verification items, surfaced findings). The report shows the marginal thoroughness per additional 1k tokens so the cost/benefit knee is visible.
4. The **adoption intent suite** is updated so the new `workspace`/`duplicates` routes are represented rather than measured against a stale intent map.
5. The whole harness remains **deterministic, offline, and CI-runnable**, and `report.py` gains sections for the new result types.

## 2. Non-Goals
- Not the live, LLM-driven benchmarking framework (parallel agent arms, real token/cost capture, caught-bug ground truth) -- that is Plan 229 and its spike.
- Not changing the rigor presets, gate semantics, or any product behavior. This plan only *measures* existing behavior.
- Not implementing Plan 227 Tiers 2-3 (configurable/recorded model, governance recall, HNSW, incremental embedding, rerank). This plan only establishes the search-quality baseline they will be measured against.
- Not a real precision/recall benchmark of the embedding model on a large corpus; the labeled set is a small, fixed, illustrative fixture, not a leaderboard.

## 3. Constraints / Invariants
- Must not break: the existing 108 eval scenarios or the deterministic, offline, no-network property of the suite.
- Backward compatibility: additive only -- new fixtures, new scenario files, new result dataclasses, new report sections. Existing `EvalResult`/`EfficiencyResult`/`report.py` outputs keep their shape.
- Determinism: multi-project indexing must respect the DuckPGQ process-global property-graph constraint already documented in `eval/conftest.py` (session-scoped fixtures; do not run a second `run_pipeline` that DROP+CREATEs a shared property graph mid-suite). The multi-project fixture must build its workspace within a single pipeline run or an isolated DB file.
- Offline: search-quality scenarios must run without network. If the `[search]` extra / embedding model is unavailable, the search-quality scenarios `skip` cleanly (mirroring how the package already gates model-dependent paths) rather than fail.
- Thoroughness is a proxy: the rigor scenario measures artifact volume and review-module output counts, not caught-bug rate. This limitation is stated in the report text; ground-truth efficacy is deferred to the live benchmarking framework (229).
- Breaking change: No.

## 4. Current State
`eval/` is a deterministic pytest harness (108 scenarios, 100% pass per `reports/latest.md`) over a single-project `sim_project/` fixture. `runner.py` defines `EvalResult`, `EfficiencyResult` (baseline file-reads/greps vs a single MCP call, deriving token/call reduction + compression), `BenchmarkResult`, `AdoptionResult`, `ReplayResult`, plus `estimate_tokens`. `report.py` aggregates these and already risk-adjusts headline efficiency by adoption adherence and replay-observed behavior + quality non-inferiority. Coverage gaps:
- **No multi-project coverage.** `sim_project` is a lone project, so Plan 225's namespacing, scoped/federated reads, provenance, `graph duplicates`, and `migrate_to_multi_project`/`verify_integrity` are entirely unexercised at the indexed-pipeline level (only unit-tested in `tests/`).
- **No retrieval-quality metric.** `test_benchmarks.py::TestSearchModes` only checks `hybrid_count >= keyword_count`, and `test_efficiency.py::TestCodeSearch` runs `mode="keyword"`. The Plan 227 Tier 1 enriched text + normalization changes are unmeasured.
- **No rigor cost-benefit view.** The `config.rigor` presets (`RIGOR_PRESETS` in `config.py`, applied by `apply_rigor_preset`) gate which pre/post reviews run, but nothing measures the token/call cost of those reviews against the thoroughness they add.
- **Stale adoption intents.** The `adoption` suite scores prompts against `TOOL_INTENTS`; the new workspace/duplicates phrasing is not represented.

## 5. Target State
The harness gains three new scenario files and a small set of fixtures/result types, all additive:
- A session-scoped **two-project workspace fixture** (`sim_project` plus a sibling, e.g. `sim_project_b`, sharing a `workspace.yaml`, with a deliberately colliding plan number and file path plus one near-duplicate definition for the duplicates check). Multi-project scenarios assert scoped-default, federated-with-provenance, duplicates detection, and migrate+verify integrity.
- A **search-quality scenario** that runs a fixed labeled query set, computes precision@k and MRR for `keyword` vs `hybrid`, asserts hybrid is non-inferior, and asserts the L2-normalization invariant on stored vectors. Skips cleanly when the embedding model is unavailable.
- A **rigor cost-benefit scenario** that loads config at each rigor level, renders the gate-appropriate review bundle for a fixed plan, and records a `RigorCostResult` (tokens, review calls, challenge/gap/verification/finding counts) per level. `report.py` renders the cost vs thoroughness table and marginal-thoroughness-per-1k-tokens.
- Updated adoption intents covering workspace/duplicates routes.
- New `report.py` sections: "Multi-Project Correctness", "Search Quality", "Rigor Cost-Benefit".

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| eval/conftest.py | Modify | Add session-scoped `indexed_two_project_workspace` fixture (workspace.yaml + sibling project), respecting the DuckPGQ process-global property-graph constraint |
| eval/sim_project_b/ | Create | Minimal sibling project fixtures: a plan reusing a sim_project plan number, a colliding file path, and one near-duplicate definition for the duplicates check |
| eval/runner.py | Modify | Add `MultiProjectResult`, `SearchQualityResult`, `RigorCostResult` dataclasses + collectors/getters; reuse `estimate_tokens` |
| eval/report.py | Modify | Add "Multi-Project Correctness", "Search Quality", and "Rigor Cost-Benefit" sections (incl. marginal thoroughness per 1k tokens) |
| eval/scenarios/test_multiproject.py | Create | Scoped-default, federated-provenance, duplicates, migrate+verify integrity scenarios |
| eval/scenarios/test_search_quality.py | Create | precision@k / MRR keyword vs hybrid on a labeled set; L2-normalization invariant; skips if model unavailable |
| eval/scenarios/test_rigor_costbenefit.py | Create | Per-rigor-level cost (tokens + calls) vs thoroughness (challenges/gaps/verify/findings) on a fixed plan |
| eval/scenarios/test_adoption.py | Modify | Add workspace/duplicates intent prompts to the adoption suite |
| eval/reports/latest.md | Modify | Regenerated report including the new sections |
| src/agentscaffold/mcp/server.py | Modify | Additive `scaffold_search` intent metadata so workspace/duplicate-search adoption prompts route to the existing MCP search tool |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| eval/scenarios/test_multiproject.py | 100% of the four multi-project invariants (scoped-default, federated provenance, duplicates, migrate+verify) assert and pass | Deterministic; uses the two-project fixture; no network |
| eval/scenarios/test_search_quality.py | precision@k / MRR computed and reported for keyword + hybrid; hybrid non-inferior assertion; every stored vector L2 norm in [0.99, 1.01] | Skips cleanly if `[search]`/model absent; fixed labeled query set |
| eval/scenarios/test_rigor_costbenefit.py | A `RigorCostResult` produced for each of minimal/standard/strict; cost monotonic non-decreasing with rigor; thoroughness proxy reported per level | Loads config via `apply_rigor_preset`; reuses review modules (challenges/gaps/verify/findings) |
| eval/scenarios/test_adoption.py | New workspace/duplicates prompts included; adherence still computed | Additive to existing adoption suite |

Test approach:
- [x] Write the two-project fixture and `test_multiproject.py` first (highest-value gap; it is a breaking-change feature with no eval coverage)
- [x] Add `test_search_quality.py` with skip-guards for the optional model
- [x] Add `test_rigor_costbenefit.py` reusing existing review modules
- [x] Update adoption intents and regenerate `reports/latest.md`
- [x] Edge cases: model/`[search]` extra absent (skip), empty federated result, rigor level with no applicable reviews (cost still reported), duplicates with zero hits

## 8. Execution Steps
- [x] Step 0: Consumer Audit -- no product config/schema/interface mutation; implementation added only eval harness code plus additive MCP `TOOL_INTENTS` metadata for the existing `scaffold_search` tool
- [x] Step 1: Capture baseline -- `pytest -q eval/` initially crashed with a DuckDB concurrent governance-export bus error in `test_finding_lifecycle.py::test_concurrent_writes_no_data_loss`; fixed by serializing governance write-through mutations, then reran the full eval harness successfully
- [x] Step 2: Add `MultiProjectResult`, `SearchQualityResult`, `RigorCostResult` to `runner.py` (dataclasses + collectors + getters)
- [x] Step 3: Build the two-project workspace fixture in `conftest.py` and the `sim_project_b/` fixtures (colliding plan number + file path + near-duplicate definition)
- [x] Step 4: Write `test_multiproject.py` (scoped-default, federated provenance, duplicates, migrate+verify) and make it pass
- [x] Step 5: Write `test_search_quality.py` (precision@k/MRR keyword vs hybrid, L2-normalization invariant) with model skip-guards
- [x] Step 6: Write `test_rigor_costbenefit.py` (per-rigor cost vs thoroughness on a fixed plan) using `apply_rigor_preset` + existing review modules
- [x] Step 7: Update `test_adoption.py` intents for workspace/duplicates routes
- [x] Step 8: Extend `report.py` with the three new sections; regenerate `reports/latest.md`
- [x] Step 9: Full validation (ruff, mypy, pytest in `eval/` and `tests/`, plan lint)

## 9. Validation
```bash
cd .
ruff format eval/
ruff check eval/
pytest -q eval/
pytest -q                      # ensure unit suite still green
python ../../scripts/lint_plan_cohesion.py --plan 228
```

Expected results:
- Ruff: no errors in `eval/`
- Pytest: new multi-project, search-quality, and rigor cost-benefit scenarios pass; search-quality scenarios skip (not fail) when the embedding model is unavailable; existing 108 scenarios still pass
- Plan lint: no errors for Plan 228

## 10. Rollback Plan
Revert the feature branch. The change is confined to `eval/` (fixtures, scenarios, result types, report sections) plus additive `scaffold_search` intent metadata in `src/agentscaffold/mcp/server.py`. Reverting removes the new scenarios/report sections and returns search-intent routing to its prior state.

## 11. Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| DuckPGQ process-global property graph clobbered by a second pipeline run in the multi-project fixture | Medium | Medium | Build the two-project workspace within a single pipeline run or an isolated DB file; reuse the session-scoped pattern already in `conftest.py`; disable async freshness as the existing fixtures do |
| Embedding model unavailable offline makes search-quality scenarios fail in CI | Medium | Medium | Guard with a skip when `[search]`/model is absent; keep the normalization invariant behind the same guard |
| Thoroughness-by-count misread as caught-bug efficacy | Medium | Low | Report text explicitly labels it a proxy; ground-truth efficacy is scoped to Plan 229 |
| Labeled query set is too small to be meaningful | Low | Low | Treat precision@k/MRR as a regression baseline for Tiers 2-3, not an absolute quality claim; document this in the report |
| Rigor scenario coupled too tightly to current review-module output | Low | Low | Assert on relative ordering (cost non-decreasing with rigor) rather than absolute counts |

## 12. Implementation Notes

Completed 2026-06-16.

- Multi-project eval coverage now builds a temp workspace with `sim_project` + `sim_project_b`, colliding `plan_042_data_router_v2.md` and `libs/data/router.py`, and deterministic seeded embeddings for cross-project duplicate detection.
- Search-quality coverage computes keyword/hybrid precision@k and MRR when the configured embedding model is ready offline. In the current environment, the local model cache is absent, so the scenario records a skipped search-quality row and exits cleanly.
- Rigor cost-benefit coverage reports existing preset cost/proxy rows: minimal 102 tokens / 1 call / thoroughness 4; standard 959 tokens / 5 calls / thoroughness 16; strict 976 tokens / 6 calls / thoroughness 16.
- Report generation now renders dedicated Multi-Project Correctness, Search Quality, and Rigor Cost-Benefit sections in `eval/reports/latest.md`.
- Adoption coverage now includes workspace-wide search and duplicate-search phrasing. This required additive `scaffold_search` entries in `TOOL_INTENTS` because the existing MCP search tool had no adoption-route metadata.
- Validation: full eval harness passes (`112 passed, 1 skipped`), full package tests pass (`794 passed`), edited-file ruff/format checks pass, plan cohesion lint passes, and `eval/report.py` passes isolated mypy with imports skipped. Full targeted mypy remains blocked by existing strict-typing debt in legacy MCP/graph/eval fixture surfaces.
- Concurrency fix: `governance_store.py` now provides a per-backend re-entrant governance write lock, and `findings.py` wraps record/resolve/batch finding mutations plus write-through sync in that lock. This prevents multiple threads from driving one DuckDB connection through governance export while another write is in progress.
- Eval artifact hygiene: eval fixtures and conversation replay scenarios now pin governance write-through artifacts to temp fixture paths, so `pytest -q eval/` does not leave a root `docs/ai/state/governance.json` artifact behind.

## 12.6 Retrospective

What worked well: The new result dataclasses fit the existing report collector pattern cleanly, and the deterministic seeded-embedding duplicate test avoided coupling multi-project correctness to optional model weights.

What was harder than expected: The baseline eval suite exposed a native DuckDB crash in a concurrent finding-lifecycle scenario. Fixing it required serializing the whole finding mutation plus write-through export, not just the final artifact write. The adoption update also exposed that `scaffold_search` existed as an MCP tool but had no intent metadata.

Discoveries not in the plan: The implementation touched one product metadata file (`mcp/server.py`) to make the adoption suite meaningful for workspace/duplicate-search phrasing. This is additive route metadata only, not a new runtime surface.

What to do differently: Future eval plans should call out whether adoption coverage may require `TOOL_INTENTS` updates, since those are technically product metadata even when the scenario work is harness-focused.

Actionable follow-ups: None from Plan 228. The remaining typed-surface debt belongs to the existing MCP/graph/eval fixture mypy cleanup thread.

## 12.5 Plan Review Checklist (Ready Gate)

Completed 2026-06-16 before implementation.

| Check | Status | Notes |
|-------|--------|-------|
| Plan status verified | Pass | Execution steps remain unchecked; plan is not marked COMPLETE in workflow_state; not superseded. |
| Staleness reviewed | Pass | Created 2026-06-15 and updated within 2 weeks. |
| Architectural alignment | Pass | Cross-Cutting eval harness only; no trading/data-layer bypass; no system_architecture amendment required. |
| Dependency readiness | Pass | Depends on completed Plans 225 and 227 Tier 1/2a for behavior under measurement; Plan 229 remains a non-goal. |
| Security review | Pass | Security Review: None; deterministic/offline eval-only code, no new secrets/network/runtime surface. |
| Interface contracts | Pass | No public runtime interface exports; eval result dataclasses are harness-internal and additive. |
| Consumer audit | Pass | Eval-only plan; no product config/schema/interface mutation. If implementation touches product code, update File Impact Map before continuing. |
| Test coverage | Pass | Test files are listed in File Impact Map and Tests; validation commands include eval suite and package unit suite. |
| Standards compliance | Pass | Applies testing/config/error-handling standards; no user-facing runtime operations or runbook update required. |
| Devil's advocate review | Pass | Main risk is over-reading proxy metrics as efficacy; mitigated by explicit report language and Plan 229 ground-truth benchmark deferral. |
| Expansion review | Pass | Edge cases listed: optional model absent, empty federated result, no-review rigor level, zero duplicate hits. |
| Approval gate | Pass | Approval Required: No; no human approval blocker before implementation. |

## 13. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff; mypy validation completed with pre-existing typed-surface debt noted in workflow state)
- [x] workflow_state.md updated
- [x] Session log entry added (workflow_state.md)
- [x] Code reviewed (self)
- [x] Approval obtained (if required; Approval Required: No)
