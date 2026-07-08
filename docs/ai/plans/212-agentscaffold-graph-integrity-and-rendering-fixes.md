# Bugfix: AgentScaffold Knowledge Graph Integrity and Agent-Readability Fixes

## 0. Metadata
- Issue: #TBD
- Branch: bugfix/212-agentscaffold-graph-integrity
- Severity: High
- Approval Required: No (developer tooling; no live-trading/risk/secrets impact)
- Component: ``
- Source of findings: Code audit 2026-06-12 (this session); corroborated by subagent audits of MCP rendering and post-migration degradations.

## 1. Bug Description

After the DuckDB + DuckPGQ migration (Plan 149), the AgentScaffold knowledge graph
no longer renders relationships and context well for an AI agent. Direct inspection of
the live graph (`.scaffold/graph.duckdb`, 1.3 GB) revealed two compounding problems:

1. **Catastrophic edge duplication**: relationship edges are duplicated ~725-750x.
2. **Missing governance data**: the most agent-valuable relationships (plans, contracts,
   findings, impact edges) are entirely absent from the live graph.

Reproduction:
```bash
# Inspect the live graph
python -c "import duckdb; c=duckdb.connect('.scaffold/graph.duckdb', read_only=True); \
print('IMPORTS', c.execute('SELECT count(*) FROM IMPORTS').fetchone()[0]); \
print('IMPORTS distinct', c.execute('SELECT count(*) FROM (SELECT DISTINCT src,dst FROM IMPORTS)').fetchone()[0]); \
print('Plan', c.execute('SELECT count(*) FROM Plan').fetchone()[0])"
```

Measured live state (2026-06-12):

| Table | Total | Distinct | Duplication |
|-------|-------|----------|-------------|
| IMPORTS | 1,552,699 | 2,070 | 750x |
| CALLS | 6,737,503 | 9,296 | 725x |
| METHOD_CALLS | 0 | - | never populated |
| PLAN_IMPACTS | 0 | - | empty |
| Plan | 0 | - | empty |
| Contract | 0 | - | empty |
| ReviewFinding | 0 | - | empty |
| EmbeddingStore | 0 | - | empty |

`GraphMeta` shows `pipelineState=complete`, `phasesCompleted=["incremental"]`,
`lastIndexed=2026-06-11`. The graph's last write was an incremental run.

The effect on an agent: every CALLS/IMPORTS traversal returns hundreds of identical
duplicate rows (noise, truncation, blown context windows), while governance context
(the high-value relationships) returns nothing.

## 2. Root Cause

### Primary: incremental indexing appends duplicate edges
`_run_incremental` in `pipeline.py` re-resolves **all** imports and calls on every run
but never clears the prior edges first:

```374:381:src/agentscaffold/graph/pipeline.py
        from agentscaffold.graph.calls import process_calls
        from agentscaffold.graph.imports import process_imports

        import_result = process_imports(store, root, symbol_table)
        summary["imports"] = import_result

        call_result = process_calls(store, root, symbol_table)
        summary["calls"] = call_result
```

`create_edge` is a blind INSERT with no dedup or upsert:

```274:281:src/agentscaffold/graph/duckpgq_backend.py
        sql = f"INSERT INTO {rel_table} ({', '.join(cols)}) VALUES ({placeholders})"
        self._conn.execute(sql, vals)
```

A `PostToolUse` hook runs `scaffold index --incremental` on every file edit. After ~750
edits, IMPORTS/CALLS accumulate ~750 full copies. The full-index path (`run_pipeline`)
is safe because it calls `store.clear_all()` first (`pipeline.py:65`); only the
incremental path is affected.

### Secondary: incremental never refreshes governance
`run_pipeline` ingests governance at phase 4 (`pipeline.py:221`,
`process_governance(...)`), but `_run_incremental` has no equivalent step. Since the
live graph's last write was incremental, governance nodes/edges are absent.

### Tertiary: METHOD_CALLS never populated
`process_calls` only iterates functions and only ever writes `CALLS`
(`calls.py:115`, Function->Function). Methods are never processed as callers, so the
`METHOD_CALLS` edge table defined in the schema stays empty.

