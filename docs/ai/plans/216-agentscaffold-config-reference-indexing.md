# Feature: AgentScaffold Config-Reference Indexing

## 0. Metadata
- Issue: #TBD
- Branch: feature/216-agentscaffold-config-references
- Severity: Medium (closes a real dynamic-dispatch blind spot)
- Approval Required: No (developer tooling; additive graph edge + tool fields)
- Component: ``
- Source: Plan 214 Section 9 (P3) + spike `docs/ai/spikes/SPIKE-2026-06-12-config-reference-resolution.md`
- Architecture Layer(s): Cross-Cutting (developer tooling)
- Breaking change: No (additive node-graph edge; schema version bump rebuilds graph)
- Created: 2026-06-12
- Last Updated: 2026-06-12

## 1. Objective

Config files wire code dynamically (e.g. `configs/strategies/strategy_registry.yaml`
maps `class: libs.strategies.momentum.MomentumStrategy`). The static call graph only
resolves these dispatch points heuristically (Plan 215 showed `handle_strategy_nans`
with 38/39 heuristic callers). Editing such a class shows no config consumer in
`scaffold_impact`, so an agent cannot see that a YAML registry depends on it.

The P3 spike validated that extracting fully-qualified dotted references under an
allowlist of keys resolves at 96.9% precision with zero false positives, concentrated
in high-value registry files. This plan implements that validated, restricted approach.

## 2. Scope
- Add a `CONFIG_REFERENCES` edge (config `File` -> target `File`) to the schema.
- Add a `config_refs` processor: extract FQN dotted references ONLY under an allowlist
  of keys from YAML/JSON/TOML `File` nodes already in the graph (no disk re-walk, so the
  `.mypy_cache` flood is structurally avoided), resolve module -> File (+ optional
  trailing Class/Function, including package `__init__` re-exports), create edges with
  confidence 0.9 (file+symbol) or 0.7 (file-only).
- Wire the processor into the full pipeline (Phase 3) and incremental runs.
- Surface config consumers in `scaffold_impact` and `scaffold_context`.

Out of scope: identifier-only wiring (Prefect flow names, Feast refs), ReviewFinding
memory expansion (separate follow-up).

## 3. File Impact Map

| File | Change |
|------|--------|
| `src/agentscaffold/graph/duckpgq_schema.py` | `CONFIG_REFERENCES` DDL in EDGE_TABLES + CREATE_PROPERTY_GRAPH_SQL edge clause + SCHEMA_VERSION 6 -> 7 |
| `src/agentscaffold/graph/duckpgq_backend.py` | Add `CONFIG_REFERENCES` to `_EDGE_TABLE_NAMES` (cascade/clear coverage) |
| `src/agentscaffold/graph/pipeline.py` | Run `process_config_references` in Phase 3 (full) and in `_run_incremental`; report count in summary |
| `src/agentscaffold/mcp/server.py` | `_tool_impact` and `_tool_context` query + surface config consumers |
| `src/agentscaffold/mcp/render.py` | Render config consumers |
| `src/agentscaffold/graph/config_refs.py` | New: the processor |
| `tests/test_config_refs.py` | New: unit + integration tests |

## 4. Tests

| Test File | Coverage |
|-----------|----------|
| `tests/test_config_refs.py` | FQN extraction respects the key allowlist (allowlisted keys extracted; arbitrary scalars ignored); module-to-file resolution `a.b.c` -> `a/b/c.py` and `a/b/c/__init__.py` with prefix strip (`src/`, `libs/`); trailing Class symbol resolution + confidence assignment; idempotent edge creation dropping stale references; `_tool_impact` / `_tool_context` include `config_consumers` |

## 5. Execution Steps
- [x] 5.1 Schema: add `CONFIG_REFERENCES` DDL + property-graph clause + version bump (6->7); add to `_EDGE_TABLE_NAMES`.
- [x] 5.2 Implement `config_refs.py` (allowlisted-key FQN extract + resolve + edges).
- [x] 5.3 Wire into pipeline (full Phase 3 + incremental) with summary count + table row.
- [x] 5.4 Surface `config_consumers` in `_tool_impact` / `_tool_context` (+ render helper).
- [x] 5.5 Tests (`test_config_refs.py`, 19) + schema guardrail-count updates.
- [x] 5.6 Full suite (565 passed) + ruff clean + live full re-index (64 edges).

## 6. Validation
```bash
uv run python -m pytest -q
uv run ruff check src/agentscaffold/graph/config_refs.py
uv run scaffold index   # full re-index; expect CONFIG_REFERENCES edges > 0
```

## 7. Rollback Plan
Additive. Revert the new processor + schema edge; SCHEMA_VERSION bump back triggers a
clean rebuild. No data migration (graph is a derived cache).

## 8. Retrospective

What worked: the spike's restriction to allowlisted keys paid off exactly as predicted --
a live full re-index produced 64 `CONFIG_REFERENCES` edges, every one from
`configs/strategies/strategy_registry.yaml` resolving to a strategy class at confidence
0.9 (file+symbol), with zero false positives. These are precisely the symbols the static
call graph resolves only heuristically, so the new edges corroborate the low-confidence
dispatch edges Plan 215 surfaces. A line-based extractor (no YAML/JSON/TOML parser
dependency) was sufficient because the high-value references are flat `key: dotted.path`
scalars; this kept the processor dependency-free and uniform across the three formats.

Harder/subtle: the edge had to be registered in three coupled places (EDGE_TABLES DDL,
CREATE_PROPERTY_GRAPH_SQL, and the hand-maintained `_EDGE_TABLE_NAMES` tuple in the
backend) plus two guardrail-count tests -- the schema module docstring warns about the
first two but not the backend tuple. Resolving against `File` nodes already in the graph
(rather than re-walking disk) structurally avoided the `.mypy_cache` flood the spike hit.

Discovered: the local `afterFileEdit` hook fires `scaffold index --incremental` on every
edit, which held the production `graph.duckdb` lock during development -- a good live proof
the hook works, but it forced the verification re-index to run against a temp DB. This is
expected behavior, not a defect.

Net: P3 complete. CONFIG_REFERENCES is additive and rebuilds cleanly on the v7 schema bump.
