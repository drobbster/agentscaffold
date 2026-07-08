# Feature: AgentScaffold Semantic Search Quality

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-semantic-search-quality
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: No (additive; embeddings are derived data rebuildable from source/governance; no financial/security/external-integration surface). Promote to Yes only if a schema bump is taken that is not additive.
- Security Review: Partial (new persistence: embeddings of governance text -- findings/learnings/plans -- live in the cache; document that they are derived and contain no new secrets)
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package)
- Superseded By: None
- Source: Pre-mortem follow-up discussion 2026-06-15 (search-quality roadmap). Builds on Plan 225 multi-project embedding plumbing (project column, scoped/federated search, provenance, model guard). Sequenced after 225.

## 1. Objective
Raise semantic search from "lexical-on-names" to genuine semantic + hybrid retrieval, and extend it to agent knowledge. Today `_build_text_for_*` embeds only `name + signature + module path` with a general-purpose model (`all-MiniLM-L6-v2`), and search is a brute-force exact cosine scan. Success means: (a) embedded text is enriched with docstrings/leading comments (read from source at embed time); (b) retrieval is hybrid (vector fused with a lexical/symbol signal via reciprocal-rank fusion); (c) the embedding model is configurable and pinnable at the workspace/home level (Plan 224); (d) governance nodes (findings, learnings, plans, ADRs, studies) are embedded so agents can semantically recall prior problems/decisions; (e) the `vss`/HNSW ANN path is actually wired (with an exact-cosine fallback); and (f) precision/perf polish lands (optional cross-encoder re-rank, incremental embedding keyed on `contentHash`, store-time normalization). All additive: search returns today's result shape plus new fields, and the `[search]` extra stays optional.

## 2. Non-Goals
- Not the multi-project plumbing (Plan 225 owns project column, scoped/federated search, provenance, model guard, `find_duplicates`).
- Not swapping DuckDB for an external vector database.
- Not chunking/multi-vector for very large definitions (deferred; noted as a future item).
- Not re-embedding remote/third-party code; only the indexed workspace.

## 3. Constraints / Invariants
- Backward compatibility: Required. With `[search]` absent, search degrades exactly as today. Result dicts keep existing keys; new keys are additive.
- Determinism: a fixed model + fixed input text yields stable vectors; hybrid fusion and ranking are deterministic for a fixed corpus.
- Enrichment reads source at embed time (files are present during indexing), avoiding a node-table schema change for docstrings; a stored-docstring column is a fallback only if profiling demands it.
- Schema changes (governance node-type embeddings, per-embedding `model`) are additive to `EmbeddingStore`; any `SCHEMA_VERSION` bump must remain additive and ride the Plan 219 fail-closed rebuild.
- Model pinning is workspace/home-level (Plan 224); changing the model requires a full re-embed and is recorded so federated comparisons stay model-consistent.
- Breaking change: No (additive).

## 4. Current State
`embeddings.py` builds shallow NL text for `Function`/`Class`/`Method`/`File`, encodes with `all-MiniLM-L6-v2` (384-dim), and upserts into `EmbeddingStore(node_id, node_type, embedding)`. `search_similar` JOINs `EmbeddingStore` to the node table and computes `list_cosine_similarity` ordered DESC LIMIT -- a brute-force exact scan; `search_similar_vss` scans the table directly and notes an unused HNSW (`vss`) acceleration path. Only code definitions are embedded; governance knowledge is not. There is no lexical/hybrid component and no re-rank. Embeddings are regenerated wholesale (no incremental) and cleared globally by `clear_derived`.