### Rendering gaps (separate from data integrity)
Even with correct data, several MCP tools under-render relationships:
- `scaffold_context`, `scaffold_impact`, `scaffold_orient`, `scaffold_prepare_implementation`
  return JSON only (no markdown companion), unlike `scaffold_prepare_review`.
- Tool descriptions oversell: `scaffold_context` promises imports/layer/plan-history/
  contracts/learnings but returns only symbol + callers + callees; `scaffold_impact`
  promises transitive consumers/affected layers/governance but returns only direct
  importers/callers and ignores its `depth` parameter (`server.py:1221-1222`).
- Raw dot-qualified column aliases (`"f.path"`, `"caller.name"`, `"rf.id"`) leak into
  agent-visible JSON.
- `generate_brief` queries full importer/caller/transitive lists then discards them,
  keeping only counts (`brief.py:80-100`).

### Pre-Audit Findings (validated with line numbers)

| # | Summary | File:Line | Root Cause | Fix Approach | Severity |
|---|---------|-----------|------------|--------------|----------|
| 1 | IMPORTS/CALLS duplicated ~750x | pipeline.py:377,380; duckpgq_backend.py:274-281 | Incremental re-inserts all edges without clearing; create_edge non-idempotent | Clear regenerated edge tables before re-resolve in incremental; add idempotent edge insert | Critical |
| 2 | Governance empty after incremental | pipeline.py:_run_incremental (no governance step) | Incremental path omits process_governance | Add governance refresh to incremental path | High |
| 3 | Incremental re-resolves ALL files | pipeline.py:377,380 | process_imports/process_calls ignore changeset | Scope re-resolution to changed files (or clear-all + reinsert as interim) | High |
| 4 | METHOD_CALLS never populated | calls.py:34-123 | process_calls only handles Function callers, only writes CALLS | Extend process_calls to emit METHOD_CALLS for Method callers | Medium |
| 5 | create_edge non-idempotent | duckpgq_backend.py:274-281 | Blind INSERT, no unique handling | Add dedup/anti-join insert option for structural edges | Medium |
| 6 | context/impact/orient JSON-only, descriptions oversell | server.py (~398-415, 1166-1271, 1700-1798) | No markdown formatters; depth unused; queries missing promised fields | Add markdown formatters; implement transitive impact + governance; align descriptions | Medium |
| 7 | Dot-qualified keys leak to agent output | server.py composite tools | Raw SQL aliases returned verbatim | Normalize keys to clean names in MCP output | Medium |
| 8 | brief discards relationship lists | brief.py:80-100,176-188 | Only counts retained | Include top-N importer/caller/consumer names | Medium |
| 9 | No embeddings persisted | embeddings opt-in; index interrupted | EmbeddingStore empty | Rebuild with --embeddings; consider enabling in config | Medium |
| 10 | Integration tests sidelined | tests/ (test_governance_and_review, test_template_integration, test_search_and_communities, test_incremental_and_sessions, test_cli_graph_wiring) | Repeatedly --ignore'd during Plan 149 | Re-enable, fix, run | Medium |
| 11 | Per-file language reload in parser | parsing.py:258 | _get_ts_language re-invokes _load_language per file | Cache Language objects | Low |
| 12 | Stale doc: C warnings "harmless" | docs/getting-started.md | Predates 0.3.1 fix | Update doc | Low |

## 3. Constraints / Invariants
- Must not break: full-index path (`run_pipeline`), MCP server startup, existing passing tests.
- Must not break: `scaffold.yaml` ignore behavior or file scoping (graph must remain ~1,400 files, not re-scan `.venv`).
- Regression risk: changing incremental edge handling could drop legitimate edges if clearing is too broad; mitigate with backend-parity counts after a clean full index vs. incremental.
- Idempotency invariant: running `scaffold index --incremental` N times with no file changes must leave edge counts unchanged.
- Backward compatibility: no schema version bump required (no DDL change) unless a UNIQUE constraint is added for edge dedup (decide in Step 5).

## 4. File Impact Map

