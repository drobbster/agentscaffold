# AgentScaffold Durable / Ephemeral Storage

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-durable-storage
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: Yes (changes storage/persistence behavior and adds an env override)
- Security Review: Partial (new persistence location handling + env-driven path expansion)
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package)
- Superseded By: None
- Source: STU-2026-06-14-agentscaffold-multiproject-collab-durability (Thread 3, Option A). Depends on Plan 221 (db_path resolution) and Plan 222 (governance artifact as the durable system of record).

## 1. Objective
Make one committed `scaffold.yaml` work safely in both persistent and ephemeral (devbox/Codespaces-style) environments, so deleting the local cache never loses governance. Success means: (a) `db_path` supports `${ENV}` expansion and an `AGENTSCAFFOLD_DB_PATH` env override so the same config points at a tmp/scratch path in ephemeral boxes and a durable path elsewhere; (b) on first `scaffold index` when the local cache is absent, governance auto-restores from the durable system of record (the Plan 222 git-committed artifact); and (c) the workflow is documented so an operator on an ephemeral box can rebuild a full graph from git alone.

## 2. Non-Goals
- Not building a network sync service or object-store backend (env-expandable paths cover mounted volumes; object store is a documented future extension, not built here).
- Not making DuckDB multi-writer or shared-live (the cache stays local/derived).
- Not changing the governance serialization format (owned by Plan 222).
- Not adding scheduled/automatic background export (export is tied to existing record/index events).

## 3. Constraints / Invariants
- Must not break: existing absolute/relative `db_path` behavior; `scaffold index`; Plan 221 root-relative `db_path` resolution; Plan 222 governance write-through/ingest.
- Backward compatibility: Required. A `db_path` with no `${...}` and no env override must resolve exactly as it does post-Plan-221. The env override is opt-in.
- Performance constraints: env expansion and the missing-cache check are negligible; auto-restore cost is bounded by governance volume (small).
- Security constraints: env expansion must only expand named environment variables (no shell execution); an unset referenced variable is a clear error, not a silent empty path. Document that `AGENTSCAFFOLD_DB_PATH` controls where the cache lives.
- Data integrity constraints: auto-restore must never overwrite a non-empty existing cache; restore only populates when the cache is absent/empty, and reports what it restored.
- Breaking change: No (additive env expansion + override + restore-on-missing).

## 4. Current State
`db_path` defaults to `.scaffold/graph.duckdb` under the project; after Plan 221 it resolves relative to the project root. There is no `${ENV}` expansion and no env-var override, so a single committed `scaffold.yaml` cannot point at a persistent location in one environment and a scratch location in an ephemeral one. There is no auto-restore: if `.scaffold/` is deleted on an ephemeral devbox, the local governance cache is gone and `scaffold index` rebuilds only derived code data (governance is empty) unless Plan 222's committed artifact is ingested. Plan 222 establishes that artifact as the durable system of record; this plan makes storage location portable and wires restore-on-missing.

## 5. Target State
`db_path` resolution (the Plan 221 resolver) gains `${ENV_VAR}` expansion and honors `AGENTSCAFFOLD_DB_PATH` (override wins over config). `scaffold index` detects an absent/empty cache and, before/with indexing, restores governance from the Plan 222 committed artifact, reporting counts. The user guide documents the ephemeral pattern: commit `scaffold.yaml` + governance artifact, set `AGENTSCAFFOLD_DB_PATH=$TMPDIR/...` (or a mounted volume) on the devbox, and `scaffold index` reproduces the full graph from git.

