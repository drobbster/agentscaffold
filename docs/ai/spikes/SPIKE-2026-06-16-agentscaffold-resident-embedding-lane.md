# Spike: AgentScaffold Resident Embedding Lane

### Metadata

| Field | Value |
|-------|-------|
| Parent Plan | Plan 232: AgentScaffold Async Embedding Lane and Resident Embedder |
| Time-box | 2-4 hours |
| Created | 2026-06-16 |
| Author | AI-assisted (Dave Robb) |
| Status | Complete |

### Goal

**One-sentence goal:**
> Validate whether AgentScaffold should host a resident embedding model in the MCP server, or fall back to short-lived subprocess embedding, by measuring model load/memory and checking MCP/DuckDB concurrency constraints.

### Questions to Answer

| # | Question | Success Criteria |
|---|----------|------------------|
| 1 | Is the resident `all-MiniLM-L6-v2` footprint acceptable for an opt-in MCP lane? | Model loads from local cache, memory footprint is bounded and lazy, and `async_embeddings: off` loads no model |
| 2 | Would embedding work block MCP request handling? | Embedding is not run on the request handler path; a background worker can be used |
| 3 | Can the MCP process safely write embeddings while serving requests / holding other graph connections? | Separate backend connections in one process can coexist and write/read embedding rows; scheduler must still yield to the structural index lock |

### Constraints

- Time-box: Do not exceed 4 hours.
- Scope: Only validate feasibility; do not implement production scheduler code.
- Output: Clear decision and parent-plan modifications, not production code.

### Approach

**Steps:**
1. [x] Inspect MCP server request handling and graph open/close lifecycle.
2. [x] Measure embedding model readiness, cold load time, cached load time, encode latency, and RSS delta in `.venv-scaffold`.
3. [x] Probe same-process DuckDB backend concurrency with two connections and an `EmbeddingStore` write.
4. [x] Record decision and required Plan 232 changes.

### Minimal Prototype

**Location:** none. The spike used throwaway inline scripts only; no prototype files were retained.

Model/memory measurement command:

```bash
cd /Users/daverobb/rebellion-trading-system
uv run python - <<'PY'
import resource
import time
from agentscaffold.config import load_config
from agentscaffold.graph.embeddings import _get_model, model_ready

cfg = load_config()
model_name = cfg.search.embedding_model
cache_dir = cfg.search.cache_dir

def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)

print(model_ready(model_name, cache_dir))
rss0 = rss_mb()
t0 = time.perf_counter()
model = _get_model(model_name, cache_dir)
t1 = time.perf_counter()
rss1 = rss_mb()
print(t1 - t0, rss1 - rss0)
t2 = time.perf_counter()
model2 = _get_model(model_name, cache_dir)
t3 = time.perf_counter()
print(model is model2, t3 - t2)
model.encode(["function calculates moving average", "class handles graph indexing"], show_progress_bar=False)
print(rss_mb())
PY
```

DuckDB concurrency probe command:

```bash
cd /Users/daverobb/rebellion-trading-system/agentscaffold
uv run python - <<'PY'
# Create a temp graph, open two DuckPGQBackend connections in one process,
# write one embedding via the second connection, and read it through the first.
PY
```

### Findings

#### Question 1: Is the resident model footprint acceptable?
**Finding:** Acceptable only as an opt-in, lazy lane. Do not load the model when `graph.async_embeddings: off`.
**Evidence:** `model_ready=True`; cold model load from `.scaffold/models` took 1.743s. The process RSS rose from 415.5 MB to 451.3 MB after model load (+35.8 MB), then to 504.7 MB after encoding two texts. Cached second load reused the same object and took 0.000234s. The live MCP process before resident model load was 64,224 KiB RSS.
**Confidence:** Medium. RSS includes Python/ML import overhead and macOS `ru_maxrss` high-water behavior, but the order of magnitude is clear.

#### Question 2: Would embedding work block MCP request handling?
**Finding:** It would block if run directly from the MCP `call_tool` path; it is feasible if run in a background worker.
**Evidence:** `mcp/server.py` uses async MCP handlers, but `call_tool` calls synchronous `_dispatch_tool(...)` directly. `_dispatch_tool` opens the graph, handles the request synchronously, and closes the store in a `finally` block. The existing `mcp/freshness.py` coordinator already uses a daemon thread for background incremental indexing, which is the right pattern to reuse for embedding scheduling.
**Confidence:** High.

#### Question 3: Can the MCP process safely write embeddings while serving graph requests?
**Finding:** Same-process multiple DuckDB backend connections can coexist for the needed embedding write/read path, but the embedding lane must still yield to the structural index lock and use single-flight/coalescing.
**Evidence:** A temp-graph probe opened two `DuckPGQBackend` connections in one Python process, wrote one `EmbeddingStore` row through the second, and read it through the first: `concurrent_connections_write_visible=1`.
**Confidence:** Medium. This validates same-process connection coexistence, but not every possible concurrent write interleaving. The scheduler should serialize its own writes and respect `.scaffold/index.lock`.

### Unexpected Discoveries

| Discovery | Impact on Parent Plan |
|-----------|----------------------|
| The existing freshness coordinator already implements a thread-based single-flight/coalesced pattern. | Reuse/parallel that design for the embedding scheduler instead of inventing a new coordinator model. |
| MCP handlers are async wrappers around synchronous dispatch. | Embedding must not run inside `_dispatch_tool`; scheduling must return immediately and work in a background thread. |
| Live MCP RSS is modest (~64 MB) before model load, while embedding import/load/encode can push a process toward ~500 MB RSS in the measurement script. | Resident model must be strictly opt-in and lazy; default `off` is important. |

### Blockers Discovered

| Blocker | Severity | Resolution Path |
|---------|----------|-----------------|
| None | Minor | Proceed with modified plan. |

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
| Target State | Make the in-process resident embedder the preferred implementation when `async_embeddings != off`, running in a background worker. Keep subprocess fallback only for failures or future hardening, not the primary path. |
| Execution Steps | Reuse/parallel `mcp/freshness.py` coordinator semantics: per-root state, debounce, single-flight, coalescing, daemon thread, state in MCP meta. |
| Constraints / Risks | Add explicit memory guard: no model load under `off`; lazy load only after scheduling; surface load/error state; yield to `.scaffold/index.lock`. |
| Tests | Add tests that `off` does not import/load the model, scheduler returns immediately, and a simulated structural lock defers embedding. |

### Time Tracking

| Activity | Planned | Actual |
|----------|---------|--------|
| Setup | 15 min | 10 min |
| Exploration | 2-3 hrs | 45 min |
| Documentation | 30 min | 20 min |
| **Total** | 2-4 hrs | ~75 min |

---

## Spike Cleanup

After spike completion:
- [x] Delete or archive prototype code
- [x] Update parent plan with findings
- [x] Update workflow_state.md if blockers found (none found)
- [x] Add backlog items for discovered work (none required; Plan 232 already owns follow-up work)