| File | Change Type | Notes |
|------|-------------|-------|
| `src/agentscaffold/graph/pipeline.py` | MODIFY | Incremental: clear regenerated edges, scope re-resolution, add governance refresh |
| `src/agentscaffold/graph/duckpgq_backend.py` | MODIFY | Idempotent edge insert; helper to clear edges by source-node set |
| `src/agentscaffold/graph/imports.py` | MODIFY | Optional file scoping for re-resolution |
| `src/agentscaffold/graph/calls.py` | MODIFY | Populate METHOD_CALLS; optional file scoping |
| `src/agentscaffold/graph/parsing.py` | MODIFY | Cache Language objects (perf) |
| `src/agentscaffold/mcp/server.py` | MODIFY | Markdown formatters for context/impact/orient; transitive impact + governance; key normalization; align tool descriptions |
| `src/agentscaffold/review/brief.py` | MODIFY | Surface top-N relationship names, not just counts |
| `src/agentscaffold/graph/governance.py` | MODIFY | Wire `_parse_review_findings` -> `_ingest_plan_findings`; `_parse_plan` returns `text`; confirmed idempotent for incremental reuse |
| `tests/test_governance_findings.py` | NEW | Regression: plan `[CATEGORY]` markers -> ReviewFinding, idempotent, resolved-status preserved |
| `docs/getting-started.md` | MODIFY | Remove stale "C warnings harmless" note |
| `tests/test_incremental_and_sessions.py` | MODIFY | Re-enable; add idempotency regression test |
| `tests/test_governance_and_review.py` | MODIFY | Re-enable |
| `tests/test_template_integration.py` | MODIFY | Re-enable |
| `tests/test_search_and_communities.py` | MODIFY | Re-enable (guard embeddings tests on sentence-transformers) |
| `tests/test_cli_graph_wiring.py` | MODIFY | Re-enable |
| `tests/test_graph_edge_idempotency.py` | NEW | Regression: incremental N-runs => stable edge counts |
| `tests/test_mcp_rendering.py` | NEW | Markdown present + no dot-keys for context/impact/orient |

## 5. Tests

| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| `tests/test_graph_edge_idempotency.py` | Edge dedup regression | Index, then incremental x3 with no changes => IMPORTS/CALLS counts unchanged; with 1 changed file => only that file's edges change |
| `tests/test_incremental_and_sessions.py` | Incremental correctness + governance | Re-enabled; assert governance present after incremental |
| `tests/test_governance_and_review.py` | Governance ingestion + review | Re-enabled |
| `tests/test_template_integration.py` | Graph context in templates | Re-enabled |
| `tests/test_search_and_communities.py` | Search + communities | Re-enabled; embeddings tests skip if no sentence-transformers |
| `tests/test_cli_graph_wiring.py` | CLI + graph context | Re-enabled |
| `tests/test_mcp_rendering.py` | Agent-readability | context/impact/orient return markdown; no raw dot-qualified keys at top level |
| `tests/test_duckpgq_backend.py` | Idempotent create_edge | Add case: duplicate create_edge does not double-count when idempotent flag set |

Test approach:
- [ ] Regression test that fails before fix (edge counts grow on repeated incremental), passes after
- [ ] Governance present after incremental run
- [ ] METHOD_CALLS populated on a fixture with class methods calling functions
- [ ] MCP context/impact/orient include a markdown field and clean keys
- [ ] Idempotency: repeated no-op incremental leaves all edge counts stable

## 6. Execution Steps

