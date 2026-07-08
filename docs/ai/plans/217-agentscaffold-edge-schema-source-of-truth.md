# AgentScaffold Edge/Node Schema Single Source of Truth

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-schema-source-of-truth
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: No
- Security Review: None
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package)
- Superseded By: None

## 1. Objective
Make the AgentScaffold graph edge identity derive from a single structured source so that adding or changing an edge can no longer drift across the edge DDL, the `CREATE PROPERTY GRAPH` statement, the backend's edge-name tuple, and the schema tests. Success means: edge table names, edge DDL, and the property-graph edge clauses are all generated from one `EDGE_DEFS` list; the backend imports the derived names instead of maintaining its own copy; node-name handling no longer relies on an inline string parse; and a guardrail test fails if the three derived artifacts ever disagree.

## 2. Non-Goals
- No change to the logical schema (no new/removed tables or columns), so `SCHEMA_VERSION` stays at 7.
- Not restructuring node column definitions into data (node DDL strings remain authoritative).
- Not touching the migration/rebuild behavior (covered by Plan 219).
- Not changing `_GOVERNANCE_NODE_TABLES` / `_GOVERNANCE_EDGE_TABLES` semantics (only adding a subset guardrail test).

## 3. Constraints / Invariants
- Must not break: `init_schema()`, `clear_table()`, `clear_derived()`, all existing GRAPH_TABLE queries.
- Backward compatibility: `EDGE_TABLES`, `NODE_TABLES`, `CREATE_PROPERTY_GRAPH_SQL`, `all_edge_ddl()`, `all_node_ddl()` remain importable with the same types (`list[str]` / `str`).
- Performance constraints: none (module-import-time generation only).
- Security constraints: none.
- Data integrity constraints: generated DDL must create the identical set of tables/columns and an equivalent property graph (same vertex/edge set and FK references) as today.
- Breaking change: No.

## 4. Current State
Edge identity is duplicated four times: the `EDGE_TABLES` DDL strings in [duckpgq_schema.py](src/agentscaffold/graph/duckpgq_schema.py) (lines 286-384), the `EDGE TABLES` clause of `CREATE_PROPERTY_GRAPH_SQL` (lines 420-529), the manual `_EDGE_TABLE_NAMES` tuple in [duckpgq_backend.py](src/agentscaffold/graph/duckpgq_backend.py) (lines 39-76), and `expected_edges` in [test_duckpgq_schema.py](tests/test_duckpgq_schema.py) (lines 93-129, already drifted - missing `BACKLOG_ITEM_OF`). `clear_derived()` parses node names with `stmt.strip().split("(")[0].split()[-1]`. Adding `CONFIG_REFERENCES` required edits in all of these places.

## 5. Target State
`duckpgq_schema.py` defines `EDGE_DEFS: list[EdgeDef]` (name, src node, dst node, optional property columns) as the single source. `EDGE_TABLES` (DDL), `EDGE_TABLE_NAMES`, and the edge clause of `CREATE_PROPERTY_GRAPH_SQL` are generated from it; the vertex clause and `NODE_TABLE_NAMES` are derived from `NODE_TABLES` via one centralized name extractor. The backend imports `EDGE_TABLE_NAMES` and `NODE_TABLE_NAMES`. Tests derive their expectations from these constants and a new guardrail asserts the edge DDL, names, and property-graph statement agree.

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/agentscaffold/graph/duckpgq_schema.py | Modify | Add `EdgeDef`, `EDGE_DEFS`, generators; derive `EDGE_TABLES`, `EDGE_TABLE_NAMES`, `NODE_TABLE_NAMES`, `CREATE_PROPERTY_GRAPH_SQL`; update docstring checklist |
| src/agentscaffold/graph/duckpgq_backend.py | Modify | Import `EDGE_TABLE_NAMES`/`NODE_TABLE_NAMES`; drop local `_EDGE_TABLE_NAMES`; replace node-name parse in `clear_derived()` |
| tests/test_duckpgq_schema.py | Modify | Derive expectations from constants; add drift guardrail; add governance-subset guardrail |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_duckpgq_schema.py | Edge/node name derivation, drift guardrail, property graph completeness | Existing tests refactored to derive from constants; new guardrail test added |

Test approach:
- [ ] Unit tests for core logic: names derived == DDL == property graph
- [ ] Integration tests (if applicable): `init_schema` still creates every table; GRAPH_TABLE queries still pass
- [ ] Edge cases: edges with extra property columns (IMPORTS, CALLS, CONFIG_REFERENCES) generate correct DDL; governance tuples are subsets of full names

## 8. Execution Steps
- [x] Step 1: Add `EdgeDef` + `EDGE_DEFS` and the DDL/property-graph generators in `duckpgq_schema.py`; derive `EDGE_TABLES`, `EDGE_TABLE_NAMES`, `NODE_TABLE_NAMES`, `CREATE_PROPERTY_GRAPH_SQL`
- [x] Step 2: Update the module docstring coupling checklist to reflect single-source edges
- [x] Step 3: Update `duckpgq_backend.py` to import `EDGE_TABLE_NAMES`/`NODE_TABLE_NAMES` and remove the duplicated tuple and inline node-name parse
- [x] Step 4: Refactor `test_duckpgq_schema.py` to derive expectations from constants; add drift + governance-subset guardrail tests
- [x] Step 5: Run ruff + full pytest; verify all pass (572 passed). Eval harness deferred to release gate.

## 9. Validation
```bash
ruff format src tests
ruff check src tests
uv run python -m pytest tests -q
uv run python -m pytest eval -q
```

Expected results:
- Ruff: no errors
- Pytest: all tests pass (including new guardrail)

## 10. Rollback Plan
`git revert` the commit. The change is import-time-only and self-contained to three files; reverting restores the hand-maintained constants with no data migration needed.

## 11. Risks & Mitigations
- Risk: generated property-graph SQL differs functionally from the hand-written one. Mitigation: edge order preserved to match current; guardrail test plus existing `init_schema`/GRAPH_TABLE tests confirm the graph registers and queries work.
- Risk: node-name extractor mishandles a DDL form. Mitigation: centralized helper tested against all 20 node tables; `NODE_TABLE_NAMES` asserted against the property graph.

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff, mypy)
- [ ] workflow_state.md updated (batched at release gate)
- [x] Code reviewed (self)
- [x] Approval obtained (not required)
