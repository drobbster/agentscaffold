# Spike: Config-Reference Resolution Precision/Recall

### Metadata

| Field | Value |
|-------|-------|
| Parent Plan | 214/215 (AgentScaffold graph coverage), P3 follow-up |
| Time-box | 2-3 hours |
| Created | 2026-06-12 |
| Author | agent |
| Status | Complete |

### Goal

> Validate that a heuristic resolver can extract code references from config files
> (YAML/JSON/TOML) and resolve them to graph nodes with high enough precision to be worth
> adding as `CONFIG_REFERENCES` edges, closing part of the config-driven-wiring blind spot.

### Questions to Answer

| # | Question | Success Criteria |
|---|----------|------------------|
| 1 | What fraction of extracted fully-qualified dotted references resolve to a unique graph File/Class node? | >= 80% resolve uniquely |
| 2 | What is the false-positive rate (non-code strings mis-extracted as references)? | < 10% on a manual sample of 30 |
| 3 | How much wiring would this add (edges + config files covered)? | Meaningful volume across strategy/pipeline configs |

### Constraints
- Time-box: 3 hours. Validate only the questions above.
- Output: throwaway prototype + measurements + go/no-go decision. NOT production code.

### Approach
1. [x] Sample config files to identify reference patterns (done: `class: a.b.C` dotted FQNs).
2. [ ] Prototype an extractor (dotted-path regex + allowlisted keys) over all config files.
3. [ ] Resolve candidates against graph File paths + Class/Function names.
4. [ ] Measure unique-resolution rate, manual-sample precision, and volume/coverage.
5. [ ] Decide: proceed (full FQN), restrict (allowlisted keys only), or defer.

### Minimal Prototype

Location: `/tmp/spike_config_refs.py` (temporary, not committed). Key logic embedded in
Findings below.

### Findings

Corpus note: the first run scanned 30,271 "config" files (2.5M candidates) because it
walked `.mypy_cache/` and other vendored trees the graph ignores. Restricting to config
files the graph actually indexes (158 files) is the correct scope and is what the numbers
below use.

#### Question 1: unique-resolution rate
**Finding:** Under an allowlist of code-reference keys (`class`, `_target_`, `type`,
`factory`, `callable`, `module`, ...), 62 of 64 fully-qualified dotted references resolved
to a unique File+Class node -- 96.9%. The 2 misses were file-resolved but class-missed
(class re-exported via a package `__init__`), so still file-level correct. Over ALL scalars
(no key filter) the rate drops to 85.1% (63/74).
**Evidence:** `/tmp/spike_config_refs2.py` over `/tmp/spike_graph.duckdb`; outcomes
`file+class=62, file-classmiss=2` for allowlisted keys.
**Confidence:** High (clean, deterministic resolution against the live graph).

#### Question 2: false-positive rate
**Finding:** Allowlisted-key extraction produced ZERO false positives -- all 64 candidates
were genuine code references. The false positives appear only in the any-scalar mode
(`yield_curve.flat_threshold`, `live.bbo`, `pyproject.toml`, `uv.lock`), and even those
correctly fail to resolve (no matching File/Class), so they would never become edges.
**Evidence:** Unresolved-candidate audit sample; all FPs were non-allowlisted keys and
unresolved.
**Confidence:** High.

#### Question 3: volume/coverage
**Finding:** Volume is concentrated: ~62 resolvable references, almost all in
`configs/strategies/strategy_registry.yaml`. Low file-count coverage, but HIGH value --
that file dynamically wires 60+ strategy classes, which are exactly the symbols the static
call graph resolves only heuristically (confidence 0.5, per Plan 215's `handle_strategy_nans`
example). Other config-driven wiring (Prefect flow names, Feast refs) uses non-FQN
identifiers and is out of scope for this FQN-based approach.
**Evidence:** `config files with >=1 strong (allow): 1`; strong-resolution sample dominated
by `strategy_registry.yaml`.
**Confidence:** High for FQN configs; the approach does NOT address identifier-only wiring.

### Unexpected Discoveries

| Discovery | Impact on Parent Plan |
|-----------|----------------------|
| `.mypy_cache/*.data.json` dominates a naive config walk | Implementation MUST reuse the graph's ignore set / index only graph File nodes |
| Allowlisted keys give 97% precision + 0 FP; any-scalar is noisy | Restrict extraction to allowlisted keys; do NOT extract from arbitrary scalars |
| Package `__init__` re-exports cause file+class misses | Resolver should also check `__init__` exports to lift the 2 misses |
| Value is concentrated in the strategy registry | Even low file-coverage is worth it: it corroborates the heuristic strategy-dispatch edges |

### Decision

- [x] **Modify plan** - Approach is viable but must be RESTRICTED.

Proceed to a 0.4.0 implementation plan with these constraints:
1. Extract FQN references ONLY under an allowlist of keys (`class`, `_class_`, `_target_`,
   `target`, `callable`, `factory`, `cls`, `type`, `module`, `import`, `entrypoint`,
   `strategy_class`). Do not extract from arbitrary scalars (85% precision, FPs).
2. Resolve module->File and optional trailing Class/Function; also resolve package
   `__init__` re-exports. Create `CONFIG_REFERENCES` edges (config File -> File/Class) with
   confidence: file+class = 0.9, file-only = 0.7.
3. Reuse the structure-ingest ignore set (only index config files that are graph File
   nodes) to avoid the `.mypy_cache` flood.
4. Surface these edges in `scaffold_impact` (editing a class shows config consumers) and as
   corroboration in `scaffold_context` (a high-confidence config edge alongside heuristic
   call edges).

### Plan Modifications Required

| Section | Change Required |
|---------|-----------------|
| Parent Plan 214 Section 9 (P3) | Mark config-reference indexing VALIDATED; scope to allowlisted-key FQN only |

### Spike Cleanup
- [x] Delete prototype (`/tmp/spike_config_refs*.py`, `/tmp/spike_graph.duckdb`)
- [x] Update parent plan (214 Section 9) with decision
- [x] Backlog item added (B-214-1)