### Phase 1: Graph data integrity (Critical/High)
- [x] Step 1.1: Write failing regression test `test_graph_edge_idempotency.py` (incremental x3 grows IMPORTS/CALLS today)
- [x] Step 1.2: Make `duckpgq_backend.create_edge` idempotent on `(src, dst)` via anti-join insert; added `clear_governance()` helper + `_GOVERNANCE_*` table groups
- [x] Step 1.3: Incremental resolution is now idempotent (no duplicate edges); `_run_incremental` re-resolves without duplicating. (Per-file scoping deferred as perf-only; correctness achieved via idempotent inserts.)
- [x] Step 1.4: Add governance refresh to `_run_incremental` (`clear_governance()` + `process_governance`); threaded `config` through. Governance nodes are idempotent (ON CONFLICT); edges now idempotent.
- [x] Step 1.5: Populate `METHOD_CALLS` in `process_calls` (Method callers -> Function targets, per schema)
- [x] Step 1.6: Regression test passes; repeated incremental on live graph leaves counts stable (IMPORTS 2071, CALLS 9306, METHOD_CALLS 5023)
- [x] Step 1.7: Clean rebuild verified: IMPORTS 2071 (distinct=2071, was 1.5M), CALLS 9306 (was 6.7M), METHOD_CALLS 5023 (was 0), 212 plans / 68 contracts / 1619 impact edges (was 0), EmbeddingStore 13,739 (was 0). All edge tables: total == distinct (no duplication).
- [x] Step 1.8: Wire up dead `_parse_review_findings` -> `process_governance` now ingests `[CATEGORY]` review markers from plan text into `ReviewFinding` nodes at index time (`_ingest_plan_findings`, review_type `plan_appendix`). Idempotent (deterministic ids + ON CONFLICT); preserves runtime-resolved status. Live smoke (on DB copy): 4 markers -> 4 findings, readable via `get_open_findings`. Current plan corpus has 0 markers, so live graph stays 0 until plans contain markers. NOTE: incremental only refreshes governance when the work path runs (code change); a pure plan-doc edit with no code change does not trigger governance refresh -- run a full `scaffold index` to pick up doc-only finding changes.