## 5. Target State
`_build_text_for_*` incorporates docstrings/leading comments (and a short identifier summary) read from the source slice `[startLine:endLine]`. A configurable, workspace-pinned model (default `all-MiniLM-L6-v2`, optionally a code-specialized model) is recorded per embedding. Governance nodes are embedded via new text builders so `scaffold search --kind governance` (and an MCP tool) can answer "have we seen this before?". `search()` fuses vector similarity with a lexical/symbol score using reciprocal-rank fusion; an optional cross-encoder re-ranks the top-k. The `vss` HNSW index is wired with an exact-cosine fallback. Embedding generation is incremental (re-embed only nodes whose `contentHash`/text changed) and vectors are normalized at store time. All multi-project scoping/provenance is inherited from Plan 225.

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/agentscaffold/graph/embeddings.py | Modify | Enriched text builders (docstring/body); governance text builders; configurable model + recorded model; incremental embed; store-time normalization |
| src/agentscaffold/graph/search.py | Modify | Hybrid fusion (vector + lexical/symbol, RRF); optional cross-encoder re-rank; governance search surface |
| src/agentscaffold/graph/duckpgq_backend.py | Modify | Wire `vss`/HNSW index with exact-cosine fallback; record `model` on `EmbeddingStore`; incremental upsert |
| src/agentscaffold/graph/duckpgq_schema.py | Modify | Additive `model` column on `EmbeddingStore`; allow governance `node_type`s; `SCHEMA_VERSION` bump if needed (additive) |
| src/agentscaffold/config.py | Modify | `search`/embedding config: model name, hybrid weights, rerank toggle, governance-embedding toggle, **model cache dir** (provisioning) |
| src/agentscaffold/cli.py | Modify | `scaffold graph search` gains `--kind code|governance|all` and `--rerank`; **`scaffold graph warm`** provisions/caches the model and `scaffold graph model-status` surfaces readiness |
| src/agentscaffold/graph/embeddings.py (provisioning) | Modify | `_get_model` honors a pinned cache dir; a `warm_model()`/`model_ready()` helper for the provisioning command and offline-graceful degrade (clear error -> keyword-only, not a stack trace) -- Tier 2a |
| src/agentscaffold/mcp/server.py | Modify | Governance semantic-recall tool; hybrid by default |
| src/agentscaffold/graph/pipeline.py | Modify | Incremental embedding step; embed governance after governance ingest |
| tests/test_embeddings_quality.py | Create | Enriched text, model config/record, incremental, normalization |
| tests/test_embeddings_provisioning.py | Create (DONE) | Tier 2a provisioning slice: config defaults, configure/resolve, warm/model_ready, evaluate_retrieval offline-graceful degrade, CLI warm/model-status smoke (all stubbed; no real download) |
| tests/test_search_hybrid.py | Create | RRF fusion ranking, lexical fallback, rerank ordering, governance recall |
| CHANGELOG.md | Modify | Search-quality notes |
| docs/configuration.md | Modify | `search`/embedding config + model pinning |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_embeddings_quality.py | enriched text includes docstring; model recorded per embedding; incremental skips unchanged nodes; vectors normalized | Skip if `[search]` extra absent; use a tiny stub model where possible |
| tests/test_search_hybrid.py | RRF fuses vector + lexical; exact-name query ranks the exact match first; rerank reorders; governance recall returns a seeded finding | Deterministic on a fixed small corpus |

Test approach:
- [ ] Write `test_search_hybrid.py` first (fusion + ranking are the core behavior)
- [ ] Existing `search_similar` tests continue to pass (additive result keys)
- [ ] Edge cases: `[search]` extra absent (graceful degrade); empty corpus; model mismatch on re-embed; governance node with no docstring

