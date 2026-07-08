# Feature: AgentScaffold Benchmark (Live Two-Arm Benchmarking)

## 0. Metadata
- Issue: #TBD
- Branch: feature/agentscaffold-benchmark
- Author: AI agent
- Reviewers: Dave Robb
- Approval Required: Yes (external API integration -- runs live LLM calls against user-provided keys; executes agent-generated commands in an isolated environment; see Approval Gates and Security Review)
- Security Review: Full (external API integration + agent-executed commands; create/update a threat model in docs/security/ before Ready)
- Architecture Layer(s): Cross-Cutting (AgentScaffold tooling package -- opt-in live evaluation)
- Superseded By: None
- Status: In Progress (spike complete; threat model approved; implementation approval recorded 2026-06-16)
- Uncertainty: Medium (spike complete 2026-06-16; live smoke still requires explicit keys/cost approval)
- Dependencies: Plan 228 (deterministic eval result types and report scaffolding to reuse); SPIKE-2026-06-15-agentscaffold-live-benchmark-harness (COMPLETE, decision: proceed with modifications); Full threat model and explicit approval before implementation
- Source: Eval-harness review follow-up 2026-06-15. Builds on the in-repo prior art `packages/gitnexus/eval/` (SWE-bench baseline vs graph-enhanced harness) and the deterministic agentscaffold eval harness. Product framing updated 2026-06-16: this should ship as the installed **AgentScaffold Benchmark** tool (`scaffold benchmark ...`), not as a repo-local eval-only script.

## 1. Objective
Provide an opt-in, installed user-runnable tool -- **AgentScaffold Benchmark** -- that empirically answers "does agentscaffold help?" by running two agent arms on the same task and repo state and comparing real outcomes. Success means a user can run `scaffold benchmark ...` from an installed package and, for a curated task set and chosen model:

