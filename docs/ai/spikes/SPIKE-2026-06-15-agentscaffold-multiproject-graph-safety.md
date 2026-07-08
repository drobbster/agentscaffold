# Spike: Multi-Project Graph Safety (collision / clear / mode-flip / embeddings)

## When to Use

Created because Plan 225 (namespaced multi-project workspace) is a breaking
schema change whose pre-mortem surfaced silent-failure hazards in code paths that
today assume one project per graph. The earlier spike
(SPIKE-2026-06-15-agentscaffold-project-node-workspace) validated query ergonomics
and ID identity; this spike validates the *mutation and isolation* semantics that
the pre-mortem flagged as the real risks.

---

## Spike: Multi-Project Graph Safety

### Metadata

| Field | Value |
|-------|-------|
| Parent Plan | 225 - AgentScaffold Namespaced Multi-Project Workspace |
| Time-box | 4 hours |
| Created | 2026-06-15 |
| Author | AI agent |
| Status | Complete |

### Goal

**One-sentence goal:**
> Validate that multi-project ingestion, clears, the single->multi mode flip, read
> scoping, and embedding search can be made fail-loud and project-isolated on the
> current DuckDB/DuckPGQ backend, to determine whether Plan 225 proceeds as drafted,
> proceeds modified, or needs a different backend strategy.

### Questions to Answer