### Phase 2: MCP rendering and agent-readability (Medium)
- [x] Step 2.1: Added markdown formatters for `scaffold_context` and `scaffold_impact` (new `mcp/render.py`, mirrors `scaffold_search`'s `markdown` field). Orient already returns structured stats; markdown deferred (not over-promised).
- [x] Step 2.2: Implemented `scaffold_impact` `depth` traversal (multi-hop transitive importers via BFS) + method callers into file (METHOD_CALLS)
- [x] Step 2.3: Trimmed `scaffold_context`/`scaffold_impact` descriptions to match behavior; added method-callers to context
- [x] Step 2.4: Normalize agent-visible keys (strip `alias.` prefixes) via `render.clean_rows` in context/impact outputs
- [x] Step 2.5: `generate_brief` / `format_brief_markdown` now include top-N importer paths and caller names (not just counts)
- [x] Step 2.6: Wrote `test_mcp_rendering.py`

### Phase 3: Hygiene (Low/Medium)
- [x] Step 3.1: Cache tree-sitter `Language` objects in `parsing.py` (`@cache` on `_load_language`)
- [x] Step 3.2: Full suite run (503 passed) including the previously `--ignore`'d integration tests (governance, template, search, incremental, cli_graph_wiring) -- all pass, none were skip-marked
- [x] Step 3.3: Updated `getting-started.md` stale C-warnings note (now points to 0.3.1 fix)
- [x] Step 3.4: Incremental hook is now safe for repeated runs (guaranteed by idempotent edges in Step 1.2)

## 7. Validation
```bash
cd .

# Lint
ruff format .
ruff check .

# Full suite (use the env that owns scaffold)
/Users/daverobb/rebellion-trading-system/uv run python -m pytest tests/ -q

# Idempotency check after a clean rebuild
cd /Users/daverobb/rebellion-trading-system
rm -f .scaffold/graph.duckdb
scaffold index --embeddings
uv run python -c "import duckdb; c=duckdb.connect('.scaffold/graph.duckdb', read_only=True); \
imp=c.execute('SELECT count(*) FROM IMPORTS').fetchone()[0]; \
impd=c.execute('SELECT count(*) FROM (SELECT DISTINCT src,dst FROM IMPORTS)').fetchone()[0]; \
print('IMPORTS', imp, 'distinct', impd, 'ratio', round(imp/max(impd,1),2)); \
print('Plan', c.execute('SELECT count(*) FROM Plan').fetchone()[0]); \
print('Embeddings', c.execute('SELECT count(*) FROM EmbeddingStore').fetchone()[0])"
scaffold index --incremental && scaffold index --incremental   # must not grow edge counts
```

Expected results:
- Ruff: no errors
- Pytest: all tests pass (including new regression + re-enabled integration tests)
- IMPORTS ratio ~1.0 (no duplication); Plan/Contract/ReviewFinding populated; EmbeddingStore > 0
- Repeated incremental runs leave edge counts unchanged

## 8. Rollback Plan
- All changes are within ``; revert via `git revert` of the bugfix commits.
- The graph DB is regenerable: if a fix misbehaves, `rm .scaffold/graph.duckdb && scaffold index` restores a clean state from source.
- No data migration; no schema DDL change unless Step 1.2 adds a UNIQUE constraint (in which case bump `SCHEMA_VERSION` and document; rollback = revert + rebuild).

## 9. Completion Checklist
- [x] All execution steps checked off
- [x] Regression tests written and passing (`test_graph_edge_idempotency.py`, `test_mcp_rendering.py`, `test_governance_findings.py`)
- [x] Integration tests passing (full suite: 507 passed)
- [x] No linter errors (ruff: all checks passed)
- [x] Clean rebuild verified (no duplication, governance populated, EmbeddingStore 13,739)
- [x] Repeated-incremental idempotency verified on live graph
- [x] workflow_state.md updated
- [x] getting-started.md doc corrected
- [x] Retrospective completed (Section 10)

## 10. Retrospective

**Execution date**: 2026-06-12. **Effort**: roughly as expected for the data-integrity
and rendering phases; the finding-ingestion follow-ups (Step 1.8 + the widened regex)
were added after the original plan based on questions raised during review.

### What worked well

Inspecting the live graph directly before writing any code was the single highest-value
move. The audit table (1.5M IMPORTS / 6.7M CALLS / zero governance) turned a vague
"relationships do not render well" complaint into twelve concrete, line-referenced
findings, which made the fixes mechanical rather than speculative. Making `create_edge`
idempotent via an anti-join insert fixed the duplication at its root instead of papering
over it with post-hoc dedup, and because governance nodes already used deterministic ids,
the same idempotency property let the incremental governance refresh be a safe
clear-and-reingest rather than a fragile diff. Validating every change against a copy of
the real 1.3GB graph (never the live file) gave high confidence without risk.

### What was harder than expected

The DuckDB/DuckPGQ native extension made the test runner crash (bus error/segfault) under
the sandbox; this was resolved by running pytest outside the sandbox, but it cost time to
diagnose. The interaction between `clear_governance`'s preservation policy and the
ReviewFinding lifecycle was subtle: it required confirming that `_GOVERNANCE_NODE_TABLES`
and `_GOVERNANCE_EDGE_TABLES` exclude `ReviewFinding`, `FINDING_ABOUT_FILE`, and
`FINDING_ABOUT_FUNC` so that runtime-recorded findings survive re-indexing.

### Discoveries not in the original plan

Three things surfaced during execution that were not in the audit. First,
`_parse_review_findings` was fully implemented but never called -- dead code that meant
`ReviewFinding` could only ever be populated at runtime; this became Step 1.8. Second, the
review engine emits more finding categories (`CONSUMER_AUDIT`, `DEPENDENCY_COMPLETENESS`,
`TEST_COVERAGE`, `SIMILAR_PATTERN`, `INTEGRATION_POINTS`) than the original regex captured,
and the `!`/`!!` severity markers were leaking into finding text -- both fixed by widening
`_FINDING_RE`. Third, and most consequential for the follow-up work: `begin_plan`/
`complete_plan` already auto-write findings but do not link them to File nodes, so the
`[PATTERN]` recurring-finding detector (which traverses `FINDING_ABOUT_FILE`) can never
fire. That gap, plus the fact that incremental governance refresh is gated on code changes
(doc-only edits never refresh) and costs ~2.7s on every code edit, motivated follow-up
Plan 213.

### Technical debt incurred

Incremental re-resolution still re-resolves all imports/calls rather than scoping to the
changeset (Step 1.3 deferred per-file scoping as perf-only; correctness is guaranteed by
idempotent inserts). `scaffold_orient` returns structured stats only, with markdown
deferred. Both are intentional and documented, not silent shortcuts.

### Metrics

| Metric | Value |
|--------|-------|
| Execution steps completed | 18 / 18 (3 phases + Step 1.8) |
| New test files | 3 |
| Full suite | 507 passed |
| Linter | ruff clean |

**One-sentence summary**: Root-caused and fixed the post-DuckDB graph corruption
(idempotent edges + incremental governance refresh + METHOD_CALLS), made MCP output
agent-readable (markdown + key normalization + transitive impact), and wired finding
ingestion end-to-end. **Confidence: 5/5.** Follow-ups tracked in Plan 213.
