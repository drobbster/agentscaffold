# Spike: AgentScaffold Benchmark Feasibility

Time-boxed exploration to de-risk Plan 229 (AgentScaffold Benchmark: an installed `scaffold benchmark ...` tool that compares an agentscaffold-equipped agent against a baseline agent on real tasks). Uncertainty is High because it requires live model calls, real metric capture, agent code execution isolation, an objective definition of task success/review efficacy, and a clean product boundary between the installed benchmark tool and the deterministic eval harness.

---

## Spike: AgentScaffold Benchmark (agentscaffold vs baseline)

### Metadata

| Field | Value |
|-------|-------|
| Parent Plan | 229 - AgentScaffold Benchmark |
| Time-box | 4 hours |
| Created | 2026-06-15 |
| Author | AI agent |
| Status | Complete |

### Goal

**One-sentence goal:**
> Validate that an installed `scaffold benchmark` tool can run two agent arms (agentscaffold-equipped vs baseline) on the same task and repo state, capture real per-arm token/call/wall-clock metrics and an objective task-success signal, by adapting the in-repo `packages/gitnexus/eval/` harness on a tiny task set, to decide whether Plan 229 proceeds as an installed `agentscaffold.benchmark` package, a thin wrapper around/fork of gitnexus/eval, or is descoped.

### Questions to Answer

| # | Question | Success Criteria |
|---|----------|------------------|
| 1 | Can we orchestrate two parallel agent arms on identical task + repo state, where arm A has the agentscaffold MCP server + generated rules/hooks and arm B has plain tools? | A single command shaped like `scaffold benchmark run ...` runs both arms on one task and returns two transcripts without cross-contamination of repo state |
| 2 | Can we capture real, per-arm metrics (LLM tokens, API/tool calls, wall-clock, agentscaffold tool-call counts) rather than the estimated proxies the deterministic harness uses? | A metrics record per arm with non-zero real token + call counts sourced from the model/runner, not `estimate_tokens` |
| 3 | Can we define an objective task-success signal and a review-efficacy signal (e.g., a planted regression the stricter/equipped arm should catch) that is gradeable without a human? | At least one task with a programmatic pass/fail (tests go green) and one task with a planted defect that produces a binary "caught/not caught" outcome |
| 4 | How much of `packages/gitnexus/eval/` (modes, prompt template pairs, Docker env, parallel workers, `analysis/compare-modes`) is directly reusable vs needs rewriting for an MCP-based installed `agentscaffold.benchmark` command? | A concrete reuse/rewrite list with an effort estimate and final runtime boundary: `src/agentscaffold/benchmark/` vs eval-only fixtures |
| 5 | What is the isolation/safety posture and per-run cost? | A documented sandbox/isolation approach for agent-executed commands and a rough USD cost per task per model |

### Constraints

- Time-box: Do not exceed 4 hours.
- Scope: Only validate the five questions above on 1-2 tiny tasks and 1 cheap model. Do not build the production framework.
- Output: Working throwaway prototype OR clear findings, not production code.
- Cost: Use the cheapest viable model and a 1-2 task slice; cap spend.
- Safety: Agent-executed commands must run inside an isolated environment (container or equivalent); do not run untrusted agent commands directly on the host.

### Approach

**Steps:**
1. [x] Read `packages/gitnexus/eval/run_eval.py`, `environments/gitnexus_docker.py`, `agents/gitnexus_agent.py`, and the mode/prompt config pairs to inventory the reusable orchestration spine and decide what belongs in installed package code vs offline eval fixtures.
2. [x] Assess the agentscaffold arm design: index a fixture repo, expose `scaffold_*` tools through container-local wrappers/MCP, and confirm required runtime dependencies and isolation controls.
3. [x] Assess the baseline arm design with plain tools and identical task + repo state.
4. [x] Assess prototype command shape and metric capture requirements. Live arm execution was not run because the current environment lacks `minisweagent`, `litellm`, and `datasets`, and live model calls require explicit key/cost approval.
5. [x] Adapt the gitnexus `analyze_results compare-modes` pattern into a concrete `scaffold benchmark doctor/run/compare/report` recommendation; record reuse vs rewrite, final CLI surface, and cost controls.

### Minimal Prototype