```mermaid
flowchart LR
    cfg["scaffold.yaml db_path: ${AGENTSCAFFOLD_DB_PATH:-.scaffold/graph.duckdb}"] --> res["resolve db_path (env expand + override)"]
    res --> miss{"cache present?"}
    miss -->|no| restore["restore governance from git artifact (Plan 222)"]
    miss -->|yes| idx
    restore --> idx["scaffold index"]
    idx --> graph["DuckDB graph (derived, ephemeral-safe)"]
```

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/agentscaffold/paths.py | Modify | Add `${ENV}` expansion + `AGENTSCAFFOLD_DB_PATH` override in db_path resolution (built on Plan 221) |
| src/agentscaffold/graph/__init__.py | Modify | `open_graph`/`_resolve_db_path` use the env-aware resolver |
| src/agentscaffold/graph/pipeline.py | Modify | On absent/empty cache, restore governance from the Plan 222 artifact before indexing; report counts |
| src/agentscaffold/config.py | Modify | Allow `${ENV}` placeholders in `db_path`; document env-override precedence |
| src/agentscaffold/cli.py | Modify | Surface restore summary in `scaffold index` output |
| docs/user-guide.md | Modify | Add "Ephemeral devboxes" workflow + AGENTSCAFFOLD_DB_PATH |
| docs/configuration.md | Modify | Document db_path env expansion + override precedence |
| tests/test_db_path_resolution.py | Create | env expansion, override precedence, unset-var error, no-placeholder backward-compat |
| tests/test_ephemeral_restore_integration.py | Create | delete cache -> reindex restores governance from artifact; non-empty cache not overwritten |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_db_path_resolution.py | `${ENV}` expansion; `AGENTSCAFFOLD_DB_PATH` override beats config; unset referenced var raises clear error; plain path unchanged | Unit, monkeypatched env |
| tests/test_ephemeral_restore_integration.py | cache deleted -> `scaffold index` restores governance from committed artifact with reported counts; existing non-empty cache untouched | Integration, real DuckDB + Plan 222 artifact |

Test approach:
- [x] Unit tests for db_path env expansion + override precedence
- [x] Integration test for restore-on-missing-cache from the governance artifact
- [x] Edge cases: unset env var (raises); override to absolute/relative tmp path; non-empty cache (not flagged as restore); no artifact present (empty governance, no error)

## 8. Execution Steps
- [x] Step 0: Consumer audit -- all `db_path` consumers route through `paths.resolve_db_path` (Plan 221); env handling added there in one place
- [x] Step 1: Added `${ENV}`/`~` expansion + `AGENTSCAFFOLD_DB_PATH` override (with clear error on an unset referenced var); wrote `test_db_path_resolution.py`
- [x] Step 2: `open_graph` + pipeline already route through the env-aware resolver
- [x] Step 3: Implemented restore-on-missing-cache (governance phase ingests the Plan 222 artifact idempotently; `run_pipeline` flags `restored_from_artifact` only when the cache was absent and records were restored)
- [x] Step 4: Surfaced the restore summary in `scaffold index`; added the ephemeral restore integration test
- [x] Step 5: Documented the durable/ephemeral workflow in `configuration.md` + CHANGELOG; ran full validation

**Implementation note**: The resolver is the single choke point for `db_path`, so
env override + expansion live entirely in `paths.resolve_db_path`. An unset
`${VAR}` raises a clear `ValueError` rather than producing a wrong path. The
restore mechanism reuses Plan 222's `process_governance` artifact ingest (no
separate restore path); Plan 223 adds the cache-absent detection and operator
reporting. Documented in `configuration.md` rather than `user-guide.md` (the
latter is a prompting playbook).

## 9. Validation
```bash
cd .
ruff format .
ruff check .
pytest -q
```

Expected results:
- Ruff: no errors
- Pytest: all tests pass; deleting the cache and reindexing reproduces governance from git

## 10. Rollback Plan
Revert the feature branch. Env expansion, the override, and restore-on-missing are additive; reverting restores plain `db_path` resolution from Plan 221. No data migration to reverse (the durable artifact is owned by Plan 222 and untouched by a rollback here).

## 11. Risks & Mitigations
Env expansion could be abused or misconfigured; mitigate by expanding only named environment variables (no shell), and raising a clear error on an unset referenced variable rather than producing an empty/wrong path. Auto-restore could clobber a populated cache; mitigate by restoring only when the cache is absent/empty and reporting counts. The dependency on Plan 222's artifact means restore is a no-op (empty governance) if that artifact is missing; mitigate by documenting the dependency and making "no artifact" a clean empty-governance path, not an error. Ephemeral `AGENTSCAFFOLD_DB_PATH` pointing at a volume that is itself wiped is acceptable because git remains the system of record; document this explicitly.

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors (ruff, mypy)
- [x] workflow_state.md updated
- [x] Session log entry added (if multi-session)
- [x] Code reviewed (self or peer)
- [x] Approval obtained (if required) -- approved 2026-06-14 with the 221->223 chain
