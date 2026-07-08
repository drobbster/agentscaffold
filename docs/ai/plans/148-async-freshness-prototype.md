# Async Freshness Prototype for AgentScaffold MCP

## 0. Metadata
- Issue: #TBD
- Branch: feature/148-async-freshness-prototype
- Author: AI Agent
- Reviewers: TBD
- Approval Required: No
- Security Review: None
- Architecture Layer(s): Cross-Cutting
- Superseded By: None

## 1. Objective
Ship a feature-flagged async freshness prototype for `agentscaffold` so MCP request-path latency stays in milliseconds while graph refresh happens in the background with debounce and single-flight locking.

## 2. Non-Goals
- Rewriting incremental indexing engine internals.
- Making async freshness the default for all users immediately.
- Building watcher-mode filesystem daemons.

## 3. Constraints / Invariants
- Must not break: existing MCP tool outputs and replay/adoption eval suites.
- Backward compatibility: freshness feature is off unless enabled by config.
- Performance constraints: request-path freshness checks must stay lightweight; no synchronous reindex in MCP handlers.
- Security constraints: no new external network dependencies.
- Data integrity constraints: only one in-flight refresh worker per workspace process.
- Breaking change: No

## 4. Current State
`scaffold index --incremental` is too slow for request-path preflight on large repos. MCP tools currently open graph synchronously and do not expose freshness states or background refresh coordination.

## 5. Target State
When enabled, MCP tools compute a cheap freshness status (`fresh`, `stale`, `unknown`, `refreshing`) and return it in response metadata. Eligible composite tools/gates schedule background incremental refreshes via debounce + lock coordinator without blocking tool responses.

## 6. File Impact Map
| File | Change Type | Notes |
|-----|------------|-------|
| src/agentscaffold/config.py | Modify | Add freshness config schema and defaults |
| src/agentscaffold/templates/scaffold_yaml.yaml.j2 | Modify | Add freshness config block |
| src/agentscaffold/mcp/server.py | Modify | Integrate oracle/coordinator and metadata |
| src/agentscaffold/mcp/freshness.py | Add | Oracle + background refresh coordinator |
| tests/test_config.py | Modify | Assert freshness defaults/load behavior |
| tests/test_mcp_freshness.py | Add | Unit tests for oracle/coordinator behavior |
| dev_docs/async_freshness_default_on_readiness_checklist.md | Add | Default-on rollout gate checklist |
| dev_docs/preflight_freshness_latency_study.md | Modify | Record phase-2 stress results |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_mcp_freshness.py | Core freshness logic | Status classification, debounce, lock, scheduling |
| tests/test_config.py | Config schema | Freshness defaults and YAML parse |
| eval/scenarios/test_adoption.py | Regression | Ensure routing unaffected |
| eval/scenarios/test_replay_adoption.py | Regression | Ensure replay metrics unaffected |
| tests/test_mcp_freshness.py::test_single_flight_parallel_triggers | Concurrency | Validate one trigger under parallel calls |
| tests/test_mcp_freshness.py::test_running_no_queue_mode | Concurrency | Validate no-queue behavior when running |

Test approach:
- [x] Unit tests for core logic
- [x] Integration tests (targeted regression suites)
- [x] Edge cases: missing git context, debounce suppression, in-flight refresh coalescing

## 8. Execution Steps
- [x] Step 1: Add freshness config schema and scaffold template defaults.
- [x] Step 2: Implement freshness oracle and async refresh coordinator module.
- [x] Step 3: Wire freshness metadata and scheduling into MCP dispatch path.
- [x] Step 4: Add unit tests for freshness module and config behavior.
- [x] Step 5: Run targeted test suites and fix regressions.
- [x] Step 6: Add phase-2 readiness checklist and concurrency stress tests.

## 9. Validation
```bash
ruff check src/agentscaffold tests
pytest tests/test_mcp_freshness.py -q
pytest tests/test_config.py -q
pytest eval/scenarios/test_adoption.py -q
pytest eval/scenarios/test_replay_adoption.py -q
```

Expected results:
- Ruff: no errors
- Pytest: all tests pass

## 10. Rollback Plan
Revert freshness feature files/changes and set `freshness_async_enabled: false` in config. Existing MCP behavior remains as current baseline.

## 11. Risks & Mitigations
- Risk: Background refresh thread races or duplicate refreshes. Mitigation: single-flight lock and coalescing tests.
- Risk: Incorrect freshness status in non-git environments. Mitigation: explicit `unknown` state and warning metadata.
- Risk: Metadata contract drift for tools. Mitigation: additive `freshness` block under `meta` only.

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff, mypy)
- [x] workflow_state.md updated
- [x] Session log entry added (if multi-session) -- N/A (single-session execution)
- [x] Code reviewed (self or peer)
- [x] Approval obtained (if required) -- N/A (Approval Required: No)