**Location:** `spikes/live-benchmark/` (gitignored or temporary)

```python
# Throwaway: prototype the future `scaffold benchmark run` flow.
# Drive two arms on one task, capture real metrics, compare.
# NOT production code -- prioritize answering the 5 questions over quality.
# Likely a thin wrapper around the gitnexus/eval runner with:
#   - an agentscaffold arm (MCP server + generated rules in the env)
#   - a baseline arm (plain tools)
#   - a per-arm metrics sink (tokens, calls, wall-clock, gn/scaffold tool calls)
#   - one tests-go-green task + one planted-defect task
#   - a final recommendation for src/agentscaffold/benchmark/ module layout
```

### Findings

#### Question 1: Parallel two-arm orchestration on identical state
**Finding:** Feasible with modification. Reuse the gitnexus eval runner's per-instance worker model and Docker environment pattern, but make AgentScaffold Benchmark an installed `agentscaffold.benchmark` package rather than importing `packages/gitnexus/eval` directly.

**Evidence:** `packages/gitnexus/eval/run_eval.py` already implements `single`, `matrix`, `debug`, config merging, per-run output directories, resumable `preds.json`, and threaded `process_instance(...)` execution. `packages/gitnexus/eval/environments/gitnexus_docker.py` shows the required container setup pattern: start Docker, install the tool, index the repo, start a local eval server, install standalone command wrappers, then run the agent in isolated `/testbed` state.

**Confidence:** Medium-high for orchestration and state isolation. Live proof remains pending because model-run dependencies and keys were not installed/provided in this environment.

#### Question 2: Real per-arm metric capture
**Finding:** Feasible. The gitnexus harness already captures real `agent.cost`, `agent.n_calls`, trajectory `model_stats`, and tool-specific metrics. AgentScaffold Benchmark should preserve this metrics sink and rename/generalize the tool metrics from `gitnexus_metrics` to `scaffold_metrics`.

**Evidence:** `run_eval.py::process_instance` records `cost`, `n_calls`, and `gitnexus_metrics`; `agents/gitnexus_agent.py::GitNexusMetrics` tracks tool calls, augmentation calls/hits/errors, augmentation time, and index time; `analysis/analyze_results.py::compute_metrics` reads trajectory `model_stats.instance_cost` and `model_stats.api_calls`.

**Confidence:** Medium. The metric fields are proven in the existing harness shape, but Plan 229 must verify the same fields across the chosen mini-swe-agent/model versions and expose a `doctor` check when metrics are unavailable.

#### Question 3: Objective task-success + review-efficacy signals
**Finding:** Feasible, but do not depend on SWE-bench alone for the first AgentScaffold Benchmark release. Use two task families: tests-go-green tasks graded by command exit status, and planted-defect review tasks graded by deterministic expected finding IDs/categories in the transcript or report.

**Evidence:** Gitnexus uses SWE-bench predictions and optional official SWE-bench evaluation (`analysis/analyze_results.py::run_swebench_evaluation`) for objective pass/fail. Plan 228's deterministic eval fixtures already provide small project fixtures and report result types that can seed a cheaper AgentScaffold-specific task set before larger SWE-bench slices.

**Confidence:** Medium. Tests-go-green grading is straightforward. Review-efficacy grading needs carefully designed planted defects and a transcript parser so it does not become another proxy metric.

#### Question 4: gitnexus/eval reuse vs rewrite + installed tool boundary
**Finding:** Reuse concepts and small helper patterns, not direct package imports. The runtime should live under `src/agentscaffold/benchmark/` with an optional `benchmark` extra. Gitnexus eval code is valuable prior art but is repo-local, SWE-bench-specific, and has GitNexus-specific naming/tool wrappers throughout.

**Evidence:** Directly reusable ideas: YAML model/mode config merge, `single`/`matrix`/`debug` command structure, per-arm output directories, thread worker execution, trajectory/result schema, `compare-modes` style reporting, Docker environment setup sequence, and tool-usage metric tracking. Rewrite/adapt: `GitNexusDockerEnvironment`, `GitNexusAgent`, prompt templates, tool scripts, `gitnexus_metrics`, SWE-bench dataset loader defaults, and hardcoded `eval` package paths.