## 8. Execution Steps
- [x] Step 1: Baseline -- full `pytest -q` green; capture current search results on a sample query for before/after comparison [DONE 2026-06-16: 744 green baseline after Plan 225]
- [x] Step 2 (Tier 1): Enriched text builders (docstring/leading comment from source slice); store-time normalization; tests [DONE 2026-06-16: `_enrich_text`/`_extract_leading_doc` read the definition's source slice ([startLine:endLine], whole-file head for File) and append a `doc:` hint (capped at 400 chars); `_normalize` L2-normalizes vectors at store time so cosine == dot and an L2 ANN orders identically; `generate_embeddings` resolves root + enriches + normalizes; pipeline passes `root=` on full + incremental embed. 12 tests in test_embeddings_quality.py (pure helpers, no model needed). Enrichment is best-effort: missing source falls back to today's name+signature text]
- [x] Step 3 (Tier 1): Hybrid retrieval -- lexical/symbol scorer + reciprocal-rank fusion in `search.py`; tests first [DONE: already present pre-227 -- `hybrid_search` fuses `_keyword_search` (symbol/path `_text_match_score`) with `_semantic_search` via `_reciprocal_rank_fusion`; Plan 225 made both halves project-scoped. `--no-hybrid` escape hatch == `--mode keyword|semantic`]
- [x] Step 4 (Tier 2a): Configurable + workspace-pinned model; record `model` per embedding; model-mismatch handling on re-embed; model provisioning / offline robustness [DONE 2026-06-16: `SearchConfig{embedding_model, cache_dir, rerank, rerank_model}`; `configure_embeddings`/`warm_model`/`model_ready`/`_resolve_cache_dir` in embeddings.py; `EmbeddingStore.model` + `text_hash` with SCHEMA_VERSION 8->9; `store_embedding(..., model=, text_hash=)`; `evaluate_retrieval` now degrades hybrid->keyword / semantic->unavailable when weights are missing and reports model mismatch with a re-index instruction; `scaffold graph warm` + `scaffold graph model-status`; CLI/MCP/index entrypoints call `configure_embeddings` before model load.]
- [x] Step 5 (Tier 2a): Embed governance nodes (findings/learnings/plans/ADRs/studies) + `scaffold graph search --kind governance` + MCP recall tool [DONE 2026-06-16: governance text builders/selectors for Plan, Learning, ReviewFinding, Study, ADR, Spike, BacklogItem; default `generate_embeddings` covers code+governance tables; keyword/semantic/hybrid search supports `CODE_TABLES` + `GOVERNANCE_TABLES`; CLI `--kind code|governance|all`; MCP `scaffold_search.kind` and dedicated `scaffold_recall_governance` tool.]
- [x] Step 6 (Tier 2b): Wire `vss`/HNSW with exact-cosine fallback [DONE 2026-06-16: DuckPGQ backend already loads `vss` best-effort; added `ensure_embedding_hnsw_index()` best-effort index creation after embedding generation. If `vss` is unavailable or index creation fails, exact `list_cosine_similarity` remains the correctness fallback.]
- [x] Step 7 (Tier 3): Incremental embedding keyed on `contentHash`/text; optional cross-encoder re-rank (off by default) [DONE 2026-06-16: embedding input text is SHA-256 hashed and `generate_embeddings` skips rows whose `(node_id, node_type, model, text_hash)` already exists; optional CrossEncoder rerank is implemented in `hybrid_search(..., rerank=True)` and exposed via CLI/MCP, default off.]
- [x] Step 8: Docs + CHANGELOG; full validation (ruff, mypy, pytest, plan lints) [DONE 2026-06-16: docs/CHANGELOG updated; focused Plan 227 tests green; full validation run recorded in workflow_state/commit.]

> Status (2026-06-16): COMPLETE. Tier 1 enriched embedding text + normalization, Tier 2a configurable/recorded model + provisioning + governance recall, Tier 2b best-effort HNSW wiring with exact fallback, and Tier 3 text-hash incremental skip + optional CrossEncoder rerank are implemented. All behavior remains additive and rides the optional `[search]` extra; SCHEMA_VERSION 8->9 is additive and uses the Plan 219 fail-closed rebuild path.

## 9. Validation
```bash
cd .
ruff format .
ruff check .
pytest -q
pytest -q -m "" tests/test_search_hybrid.py tests/test_embeddings_quality.py
```

Expected results:
- Ruff + mypy: no errors
- Pytest: hybrid ranking + enriched recall verified; graceful degrade without `[search]`; existing search tests still pass