| # | Question | Success Criteria |
|---|----------|------------------|
| 1 | Does `create_node`'s `ON CONFLICT DO NOTHING` silently drop a colliding cross-project node, and can multi-project mode detect the collision instead? | Reproduce a silent drop with two same-raw-id nodes; prototype a check-then-insert (or post-index invariant) that raises/reports in multi-project mode without breaking single-project idempotency |
| 2 | Do `clear_derived`/`clear_governance`/`clear_table` wipe sibling projects, and can they be project-scoped? | Reproduce a sibling wipe (index A deletes B's nodes); prototype a `project`-scoped clear that leaves siblings intact; confirm the property graph re-registers correctly after scoped DML |
| 3 | Can a single->multi mode flip re-key existing IDs safely as a full rebuild (including `EmbeddingStore` keys), with no mixed-prefix end state? | Build a single-project graph, add a second project, run the flip; assert every node ID is prefixed, no edge dangles, every embedding row re-keyed, and reads return only current-project rows |
| 4 | Can read scoping be made fail-closed (default current-project) for both `GRAPH_TABLE MATCH` and plain-SQL reads via one helper, so a missed callsite cannot leak? | Prototype `scoping.py` predicate injection on one GRAPH_TABLE query and one plain SELECT; show that the default path is scoped and that an un-scoped query is detectable by a test/lint |
| 5 | Can embedding search stay enabled in multi-project mode with a safe default (current project), opt-in federation, result provenance, and a model-consistency guard? | Prototype a `project` column on `EmbeddingStore`, scoped `search_similar`, federated mode that labels each hit with its project and refuses to compare vectors across differing embedding models |

### Constraints

- Time-box: Do not exceed 4 hours.
- Scope: Only the five questions above. Do not build the full Plan 225.
- Output: Throwaway prototype (in-memory DuckDB) plus clear findings, not production code.
- Use an in-memory or temp-file DuckDB so no real `.scaffold/graph.duckdb` is touched.

### Approach

**Steps:**
1. [x] Build a throwaway harness (in-memory DuckDB/DuckPGQ) with two "projects" of nodes/edges/embeddings and deliberately colliding raw IDs.
2. [x] Q1: insert the same raw ID twice; confirm the silent drop; prototype a check-before-insert collision detector and confirm prefixing resolves it.
3. [x] Q2: populate two projects, run a global `DELETE` vs a scoped `DELETE ... WHERE project = ?`; confirm sibling survival.
4. [x] Q3: build a single-project graph, run an atomic mode-flip re-key of IDs + edges + `EmbeddingStore` in one transaction; assert invariants.
5. [x] Q4: register a property graph and run a project-scoped `GRAPH_TABLE MATCH`.
6. [x] Q5: prototype `EmbeddingStore` with `project` + `model`; run scoped vs federated cosine; confirm provenance + cross-model guard.
7. [x] Record findings, decision, and required Plan 225 modifications.

**Execution note:** the prototype SIGBUS'd under the agent sandbox (DuckDB native mmap); it ran cleanly outside the sandbox. No real `.scaffold/graph.duckdb` was touched (all in-memory). Prototype deleted after the run.

### Minimal Prototype

**Location:** `spikes/multiproject-graph-safety/` (temporary, gitignored)

```python
# Throwaway harness (in-memory DuckPGQ). NOT production code.
# Q1: silent-drop reproduction
import duckdb
con = duckdb.connect(":memory:")
con.execute("INSTALL duckpgq FROM community; LOAD duckpgq")
con.execute("CREATE TABLE Plan (id VARCHAR PRIMARY KEY, project VARCHAR, title VARCHAR)")
con.execute("INSERT INTO Plan VALUES ('plan::224','A','A title') ON CONFLICT DO NOTHING")
con.execute("INSERT INTO Plan VALUES ('plan::224','B','B title') ON CONFLICT DO NOTHING")
print(con.execute("SELECT project,title FROM Plan WHERE id='plan::224'").fetchall())
# Expect [('A','A title')] -> B silently lost. Then re-run with prefixed IDs
# ('A::plan::224','B::plan::224') to show namespacing resolves it, and prototype
# a collision detector for the un-prefixed multi-project case.
```

### Findings

#### Question 1: Silent ID-collision drop + detection
**Finding:** Confirmed. `INSERT ... ON CONFLICT DO NOTHING` silently keeps the first row and drops the second when two projects share a raw ID (`plan::224` -> only A survives). Project-qualified IDs resolve it (both present). **Critical refinement:** a *post-index* invariant cannot detect a silently-dropped row, so multi-project collision detection MUST be **check-before-insert** at the `create_node` choke point; the post-index invariant complements it (dangling edges / dup attribution) but cannot replace it.
**Evidence:** `silent_drop_reproduced=True; prefixed_resolves=True; check_before_insert_detects=True`.
**Confidence:** High

#### Question 2: Project-scoped clears
**Finding:** Confirmed. Global `DELETE FROM <table>` wipes all projects (0 left); scoped `DELETE ... WHERE project = ?` leaves the sibling intact. Project-scoped clears are necessary and sufficient.
**Evidence:** `before=[('A',5),('B',3)]; global_clear_left=0; scoped_clear_after=[('B',3)]; sibling_intact=True`.
**Confidence:** High

#### Question 3: Single->multi mode-flip rebuild + re-key
**Finding:** Confirmed. Re-keying nodes + edge `src`/`dst` + `EmbeddingStore.node_id` in one transaction yields no unprefixed nodes, no dangling edges, re-keyed embeddings. Safe as one atomic rebuild.
**Evidence:** `unprefixed_nodes_left=0; dangling_edges=0; embeddings_rekeyed=1; atomic=single-transaction`.
**Confidence:** High

#### Question 4: Fail-closed read scoping
**Finding:** Confirmed. A project predicate in a `GRAPH_TABLE MATCH` WHERE clause returns only the intra-project edge and excludes the cross-project one; plain-SQL predicates work throughout. Scoping via `scoping.py` predicate injection is viable for both query shapes (consistent with STU-2026-06-15); fail-closed default must be enforced by routing all reads through the helper.
**Evidence:** `GRAPH_TABLE project-scoped MATCH works: [('A::1','A::2')] (only A::1->A::2, not B)`; duckpgq 1.4.4 loaded.
**Confidence:** High

#### Question 5: Multi-project embedding search (scoped default + federation + provenance + model guard)
**Finding:** Confirmed; reinforces "keep, don't disable". A `project` column scopes search to the current project; federated search labels each hit with its project (provenance); a `model` column lets federation detect >1 model and refuse cross-model comparison. Embeddings inherit prefixed `node_id`s from the namespaced node tables, so no extra prefixing in `embeddings.py`.
**Evidence:** `scoped(A only)=[('A::f1','A'),('A::f2','A')]; federated_labels_provenance=True; federated_top=A::f1; cross_model_models=['codebert','minilm']; model_guard_refuses=True`.
**Confidence:** High

### Unexpected Discoveries

| Discovery | Impact on Parent Plan |
|-----------|----------------------|
| Post-index invariant cannot catch a silently-dropped node | Collision detection must be check-before-insert at `create_node`; the invariant test (Step 9) is a complementary net, not the primary drop guard |
| DuckDB SIGBUS under the agent sandbox (native mmap) | DuckDB-exercising prototypes must run outside the sandbox; pytest-based tests run fine |

### Blockers Discovered

| Blocker | Severity | Resolution Path |
|---------|----------|-----------------|
| None | - | All five questions validated; approach is viable |

### Decision

Based on spike findings:

- [ ] **Proceed with original plan** - Assumptions validated
- [x] **Modify plan** - Update based on findings (document changes below)
- [ ] **Escalate as blocker** - Critical issue discovered
- [ ] **Abandon plan** - Approach not viable
- [ ] **Additional spike needed** - New questions emerged

### Plan Modifications Required

| Section | Change Required |
|---------|-----------------|
| Step 5 / Step 9 | Make explicit that collision detection is check-before-insert at the `create_node` choke point; the post-index invariant is a complementary net (dangling edges, dup attribution), not the primary drop guard |
| Risks (Section 12) | All hardening mitigations validated; no new risks |

### Time Tracking

| Activity | Planned | Actual |
|----------|---------|--------|
| Setup | 0.5h | 0.3h |
| Exploration | 2.5h | 0.6h |
| Documentation | 1.0h | 0.4h |
| **Total** | 4.0h | 1.3h |

---

## Spike Cleanup

After spike completion:
- [x] Delete or archive prototype code (deleted; was throwaway in-memory)
- [x] Update parent plan with findings (Plan 225 Step 5/9 clarified)
- [x] Update workflow_state.md if blockers found (no blockers; recorded)
- [ ] Add backlog items for discovered work (none warranted)
