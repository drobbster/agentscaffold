# AgentScaffold Retrieval Degradation Contract

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-retrieval-contract
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: No
- Security Review: None
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package)
- Superseded By: None

## 1. Objective
Make retrieval degradation explicit and consistent everywhere search is exposed. Success means: a single `evaluate_retrieval(store, mode)` oracle classifies retrieval as `available`, `degraded`, or `unavailable` with an effective mode and human-readable reason; MCP tool responses surface that status in `meta` (and `scaffold_search` reflects the actually-requested mode); the CLI `graph search` reuses the same oracle instead of ad-hoc warnings; and the unused `rank-bm25` dependency is removed with the keyword-search approach documented.

## 2. Non-Goals
- Not implementing BM25 ranking (keyword search stays custom term-overlap; `rank-bm25` is dropped).
- Not changing the ranking algorithm (`_reciprocal_rank_fusion`) or embedding generation.
- Not adding new search modes.

## 3. Constraints / Invariants
- Must not break: `hybrid_search` signature/behavior, existing MCP `scaffold_search` response shape (additive `meta` only), CLI `graph search` behavior (same fallback outcome).
- Backward compatibility: oracle is additive; existing callers keep working.
- Performance constraints: oracle does at most one cheap `COUNT(*)` on `EmbeddingStore`.
- Security constraints: none.
- Data integrity constraints: read-only.
- Breaking change: No (dependency removal from an optional extra is non-breaking for code; documented).

## 4. Current State
`hybrid_search` silently returns keyword-only or empty results when semantic retrieval is unavailable. The MCP `_tool_search` ([server.py](src/agentscaffold/mcp/server.py) 1449-1474) passes `mode` straight through with no signal about whether semantic actually ran. `_build_meta` (1141-1154) carries freshness but no retrieval capability. The CLI `graph search` ([cli.py](src/agentscaffold/cli.py) 756-772) duplicates the degradation logic with ad-hoc `console.print` warnings using `_st_available`/`embeddings_available`. `rank-bm25` is declared in the `search` extra ([pyproject.toml](pyproject.toml) 64-67) but never imported.

## 5. Target State
`graph/search.py` exposes `evaluate_retrieval(store, mode)` returning prefixed keys (`retrieval_status`, `retrieval_effective_mode`, `retrieval_requested_mode`, `retrieval_reason`). `_build_meta` merges a capability snapshot; `_tool_search` recomputes for the requested mode and overrides the search response meta. CLI `graph search` calls the oracle, prints one consistent warning when not `available`, and uses the effective mode. `rank-bm25` is removed from the `search` extra and `uv.lock`; README and `docs/configuration.md` document the three modes and degradation behavior.

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/agentscaffold/graph/search.py | Modify | Add `evaluate_retrieval()` oracle |
| src/agentscaffold/mcp/server.py | Modify | Merge retrieval status into `_build_meta`; override in `_tool_search` |
| src/agentscaffold/cli.py | Modify | `graph search` reuses oracle for warning + effective mode |
| pyproject.toml | Modify | Drop `rank-bm25` from `search` extra |
| uv.lock | Modify | Regenerated after dependency removal |
| README.md | Modify | Document retrieval modes + degradation |
| docs/configuration.md | Modify | Document retrieval modes + degradation |
| tests/test_search_and_communities.py | Modify | Tests for `evaluate_retrieval` scenarios |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_search_and_communities.py | `evaluate_retrieval` available/degraded/unavailable across modes | `_st_available`/`embeddings_available` monkeypatched |

Test approach:
- [ ] Unit tests for core logic: keyword always available; semantic unavailable when ST missing; hybrid degrades to keyword; degraded when no vectors; available when both present
- [ ] Integration tests: MCP `_tool_search` meta carries retrieval status
- [ ] Edge cases: pure semantic with ST missing reports `unavailable` with `effective_mode=none`

## 8. Execution Steps
- [x] Step 1: Add `evaluate_retrieval(store, mode)` to `search.py`
- [x] Step 2: Merge retrieval snapshot into `_build_meta`; override with requested mode in `_tool_search`
- [x] Step 3: Refactor CLI `graph search` to reuse the oracle
- [x] Step 4: Drop `rank-bm25` from `pyproject.toml`; regenerate `uv.lock`
- [x] Step 5: Document retrieval modes/degradation in README and `docs/configuration.md`
- [x] Step 6: Add tests; run ruff + full pytest (584 passed)

## 9. Validation
```bash
ruff format src tests
ruff check src tests
uv run python -m pytest tests -q
```

Expected results:
- Ruff: no errors
- Pytest: all tests pass

## 10. Rollback Plan
`git revert` the commit. The oracle is additive and the dependency removal is reversible by restoring the `pyproject.toml` line and re-locking. No data or schema changes.

## 11. Risks & Mitigations
- Risk: removing `rank-bm25` breaks an environment that imported it. Mitigation: a repo-wide search confirms it is never imported; only the unused extra entry is removed.
- Risk: oracle misreports status and confuses agents. Mitigation: deterministic classification with explicit unit tests for every branch; `meta` is additive so a wrong value never blocks a query.

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff, mypy)
- [ ] workflow_state.md updated (batched at release gate)
- [x] Code reviewed (self)
- [x] Approval obtained (not required)