## 10. Rollback Plan
Revert the feature branch. Embeddings are derived: a re-index regenerates the prior representation. Config additions default to today's behavior (general model, hybrid on but reducible to pure vector), so reverting is safe and requires only a re-embed.

## 11. Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Reading source at embed time is slow on large repos | Medium | Medium | Incremental embedding (Step 7); batch reads; cache per file |
| Model swap invalidates existing vectors | Medium | Medium | Record `model`; re-embed on change; refuse cross-model compare (inherits Plan 225 guard) |
| Hybrid fusion regresses some queries vs pure vector | Low | Medium | Keep weights configurable; `--no-hybrid` escape hatch; before/after sample (Step 1) |
| Governance embeddings surface stale/resolved findings | Medium | Low | Filter by status; label provenance; recall is advisory |
| `vss` extension unavailable offline | Medium | Low | Exact-cosine fallback preserves correctness (slower); 2b is gated on this and trails 2a |
| Model weights absent at first use (offline/air-gapped/CI/sandbox) | Medium | Medium | Provision deterministically via `scaffold graph warm` + pinned cache dir (Tier 2a); offline-graceful degrade to keyword-only with a clear actionable message instead of a runtime stack trace. Note: installing the `[search]` package does NOT bundle weights -- provisioning is a separate, explicit step |
| Forcing `[search]`/torch as a hard dependency bloats every install | Medium | Medium | Keep `[search]` optional; make readiness explicit via `scaffold doctor`/`warm` and docs (`[all]` for full power, bare install for lightweight CLI/governance). Revisit hard-dep only if the lightweight path proves unused |

## 12. Security Review (Partial)
The new persistence is embeddings of governance text (findings, learnings, plans, ADRs, studies) stored in the derived cache. These are vectorizations of content already committed to the repo (git-backed governance), so they introduce no new secret material and no new external surface; embedding generation is local (sentence-transformers), with no network calls at query time. The data-flow is source/governance text -> local model -> `EmbeddingStore` (derived, rebuildable). Trust boundary is unchanged from Plan 225 (single-writer, workspace = single trust domain). Risk is limited to surfacing stale knowledge, mitigated by status filtering and advisory provenance.

## 13. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] Ruff clean; mypy run documented with pre-existing strict-typing debt outside this plan's scope
- [x] workflow_state.md updated
- [x] Session log entry added (if multi-session)
- [x] Code reviewed (self or peer)
- [x] Approval obtained (if required; Approval Required: No)

## 14. Retrospective

Completed 2026-06-16.

### What Worked Well

Splitting Tier 2 into a stub-testable provisioning/model-recording/governance slice and a resource-gated HNSW slice kept the implementation incremental. The text-hash approach gave the incremental embedding requirement without introducing new source-node schema columns, and the existing Plan 219 fail-closed rebuild path made the additive schema bump straightforward.

### What Was Harder Than Expected

The model-weight fragility was not solved by dependency installation alone because sentence-transformers downloads weights lazily. Treating provisioning as a first-class command (`scaffold graph warm`) was the right abstraction, but it required threading model/cache configuration through CLI, indexing, MCP, and retrieval evaluation.

### Discoveries Not In The Plan

The deterministic fallback paths mattered more than HNSW itself. Best-effort HNSW index creation is useful, but exact cosine remains the correctness path and keeps offline/minimal installs reliable. Mypy also still reflects older strict-typing debt in CLI/MCP/protocol surfaces; Plan 227 avoided expanding that debt but did not resolve it.

### What We Would Do Differently

Add model provenance to `EmbeddingStore` at the same time as the Plan 225 `project` column in future embedding-related schema changes. Both are part of the same invariant: vectors should only be compared when scope and model are compatible.

### Actionable Follow-Ups

No standalone backlog item is needed. Plan 228 will add deterministic eval coverage for search quality and multi-project behavior, and Plan 229 will handle live efficacy benchmarking rather than adding another proxy metric here.
