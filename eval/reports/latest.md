# AgentScaffold Evaluation Report

**Generated**: 2026-03-05T09:51:57

## Summary

| Metric | Value |
|--------|-------|
| Total Scenarios | 64 |
| Passed | 64 |
| Failed | 0 |
| Pass Rate | 100.0% |
| Average Score | 0.97 |
| Total Time | 0ms |

## Lifecycle (9/9)

Average score: 1.00

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| full_index_lifecycle | PASS | 1.00 | 0 |
| files_indexed | PASS | 1.00 | 0 |
| definitions_extracted | PASS | 1.00 | 0 |
| governance_ingested | PASS | 1.00 | 0 |
| import_resolution | PASS | 1.00 | 0 |
| incremental_no_changes | PASS | 1.00 | 0 |
| incremental_new_file | PASS | 1.00 | 0 |
| session_start_end | PASS | 1.00 | 0 |
| session_modifications | PASS | 1.00 | 0 |

## Review (9/9)

Average score: 1.00

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| brief_complete_plan | PASS | 1.00 | 0 |
| brief_missing_plan | PASS | 1.00 | 0 |
| challenges_ready_plan | PASS | 1.00 | 0 |
| gaps_draft_plan | PASS | 1.00 | 0 |
| verify_complete_plan | PASS | 1.00 | 0 |
| verify_partial_plan | PASS | 1.00 | 0 |
| retro_complete_plan | PASS | 1.00 | 0 |
| communities_detected | PASS | 1.00 | 0 |
| community_membership | PASS | 1.00 | 0 |

## Edge Case (12/12)

Average score: 1.00

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| graph_context_no_graph | PASS | 1.00 | 0 |
| review_context_no_graph | PASS | 1.00 | 0 |
| empty_module_indexed | PASS | 1.00 | 0 |
| unicode_class_indexed | PASS | 1.00 | 0 |
| unicode_methods_extracted | PASS | 1.00 | 0 |
| go_file_indexed | PASS | 1.00 | 0 |
| rust_file_indexed | PASS | 1.00 | 0 |
| deleted_file_removed | PASS | 1.00 | 0 |
| malformed_plan_no_crash | PASS | 1.00 | 0 |
| missing_contracts_dir | PASS | 1.00 | 0 |
| contract_drift_detection | PASS | 1.00 | 0 |
| stale_plan_ingested | PASS | 1.00 | 0 |

## Mcp (7/7)

Average score: 1.00

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| mcp_stats | PASS | 1.00 | 0 |
| mcp_query | PASS | 1.00 | 0 |
| mcp_context_known | PASS | 1.00 | 0 |
| mcp_context_unknown | PASS | 1.00 | 0 |
| mcp_search_cypher | PASS | 1.00 | 0 |
| mcp_review_all | PASS | 1.00 | 0 |
| mcp_review_json_wellformed | PASS | 1.00 | 0 |

## Cli (6/6)

Average score: 1.00

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| cli_index | PASS | 1.00 | 0 |
| cli_search | PASS | 1.00 | 0 |
| cli_review_brief | PASS | 1.00 | 0 |
| cli_session_lifecycle | PASS | 1.00 | 0 |
| cli_communities | PASS | 1.00 | 0 |
| cli_review_template_wellformed | PASS | 1.00 | 0 |

## Benchmark (2/2)

Average score: 1.00

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| search_coverage | PASS | 1.00 | 0 |
| template_wellformedness | PASS | 1.00 | 0 |

## Efficiency (5/5)

Average score: 0.78

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| efficiency_symbol_understanding | PASS | 0.95 | 0 |
| efficiency_plan_review | PASS | 0.47 | 0 |
| efficiency_codebase_orientation | PASS | 0.88 | 0 |
| efficiency_impact_analysis | PASS | 0.90 | 0 |
| efficiency_code_search | PASS | 0.70 | 0 |

## Readability (9/9)