**Confidence:** High. The installed-package boundary is clear: production runtime belongs in `agentscaffold.benchmark`; recorded/offline tests belong in `tests/test_benchmark_*.py` and optional `eval/live/` fixtures.

#### Question 5: Isolation/safety posture and per-run cost
**Finding:** Docker isolation should be mandatory for `run`; live model calls must be opt-in with explicit `--max-cost-usd`, `--max-tasks`, and `--workers` bounds. `doctor` and `dry-run` should be implemented before live execution.

**Evidence:** Docker is available locally (`Docker version 28.5.1`, server `29.1.3`). The current Python environment does not have `minisweagent`, `litellm`, or `datasets`, so Plan 229 needs a `benchmark` optional extra and a dependency doctor. Gitnexus mode configs use `cost_limit: 3.0` per agent run; AgentScaffold Benchmark should default lower for smoke runs and require explicit flags for larger matrices.

**Confidence:** High for required controls; medium for exact cost defaults until a live smoke is run with the chosen cheap model.

### Unexpected Discoveries

| Discovery | Impact on Parent Plan |
|-----------|----------------------|
| The existing gitnexus harness is not installed-package-ready; it assumes repo-local `eval` imports and GitNexus-specific command wrappers. | Plan 229 should implement `agentscaffold.benchmark` modules instead of importing gitnexus eval directly. |
| The current environment has Docker but lacks `minisweagent`, `litellm`, and `datasets`. | Add `agentscaffold[benchmark]`, `scaffold benchmark doctor`, and CI-safe dependency tests before live run support. |
| A live prototype needs model keys and explicit cost approval. | Keep live smoke manual/opt-in; do not make live benchmark part of deterministic CI or plan readiness validation. |
| Review-efficacy grading is the hardest new metric. | Include at least one planted-defect task with deterministic grading in Plan 229 before claiming caught-bug evidence. |

### Blockers Discovered

| Blocker | Severity | Resolution Path |
|---------|----------|-----------------|
| Live arm execution was not run in this spike because model-run dependencies are absent and live API keys/cost approval were not available in-session. | Major | Plan 229 should start with offline runtime tests plus `doctor`; live smoke remains a manual gate requiring explicit keys and budget. |

### Decision

Based on spike findings:

- [ ] **Proceed with original plan** - Assumptions validated
- [x] **Modify plan** - Update based on findings (document changes below)
- [ ] **Escalate as blocker** - Critical issue discovered
- [ ] **Abandon plan** - Approach not viable
- [ ] **Additional spike needed** - New questions emerged

**Decision:** Proceed with modifications. The architecture is feasible, but Plan 229 should be implemented as an installed `agentscaffold.benchmark` package with offline-first tests, `doctor` and `dry-run` gates, an optional dependency extra, Docker-required live execution, and explicit cost/key controls. Do not claim live cost/caught-defect evidence until the manual live smoke has been run.

### Plan Modifications Required

| Section | Change Required |
|---------|-----------------|
| Plan 229 Metadata | Keep Approval Required: Yes and Security Review: Full; mark spike complete and keep Ready blocked until threat model + explicit approval are done |
| Plan 229 File Impact Map | Finalize installed `src/agentscaffold/benchmark/` module layout; add `pyproject.toml` optional `benchmark` extra |
| Plan 229 CLI / docs | Confirm command names: `scaffold benchmark doctor/run/compare/report`; add `--dry-run`, `--max-cost-usd`, `--max-tasks`, `--workers`, and explicit live-run confirmation |
| Plan 229 Tests | Prioritize offline unit tests for config merge, arm construction, metric parsing, report formatting, and planted-defect grading; keep live smoke manual |
| Plan 229 Security | Add threat model covering container escape, secret leakage, prompt/tool injection, unbounded spend, artifact contamination, and supply-chain risks |

### Time Tracking

| Activity | Planned | Actual |
|----------|---------|--------|
| Setup | 1h | 0.5h |
| Exploration | 2h | 1.5h |
| Documentation | 1h | 1h |
| **Total** | 4h | 3h |

---

## Spike Cleanup

After spike completion:
- [x] Delete or archive prototype code (none created)
- [x] Update Plan 229 with findings
- [x] Update workflow_state.md if blockers found
- [x] Add backlog items for discovered work (none; items fold into Plan 229)
