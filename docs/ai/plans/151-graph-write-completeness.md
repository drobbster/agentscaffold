# Plan 151: Graph Write Completeness -- Findings Batch + Backlog Nodes

## 0. Metadata
- Plan: 151
- Branch: feature/plan-151-graph-write-completeness
- Author: Dave Robb
- Approval Required: No
- Security Review: None
- Architecture Layer(s): AgentScaffold (agentscaffold)
- Superseded By: None

## 1. Objective

Two governance artifact types are written to markdown files but never reach the graph as
typed nodes: review findings recorded during close-out (vs. mid-review), and backlog items.
The async incremental index picks up the file content as raw text but not as queryable nodes
with relationships, status, or severity.

Success means:
- `scaffold_record_findings_batch` accepts an array of findings and writes all in one call
- `BacklogItem` nodes exist in the graph, queryable by status/priority/plan
- `scaffold_record_backlog_item` and `scaffold_resolve_backlog_item` MCP tools work
- `scaffold_orient` surfaces open backlog items
- `scaffold_prepare_review` surfaces open backlog items alongside open findings
- All existing markdown workflows (backlog.md, backlog_archive.md, plan appendices) are
  unchanged -- graph writes are strictly additive

## 2. Non-Goals
- Retroactive migration of existing backlog.md entries into graph nodes
- Replacing markdown writes -- agent still writes backlog.md and plan appendix as before
- Backlog prioritization UI or ranking beyond the priority field
- Syncing archived items between graph and backlog_archive.md automatically

## 3. Constraints / Invariants
- Must not break: existing `scaffold_record_finding` / `scaffold_resolve_finding` single-item tools
- Must not break: backlog.md format, backlog_archive.md format, plan appendix format
- BacklogItem IDs must follow existing convention: `B-{plan_number}-{sequence}`
- Status values must match existing workflow: open / blocked / unblockable / archived
- Priority values must match existing convention: P1-P5
- Backward compatibility: all existing tests must continue to pass
- Graph schema migration must be additive (new tables only, no column changes to existing)

## 4. Current State

- `scaffold_record_finding`: writes a single ReviewFinding node per call
- No batch findings API -- agent must call N times for N findings
- No BacklogItem node type in graph schema
- "add backlog items to the backlog" writes markdown only; items are not graph-queryable
- "record findings in the plan appendix" writes markdown only; findings not in graph
- `scaffold_orient` does not surface backlog items
- `scaffold_prepare_review` surfaces open ReviewFindings but not backlog items

## 5. Target State

- `scaffold_record_findings_batch(plan_number, review_type, findings[])`: writes all
  findings in one DB transaction, returns array of IDs + count
- `BacklogItem` node table: id (B-{plan}-{seq}), plan_number, title, priority, effort,
  status, source, created_at, archived_at
- `scaffold_record_backlog_item`: creates BacklogItem node
- `scaffold_resolve_backlog_item`: marks item archived, sets archived_at
- `scaffold_orient`: includes open backlog count + top 3 by priority
- `scaffold_prepare_review`: includes open backlog items for the plan alongside open findings
- NL trigger phrases in intent map for all new tools
- Batch findings NL triggers route to `scaffold_record_findings_batch`

## 6. File Impact Map

| File | Change Type | Notes |
|------|------------|-------|
| `src/agentscaffold/graph/findings.py` | Modify | Add `record_findings_batch()` |
| `src/agentscaffold/graph/backlog.py` | New | BacklogItem schema + CRUD |
| `src/agentscaffold/graph/structure.py` | Modify | Add BacklogItem to schema init |
| `src/agentscaffold/mcp/server.py` | Modify | Add 3 new tools + NL triggers |
| `src/agentscaffold/review/orient.py` | Modify | Add open backlog to orient output |
| `src/agentscaffold/review/queries.py` | Modify | Add backlog queries for prepare_review |
| `tests/test_backlog.py` | New | BacklogItem CRUD + MCP tool tests |
| `tests/test_findings_batch.py` | New | Batch findings write tests |
| `CLAUDE.md` | Modify | Add NL triggers for new tools |

## 7. Tests

| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| `tests/test_backlog.py` | BacklogItem CRUD, status transitions, orient query | Unit + integration against real DuckDB |
| `tests/test_findings_batch.py` | Batch write, empty array, single item, duplicate IDs | Unit + integration |

Test approach:
- [x] Unit tests for core logic (backlog CRUD, batch write)
- [x] Integration tests against real in-memory DuckDB (no mocks)
- [x] Edge cases: empty batch, single item batch, archived item re-archive attempt, backlog item with no sequence collision

## 8. Execution Steps

- [x] Step 1: Add `BacklogItem` table to graph schema (duckpgq_schema.py)
- [x] Step 2: Implement `src/agentscaffold/graph/backlog.py`
  - `record_backlog_item()`, `record_backlog_items_batch()`, `resolve_backlog_item()`,
    `get_open_backlog_items()`, `get_backlog_items_for_plan()`
- [x] Step 3: Add `record_findings_batch()` to findings.py
- [x] Step 4: Add backlog queries to review/queries.py for prepare_review
- [x] Step 5: Update orient (in server.py `_tool_orient`) to include open backlog count + top 3
- [x] Step 6: Add 3 new MCP tools to server.py:
  - `scaffold_record_findings_batch`
  - `scaffold_record_backlog_item` (supports both single and batch mode)
  - `scaffold_resolve_backlog_item`
- [x] Step 7: Add NL trigger phrases to server.py `TOOL_INTENTS` and `_TOOL_SIGNAL_TOKENS`
- [x] Step 8: Update CLAUDE.md intent map with new trigger phrases
- [x] Step 9: Write tests (test_backlog.py: 26 tests, test_findings_batch.py: 16 tests)
- [x] Step 10: Run full test suite -- 467 pass, 2 pre-existing failures unchanged
- [x] Step 11: Live test all three new MCP tools end-to-end -- all working

## 9. Validation

```bash
cd .
ruff check src/ --fix
ruff format src/
python -m pytest tests/test_backlog.py tests/test_findings_batch.py -v
python -m pytest tests/ -q --tb=short
```

Expected results:
- Lint: no errors
- New tests: all pass
- Existing tests: no regressions

## 10. Rollback Plan

All changes are additive. New tables only -- no changes to existing schema. If rollback
needed: `git revert` the commits, delete `.scaffold/graph.db` and re-index to drop the
new tables.

## 11. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| BacklogItem table missing on existing graph.db | `CREATE TABLE IF NOT EXISTS` -- safe on any existing DB |
| Batch write partial failure (some findings written, some not) | Wrap in explicit transaction |
| orient query too slow on large graph | Limit to top 3 items, add index on status + plan_number |
| ID collision on B-{plan}-{seq} | Check existence before insert, return existing ID if duplicate |

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing (42 new tests: 26 backlog + 16 findings_batch)
- [x] No linter errors
- [x] workflow_state.md updated
- [ ] Backlog items for any discovered follow-ups added to backlog.md
