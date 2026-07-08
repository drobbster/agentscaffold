# AgentScaffold Backend Connection Robustness

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-backend-robustness
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: No
- Security Review: None
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package)
- Superseded By: None

## 1. Objective
Make the DuckPGQ backend fail loudly and recoverably instead of silently or fatally when the environment is wrong. Success means: a failed `INSTALL duckpgq` is logged with actionable guidance and the real `LOAD` cause is chained into the raised error; opening a database that another process holds raises a single clear, typed `GraphLockError` (with a short bounded retry) instead of a raw DuckDB `IOException`; the MCP server returns a clean error dict on a lock failure instead of crashing dispatch; and the single-writer assumption is documented.

## 2. Non-Goals
- No multi-writer / connection-pool implementation (DuckDB remains single-writer).
- No change to query semantics, schema, or the async refresh scheduler logic itself.
- No retry on non-lock connection errors (those still raise immediately).

## 3. Constraints / Invariants
- Must not break: existing `open_graph`, pipeline open, `clear_all`, MCP dispatch happy paths.
- Backward compatibility: `DuckPGQBackend(db_path)` signature unchanged; `:memory:` opens never retry.
- Performance constraints: retry backoff bounded (a few hundred ms total) so a genuinely-locked DB fails fast.
- Security constraints: none.
- Data integrity constraints: no change to write paths.
- Breaking change: No.

## 4. Current State
`_load_extension()` swallows the `INSTALL duckpgq` exception with a bare `pass` and only chains the `LOAD` failure. `duckdb.connect` is called raw in `DuckPGQBackend.__init__`, `clear_all()`, and (via the backend) the pipeline open; a lock held by another process surfaces as an unhandled `duckdb.IOException`. In [server.py](src/agentscaffold/mcp/server.py) `open_graph(config)` is called outside the dispatch `try`, so a lock failure crashes the tool call rather than returning an error dict. The single-writer assumption is undocumented.

## 5. Target State
The backend exposes a `GraphLockError` and an internal `_connect()` helper that detects lock errors, retries with bounded exponential backoff, and raises `GraphLockError` with an actionable message naming the likely holder (MCP server or running index). `__init__` and `clear_all` use it. `_load_extension()` logs the INSTALL failure at debug and the LOAD failure at warning while still chaining the cause; `vss` logs at debug when unavailable. The MCP dispatch wraps `open_graph` and returns `{"error": ..., "graph_locked": True}` on `GraphLockError`. `docs/user-guide.md` and the README teams section document single-writer behavior.

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/agentscaffold/graph/duckpgq_backend.py | Modify | Add `GraphLockError`, `_connect()` retry helper, lock detection; use in `__init__`/`clear_all`; extension load diagnostics |
| src/agentscaffold/graph/__init__.py | Modify | Re-export `GraphLockError` |
| src/agentscaffold/mcp/server.py | Modify | Guard `open_graph` in `_dispatch_tool`, return clean error dict on lock |
| docs/user-guide.md | Modify | Single-writer assumption + lock troubleshooting |
| README.md | Modify | Teams section note on single-writer DuckDB |
| tests/test_duckpgq_backend.py | Modify | Tests for lock detection, retry, GraphLockError |
| tests/test_mcp_server.py | Modify/Create | Test dispatch returns clean error dict on lock |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_duckpgq_backend.py | `_is_lock_error`, `_connect` retry/raise, second-open raises `GraphLockError` | Real file-lock contention exercised |
| tests/test_mcp_server.py | `_dispatch_tool` returns `graph_locked` error dict | `open_graph` monkeypatched to raise `GraphLockError` |

Test approach:
- [ ] Unit tests for core logic: lock-error classification and retry exhaustion
- [ ] Integration tests: open a file DB twice and assert `GraphLockError`
- [ ] Edge cases: non-lock errors are not retried; `:memory:` never retries; MCP open guard

## 8. Execution Steps
- [x] Step 1: Add `GraphLockError`, `_is_lock_error`, `_connect()` to `duckpgq_backend.py`; route `__init__` and `clear_all` through it
- [x] Step 2: Add extension-load diagnostics (debug log on INSTALL fail, warning + chained cause on LOAD fail, debug on vss unavailable)
- [x] Step 3: Re-export `GraphLockError` from `graph/__init__.py`
- [x] Step 4: Guard `open_graph` in `_dispatch_tool` to return a clean error dict on `GraphLockError`
- [x] Step 5: Document single-writer assumption in `docs/user-guide.md` and README teams section
- [x] Step 6: Add tests; run ruff + full pytest (579 passed)

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
`git revert` the commit. Changes are additive (a new error type, a retry wrapper, logging, one MCP guard, docs) and contain no migrations, so reverting restores the prior raw-connect behavior.

## 11. Risks & Mitigations
- Risk: retry masks a genuine permanent lock and slows failures. Mitigation: backoff is bounded to a few hundred ms across a handful of attempts, then raises.
- Risk: lock-error detection misclassifies a non-lock IOException. Mitigation: detection requires a lock-specific substring; all other errors propagate unchanged with a regression test.
- Risk: MCP guard hides real open errors. Mitigation: only `GraphLockError` returns `graph_locked`; other exceptions still surface as a generic error dict with the message.

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff, mypy)
- [ ] workflow_state.md updated (batched at release gate)
- [x] Code reviewed (self)
- [x] Approval obtained (not required)
