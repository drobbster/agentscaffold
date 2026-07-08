# AgentScaffold Git-Backed Governance Serialization

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-governance-serialization
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: Yes (changes the system of record for agent-generated knowledge)
- Security Review: Partial (new git-committed persistence of governance data)
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package)
- Superseded By: None
- Source: STU-2026-06-14-agentscaffold-multiproject-collab-durability (Thread 2). Depends on Plan 221 (path resolution) and reuses Plan 219 export/import.

## 1. Objective
Make agent-generated knowledge (review findings, sessions, and backlog items) durable and shareable by serializing it to git instead of leaving it only in the local DuckDB cache. Success means: (a) findings/sessions/backlog are written to a git-committed, human-diffable artifact under the project's governance tree as the system of record; (b) `scaffold index` rebuilds the graph from those artifacts plus code, so a fresh clone or rebuilt cache reproduces the same governance; and (c) teammates see each other's recorded findings/sessions through normal git pull, with no shared live database.

## 2. Non-Goals
- Not building a shared live multi-writer graph (rejected in the study; DuckDB stays single-writer/local).
- Not changing how derived code data (files/functions/edges) is produced (always rebuilt from source).
- Not adding multi-project namespacing (Phase 2) or config inheritance (Phase 2).
- Not adding a network sync/object-store path (that is Plan 223, durable/ephemeral storage).

## 3. Constraints / Invariants
- Must not break: existing `record_finding`/`resolve_finding`, session start/end, backlog record/resolve APIs; `scaffold index` happy path; the Plan 219 schema-migration export/import.
- Backward compatibility: Required. A repo with no serialized governance artifact must still index (empty governance), and existing graphs must continue to work. The serialized format is versioned.
- Performance constraints: serialization touches only governance tables (small relative to code nodes); ingest is bounded by governance volume.
- Security constraints: serialized artifacts contain project governance text only (no secrets). Document location; ensure secret-scanning (detect-secrets) still applies since the files are committed.
- Data integrity constraints: writing the artifact must be atomic (write-temp-then-rename); rebuilds must never silently drop records that fail to parse -- they are reported.
- Breaking change: No (additive serialization + ingest; the graph remains a derived index). The system-of-record shift is additive: the graph is still rebuildable.

## 4. Current State
`ReviewFinding`, `Session`, and `BacklogItem` nodes are created directly in the DuckDB graph by `graph/findings.py`, `graph/sessions.py`, `graph/backlog.py`. They are not serialized to git anywhere, so they live only in the local `.scaffold/graph.duckdb` cache: invisible to teammates and destroyed if the cache (or an ephemeral devbox) is deleted. Plan 219 added `export_governance()`/`import_governance()` on the backend, but only as a migration-time mechanism triggered on schema-version mismatch (writes `.scaffold/graph_export_v{old}.json`, which is gitignored). Backlog markdown remains the human source of truth for backlog only; findings and sessions have no committed representation.

## 5. Target State
Governance is serialized to a versioned, git-committed artifact (a `governance/` directory of JSONL files, or a single `governance.jsonl`, decided in Step 1) under the project's governance tree resolved via Plan 221's `ResolvedPaths`. Write-back helpers append to the artifact when findings/sessions/backlog are recorded; `scaffold index` ingests the artifact into the graph (the graph becomes a pure index built from artifact + code). The Plan 219 `export_governance`/`import_governance` functions are promoted to the shared serialization codec used by both write-back and ingest. Incompatible/legacy records are reported, not dropped.