1. Runs **arm A (equipped)**: an agent with the agentscaffold MCP server plus generated rules/hooks available, and **arm B (baseline)**: the same agent/model with only plain tools (grep/read/edit), on identical task + repo state, in parallel and isolated from each other.
2. Captures **real per-arm metrics** -- LLM tokens, API/tool calls, wall-clock, and agentscaffold tool-call counts -- sourced from the model/runner (not the `estimate_tokens` proxy used by the deterministic harness).
3. Grades **objective task success** (e.g., the task's tests go green) and at least one **review-efficacy** outcome (a planted regression that the equipped/stricter arm should catch and the baseline arm misses), so "benefit" is ground-truth rather than a proxy.
4. Emits a **comparison report** (per-arm and aggregate: success rate, tokens, calls, cost, wall-clock, caught-defect rate) reusing the deterministic harness's report scaffolding and the gitnexus `compare-modes` analysis pattern, with multiple seeds and reported variance so results are not single-shot.
5. Remains **out of the deterministic CI suite** -- it is explicitly opt-in (keys, cost, non-determinism). Runtime code lives under the installed package; offline fixtures/tests can live under the deterministic eval harness.

## 2. Non-Goals
- Not a replacement for the deterministic harness (Plan 228); that stays the fast, offline, every-commit signal. Benchmark may reuse report/result concepts, but it is a separate installed command surface.
- Not a public leaderboard or a claim of universal speedup; it is a self-service tool for users to test on their own tasks/models.
- Not tied to a single model or provider; model selection is config-driven (litellm/OpenRouter-style, mirroring gitnexus/eval).
- Not SWE-bench itself, though it may borrow SWE-bench instances; the curated task set is the deliverable.
- Not the rigor cost-benefit proxy (Plan 228); this framework supplies the ground-truth efficacy that the proxy approximates.

## 3. Constraints / Invariants
- Must not break: the deterministic harness or existing product code. Benchmark runtime code is isolated under `src/agentscaffold/benchmark/`; CI-safe offline fixtures/tests may live under `eval/live/` or `tests/`.
- Isolation/safety: agent-generated commands MUST run inside an isolated environment (container or equivalent); never directly on the host. Repo state for the two arms must not cross-contaminate.
- Secrets: API keys are user-provided via env/`.env` only; never committed, never logged. Follow the package's secrets handling.
- Cost control: runs are explicitly bounded (task slice, worker count, model choice, max spend) and report cost; no unbounded matrix by default.
- Reproducibility: fixed task set + commit pinning + recorded model config + multiple seeds with reported variance.
- Determinism boundary: this arm is non-deterministic by nature; results report distributions/intervals, not single numbers, and it is excluded from CI gates.
- Breaking change: No (additive, opt-in, isolated).

## 4. Current State
There is no live, LLM-driven benchmark for agentscaffold. The deterministic harness (`eval/`, extended by Plan 228) measures capability gains using `estimate_tokens` proxies and risk-adjusts them by adoption/replay behavior, but it never invokes a real model and cannot measure caught-bug rate or real cost. It is also repo-local test/eval code, not an installed user tool. The closest prior art is `packages/gitnexus/eval/`, a SWE-bench harness that already implements the two-arm pattern this plan needs: `baseline` vs `native`/`native_augment` modes, per-model YAML configs, system/instance prompt-template pairs, Docker per-instance environments, parallel workers, and `analysis/analyze_results.py compare-modes`, capturing patch/resolve rate, cost, tokens, API calls, and tool-usage stats. None of that is wired for an MCP-based agentscaffold arm or exposed as `scaffold benchmark`.

## 5. Target State
A new opt-in installed **AgentScaffold Benchmark** tool:
- Exposes a `scaffold benchmark` CLI group with `doctor`, `run`, `compare`, and `report` subcommands. `doctor` and `run --dry-run` land before live execution.
- Defines two arms (equipped MCP+rules vs baseline plain-tools) and a model/config layer adapted from gitnexus/eval's mode/model YAML pattern.
- Runs a curated, commit-pinned task set with objective pass criteria and at least one planted-defect (review-efficacy) task, in a mandatory Docker/container environment, in parallel, across multiple seeds.
- Captures real per-arm metrics and writes a comparison report (reusing deterministic-harness report concepts and the gitnexus `compare-modes` analysis), reporting success rate, caught-defect rate, tokens, calls, cost, and wall-clock with variance.
- Enforces explicit live-run bounds: API key detection via `doctor`, `--max-cost-usd`, `--max-tasks`, `--workers`, and a live-run confirmation flag. Live runs never execute in CI.
- Ships user docs (setup, keys, cost expectations, how to add tasks/models, and how to interpret noisy live results) so users can benchmark on their own repos.
- Keeps CI-safe offline fixture tests separate from live execution. Spike result: reuse gitnexus/eval concepts and schemas, but implement installed runtime under `agentscaffold.benchmark` rather than importing repo-local gitnexus eval modules directly.

## 6. File Impact Map
> Provisional -- finalized after the spike. Listed to satisfy planning structure; concrete files confirmed at Ready.

| File | Change Type | Notes |
|------|-------------|-------|
| src/agentscaffold/benchmark/__init__.py | Create | Installed AgentScaffold Benchmark package marker |
| src/agentscaffold/benchmark/adapter.py | Create | Guarded mini-swe-agent Docker adapter; optional dependency checks, workspace copy, setup/wrapper install, agent run, validation, trajectory extraction |
| src/agentscaffold/benchmark/cli.py | Create | CLI command implementations for `scaffold benchmark doctor/run/compare/report` |
| src/agentscaffold/benchmark/models.py | Create | Built-in selectable model metadata; provider/API-key/pricing-source fields |
| src/agentscaffold/benchmark/runner.py | Create | Run request validation and dry-run planning; live orchestration to follow |
| src/agentscaffold/benchmark/arms.py | Create | Arm definitions: equipped setup/tracking vs baseline plain-tools control |
| src/agentscaffold/benchmark/environment.py | Create | Isolated per-task workspace setup and container setup script rendering |
| src/agentscaffold/benchmark/metrics.py | Create | Serializable result schema, trajectory metric extraction, per-arm fields, and aggregation |
| src/agentscaffold/benchmark/tasks.py | Create | Curated task metadata and deterministic graders incl. >=1 tests-go-green and >=1 planted-defect task |
| src/agentscaffold/benchmark/configs/models/ | Create | Per-model YAML (litellm/OpenRouter-style), adapted from gitnexus/eval |
| src/agentscaffold/benchmark/report.py | Create | Two-arm comparison report for saved summaries; includes seed pass-rate ranges when multiple seeds exist |
| src/agentscaffold/benchmark/tool_wrappers.py | Create | Container-local `scaffold-*` wrappers for equipped-arm tool use |
| src/agentscaffold/benchmark/doctor.py | Create | Dependency/API-key/Docker/pricing readiness checks used by `scaffold benchmark doctor` and live-run preflight |
| pyproject.toml | Modify | Add optional `benchmark` extra (`mini-swe-agent`, `litellm`, `datasets`, etc.); do not add these heavy/live deps to the base install |
| src/agentscaffold/cli.py | Modify | Register `benchmark` Typer group and subcommands |
| eval/live/ | Create | CI-safe recorded fixtures / offline tests for benchmark logic, if useful after spike |
| tests/test_benchmark_*.py | Create | Offline unit tests of CLI wiring, arm construction, metric parsing, report formatting, task pass/defect grading logic (no live calls) |
| docs/benchmarking.md | Create | User guide: setup, keys, cost, adding tasks/models, interpreting results |
| docs/security/threat_model_agentscaffold_live_benchmark.md | Create | Full security review: external API + agent-executed-command threat model; blocks implementation until reviewed/approved |
| CHANGELOG.md | Modify | Note the opt-in live benchmarking framework |

## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_benchmark_*.py and/or eval/live/tests/test_live_harness_offline.py | Arm construction, metric parsing from recorded transcripts, report formatting, task pass/defect grading logic, CLI doctor/run dry-run behavior | Runs fully offline against recorded fixtures (no live LLM calls), so it is CI-safe |
| (manual/opt-in) live smoke | One task, one cheap model, both arms produce metrics + a comparison report | Documented manual run; not in CI; gated on keys + cost flag |

Test approach:
- [x] Offline unit tests cover the implemented logic that does not require a live model (model listing, API-key/pricing checks, live-request validation, dry-run behavior, task grading, metric aggregation, compare/report)
- [x] `doctor` and `run --dry-run` foundations are tested offline; full Docker/deps/key/cost-cap live fail-closed coverage remains part of the live-runner slice
- [ ] Live behavior validated via a documented, opt-in smoke run (not in CI) on one cheap model + one task
- [ ] Edge cases: missing API key (clear error, no run), one arm crashes (other still reported), zero-defect task, cost cap hit (graceful stop) (missing deps/key fail-closed covered offline; crash/cost-cap behavior needs live smoke/follow-up)

## 8. Execution Steps
- [x] Step 0: Gate -- complete SPIKE-2026-06-15-agentscaffold-live-benchmark-harness and record its decision; do not proceed past Ready until the threat model exists and approval is recorded
- [x] Step 1: Create the Full threat model in docs/security/ (external API + agent-executed commands; isolation, secrets, cost) and obtain approval
- [x] Step 2: Add `benchmark` optional dependency extra and `doctor` readiness checks (Docker, deps, API key presence, pricing source)
- [x] Step 3: Implement `scaffold benchmark` CLI group with `doctor`, `run --dry-run`, `run`, `compare`, and `report`
- [x] Step 4: Implement isolated per-task environment + the two arms (equipped MCP+rules vs baseline), adapting gitnexus/eval's Docker/tool-wrapper pattern for AgentScaffold
- [x] Step 5: Implement real per-arm metric capture (tokens/calls/wall-clock/scaffold tool calls/cost) and fail-closed behavior when metrics are unavailable
- [x] Step 6: Build the curated task set (>=1 tests-go-green, >=1 planted-defect review-efficacy task), commit-pinned
- [x] Step 7: Implement the comparison report (reuse deterministic report scaffolding + compare-modes pattern; multi-seed variance)
- [ ] Step 8: Write offline unit tests against recorded fixtures (CI-safe); document the opt-in live smoke run (offline tests complete; injected-runner/fake-adapter tests complete; live smoke execution pending)
- [ ] Step 9: User docs (`docs/benchmarking.md` or `docs/live-benchmarking.md`) + CHANGELOG; full validation (docs/changelog complete; live smoke result pending)

## 9. Validation
```bash
cd .
ruff format src/agentscaffold/benchmark/ tests/
ruff check src/agentscaffold/benchmark/ tests/
pytest -q tests/test_benchmark_*.py        # offline, CI-safe
python ../../scripts/lint_plan_cohesion.py --plan 229
# Opt-in (manual, requires API key + cost flag; NOT in CI):
# scaffold benchmark doctor
# scaffold benchmark run --model <cheap-model> --task-slice 0:1 --max-cost-usd <usd> --confirm-live
```

Expected results:
- Ruff + mypy: no errors in `src/agentscaffold/benchmark/`
- Offline tests: arm wiring, metric parsing, grading, and report formatting pass without any live model call
- Doctor/dry-run: missing Docker/deps/keys/cost caps produce clear fail-closed messages without starting live arms
- Opt-in live smoke: both arms produce real metrics and a comparison report on one task/model
- Plan lint: no errors for Plan 229

Current validation note (2026-06-16): offline benchmark validation passes
(`ruff`, `mypy`, `pytest -q tests/test_benchmark_*.py` = 23 passed; plan lint
0 errors/0 warnings). Manual live smoke was not run because `minisweagent`,
`litellm`, `datasets`, and `OPENROUTER_API_KEY` are absent in the current
environment.

## 10. Rollback Plan
Revert the feature branch. The tool is isolated under `src/agentscaffold/benchmark/` and is opt-in (never invoked by CI or ordinary product flows), so reverting removes it cleanly with zero runtime impact outside the `scaffold benchmark` command. No data migrations.

## 11. Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Agent-executed commands harm the host | Low | High | Mandatory isolated environment (container/equivalent); never run on host; covered by Full threat model and Step 1 approval gate |
| API keys leaked via logs/commits | Low | High | Keys via env/`.env` only; never logged or committed; follow package secrets handling; documented in threat model |
| Results too noisy to be conclusive (single-shot LLM variance) | High | Medium | Multiple seeds; report distributions/intervals; fixed task set + commit pinning |
| Cost runs away on a full matrix | Medium | Medium | Bounded by default (task slice, workers, model, max-spend cap that stops gracefully); cost reported per run |
| Curated tasks bias toward agentscaffold strengths | Medium | Medium | Include tasks where the graph is irrelevant; document task provenance; allow users to add their own tasks |
| Heavy maintenance vs gitnexus/eval drift | Medium | Low | Reuse gitnexus/eval spine where the spike shows it is sound; document the reuse boundary |
| Non-determinism leaks into CI | Low | Medium | Live arm explicitly excluded from CI; only offline fixture tests run in CI |
| Benchmark dependencies bloat base install | Medium | Low | Put `mini-swe-agent`, `litellm`, `datasets`, and related live deps behind `agentscaffold[benchmark]`; `doctor` explains missing deps |

## 12. Security Review (Full)
This framework introduces two trust-boundary-crossing surfaces and therefore requires a Full threat model in `docs/security/` before reaching Ready:
- **External API integration.** It sends task prompts and repo content to a user-configured LLM provider using user-provided keys. Threat model must cover key handling (env/`.env` only, never logged/committed), data egress (what repo content leaves the machine), and provider trust.
- **Agent-executed commands.** Each arm runs an autonomous agent that generates and executes shell commands against a repo. Threat model must cover isolation (container/equivalent, no host execution), repo-state containment between arms, resource limits, and cost caps. Approval (per Approval Gates: external API integrations) is required before implementation; record approval in workflow_state.md before Step 3.

Threat model created and approved: `docs/security/threat_model_agentscaffold_live_benchmark.md`.

Implementation approval recorded 2026-06-16 after the spike review.

## 13. Completion Checklist
- [ ] All execution steps checked off
- [ ] Tests written and passing (offline CI-safe suite)
- [ ] No linter errors (ruff, mypy)
- [ ] Threat model created and approved
- [ ] workflow_state.md updated
- [ ] Session log entry added (if multi-session)
- [ ] Code reviewed (self or peer)
- [ ] Approval obtained (required: Yes)