Average score: 0.99

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| readability_plan_enriched | PASS | 0.97 | 0 |
| readability_plan_baseline | PASS | 1.00 | 0 |
| readability_enriched_vs_baseline | PASS | 0.97 | 0 |
| readability_critique_enriched | PASS | 0.97 | 0 |
| readability_agents_md | PASS | 1.00 | 0 |
| readability_review_brief | PASS | 1.00 | 0 |
| readability_review_challenges | PASS | 0.97 | 0 |
| readability_review_gaps | PASS | 1.00 | 0 |
| readability_no_raw_ids | PASS | 1.00 | 0 |

## Conversation Replay (2/2)

Average score: 1.00

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| conversation_replay | PASS | 1.00 | 0 |
| mid_session_template | PASS | 1.00 | 0 |

## Unknown (3/3)

Average score: 0.78

| Scenario | Passed | Score | Time (ms) |
|----------|--------|-------|-----------|
| graph_enrichment | PASS | 1.00 | 0 |
| graph_enrichment | PASS | 1.00 | 0 |
| graph_enrichment | PASS | 0.33 | 0 |

## A/B Benchmarks

| Scenario | With Graph | Without Graph | Delta |
|----------|-----------|--------------|-------|
| plan_template_enrichment | 3817 | 3032 | +785 |
| agents_md_enrichment | 26323 | 24601 | +1722 |
| critique_enrichment | 6727 | 3326 | +3401 |
| search_mode_coverage | 10 | 10 | +0 |

**plan_template_enrichment**:
- Enriched length: 3817
- Baseline length: 3032
- Delta: 785 chars

**search_mode_coverage**:
- Cypher: 10 results
- Hybrid: 10 results

## Efficiency Gains (Graph vs Baseline Agent)

Compares tokens consumed and tool calls required: an agent using agentscaffold's graph vs. a baseline agent that manually reads files, greps for symbols, and traces dependencies.

| Task | Baseline Tokens | Graph Tokens | Token Reduction | Baseline Calls | Graph Calls | Call Reduction | Compression |
|------|----------------|-------------|----------------|---------------|------------|---------------|-------------|
| symbol_understanding | 3,007 | 80 | 97% | 14 | 1 | 93% | 37.6x |
| plan_review | 2,205 | 2,611 | -18% | 10 | 1 | 90% | 0.8x |
| codebase_orientation | 5,059 | 1,153 | 77% | 39 | 2 | 95% | 4.4x |
| impact_analysis | 2,210 | 259 | 88% | 12 | 1 | 92% | 8.5x |
| code_search | 1,316 | 734 | 44% | 8 | 1 | 88% | 1.8x |

**Aggregate:**

| Metric | Value |
|--------|-------|
| Avg Token Reduction | 58% |
| Avg Call Reduction | 91% |
| Overall Compression | 2.9x |
| Total Baseline Tokens | 13,797 |
| Total Graph Tokens | 4,837 |
| Total Baseline Calls | 83 |
| Total Graph Calls | 6 |

**symbol_understanding** -- Understand DataRouter and its dependents:
- Baseline: 12 reads + 2 greps
- Graph response keys: ['symbol', 'callers', 'callees', 'caller_count', 'callee_count', 'meta']

**plan_review** -- Full review of Plan 042 (Data Router V2):
- Baseline reads 10 files (plan + contracts + learnings + 7 source)
- Graph returns brief, challenges, gaps, verification, retro in 1 call

**codebase_orientation** -- Understand the full codebase structure:
- Baseline: 38 files to read
- Graph stats keys: ['schema_version', 'last_indexed', 'pipeline_state', 'phases_completed', 'files']

**impact_analysis** -- Blast radius of changing libs/data/router.py:
- Direct importers found by graph: 8
- Callers found: 0

**code_search** -- Find all risk-related code:
- Search returned 10 results
- Baseline reads 7 files