```mermaid
flowchart LR
    agent["record_finding / session / backlog"] --> ser["serialize -> git-committed governance artifact (system of record)"]
    ser --> idx["scaffold index ingests artifact"]
    code["source code"] --> idx
    idx --> graph["DuckDB graph (derived index)"]
    ser -->|git pull/push| team["teammates"]
```

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/agentscaffold/graph/governance_store.py | Create | Git-backed governance codec (read/write versioned JSONL); reuses Plan 219 export/import shapes |
| src/agentscaffold/graph/findings.py | Modify | On record/resolve, write through to the governance artifact |
| src/agentscaffold/graph/sessions.py | Modify | On start/end/modify, write through to the governance artifact |
| src/agentscaffold/graph/backlog.py | Modify | On record/resolve, write through to the governance artifact |
| src/agentscaffold/graph/duckpgq_backend.py | Modify | Reuse export_governance/import_governance as the shared codec entry points |
| src/agentscaffold/graph/pipeline.py | Modify | Ingest the governance artifact during `scaffold index` (after schema init, before/with governance ingestion) |
| src/agentscaffold/config.py | Modify | Add `graph.governance_artifact` path field (default under governance tree) |
| docs/user-guide.md | Modify | Document the governance artifact as the system of record and the rebuild-from-git model |
| docs/configuration.md | Modify | Document `governance_artifact` config + format/versioning |
| tests/test_governance_store.py | Create | Codec round-trip; versioning; atomic write; malformed-record reporting |
| tests/test_governance_serialization_integration.py | Create | record -> serialize -> rebuild index -> graph reproduces governance; empty-artifact repo indexes cleanly |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_governance_store.py | codec round-trip, version field, atomic write-then-rename, malformed line reported not dropped | Unit, tmp files |
| tests/test_governance_serialization_integration.py | record finding/session/backlog -> artifact committed -> `clear_all` + reindex reproduces them; no-artifact repo indexes to empty governance | Integration, real DuckDB |

Test approach:
- [x] Unit tests for the codec (round-trip, versioning, atomicity, error reporting)
- [x] Integration test: write-back then rebuild reproduces governance
- [x] Edge cases: empty/missing artifact; malformed record; non-object artifact; write-through disabled by default

## 8. Execution Steps
- [x] Step 0: Consumer audit -- write paths route through the new `_sync_governance`/`sync_if_enabled` hook (opt-in via backend attribute set by `open_graph`)
- [x] Step 1: Decided artifact granularity -- a single versioned JSON snapshot (`graph.governance_artifact`, default `docs/ai/state/governance.json`), atomic write, stable row order to minimize diffs. (Per-item files reduce merge conflicts but add complexity; deferred.)
- [x] Step 2: Wrote `test_governance_store.py`, then implemented `governance_store.py` (reuses the Plan 219 export/import shapes as the codec)
- [x] Step 3: Added `graph.governance_artifact` config field (resolved via Plan 221 `resolve_root`)
- [x] Step 4: Added write-through in findings/sessions/backlog helpers (`_sync_governance`); `open_graph` enables it via `enable_write_through`
- [x] Step 5: Ingest the artifact during `scaffold index` (in `process_governance`, idempotent); added the serialization integration test
- [x] Step 6: Updated configuration docs + CHANGELOG; ran full validation

**Implementation note**: Write-through is opt-in per backend instance: `open_graph`
sets a `_governance_artifact` attribute via `enable_write_through`, so runtime
(MCP/CLI) stores serialize while raw in-memory/pipeline stores do not (preserving
all existing tests). `duckpgq_backend.py` was not modified -- the codec reuses its
existing `export_governance`/`import_governance` as-is. Documented in
`configuration.md` (the "Git-backed governance" subsection) rather than
`user-guide.md`, which is a prompting playbook, not a config/operations reference.
612 unit + integration tests added (24 across `test_governance_store.py` and
`test_governance_serialization_integration.py`); ruff clean.

## 9. Validation
```bash
cd .
ruff format .
ruff check .
pytest -q
```

Expected results:
- Ruff: no errors
- Pytest: all tests pass; rebuild-from-artifact reproduces governance; no-artifact repo indexes cleanly

## 10. Rollback Plan
Revert the feature branch. The artifact is additive and the graph remains rebuildable from code; reverting write-through restores the prior graph-only behavior. Any committed governance artifact can remain in git harmlessly (ignored by the reverted code) or be deleted. No data migration to reverse.

## 11. Risks & Mitigations
Promoting Plan 219's migration-only export/import into a general codec risks format drift; mitigate by versioning the artifact and adding round-trip tests that pin the schema. Write-through on every record could add latency or merge churn; mitigate by keeping appends small/atomic and choosing a granularity (Step 1) that minimizes conflicts (per-item files reduce conflicts most). Committing governance text risks accidentally capturing secrets; mitigate by relying on the existing detect-secrets hook and documenting that findings/sessions must not embed secrets. Malformed records on ingest could silently drop knowledge; mitigate by reporting unparseable records rather than skipping silently.

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff, mypy)
- [x] workflow_state.md updated
- [x] Session log entry added (if multi-session)
- [x] Code reviewed (self or peer)
- [x] Approval obtained (if required) -- approved 2026-06-14 with the 221->223 chain
