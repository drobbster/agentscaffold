# Threat Model: AgentScaffold Benchmark

## Overview

| Field | Value |
|-------|-------|
| Component | AgentScaffold Benchmark (`scaffold benchmark`) |
| Author | AI agent |
| Date | 2026-06-16 |
| Version | 1.0 |
| Status | Approved |

## 1. Description

AgentScaffold Benchmark is a planned opt-in, installed command surface for comparing an AgentScaffold-equipped agent arm against a baseline plain-tools arm on the same task and repository state. It runs live LLM calls, captures real cost/token/call metrics, and executes agent-generated commands in isolated environments.

This threat model covers Plan 229 before implementation. It is required because the benchmark crosses two major trust boundaries: external LLM API calls and autonomous command execution.

## 2. Assets

| Asset | Classification | Impact if Compromised |
|-------|----------------|----------------------|
| LLM API keys | Confidential | High: credential theft, unauthorized spend |
| Repository contents sent to providers | Internal / Confidential | Medium-High: source/data egress |
| Host filesystem and developer machine | Confidential | High: arbitrary command execution or data loss |
| Benchmark outputs and transcripts | Internal | Medium: may contain source snippets, secrets, prompts, patches |
| Cost budget | Internal | Medium: unbounded API spend |
| Benchmark result integrity | Internal | Medium: misleading product/cost conclusions |

## 3. Data Flow

```text
User CLI
  -> benchmark doctor / dry-run preflight
  -> task loader + model config
  -> isolated per-arm environment
      -> baseline arm: live LLM + plain tools
      -> equipped arm: live LLM + AgentScaffold MCP/rules/tool wrappers
  -> per-arm transcripts, metrics, patch/output artifacts
  -> comparison report
```

### Trust Boundaries

| Boundary | Description | Controls |
|----------|-------------|----------|
| Host -> isolated environment | Agent-generated commands execute in task environments, not directly on host | Docker/container required for live run; no host execution mode in initial release |
| Local repo -> LLM provider | Prompts, code snippets, tool output, and task context may leave machine | Explicit live confirmation; docs disclose data egress; user-provided model config |
| CLI -> secrets | API keys read from env/`.env` | `doctor` checks presence without printing values; never write keys to reports/logs |
| Live run -> cost budget | Agents can loop or call expensive models | Required `--max-cost-usd`, task limits, worker limits, step/cost caps |
| Arm A -> Arm B | Equipped and baseline arms must not share mutable repo state | Per-arm isolated workdirs/containers; commit/task pinning |

## 4. Threat Actors

| Actor | Capability | Motivation | Likelihood |
|-------|------------|------------|------------|
| Malicious benchmark task/repo | Controls files, tests, prompts, package scripts | Escape sandbox, steal secrets, bias results | Medium |
| Compromised dependency | Code execution during install/run | Supply chain compromise | Low-Medium |
| External LLM/provider | Receives prompts/code/tool output | Data retention or unintended disclosure | Medium |
| User misconfiguration | Runs large matrix or host-like environment | Accidental cost/data exposure | Medium |
| Local attacker/process | Reads artifacts or env | Credential/data theft | Low |

## 5. Attack Vectors

### Vector 1: Container Escape or Host Mutation

| Field | Value |
|-------|-------|
| Description | Agent-generated commands mutate host files or escape the intended task environment |
| Prerequisites | Live benchmark runs without container isolation or with unsafe mounts |
| STRIDE Category | Elevation / Tampering |
| Likelihood | Medium |
| Impact | High |
| Risk Score | Medium x High |

**Mitigation:**
- [ ] Require Docker/container isolation for `scaffold benchmark run` live mode.
- [ ] Keep each arm in its own throwaway workdir/container.
- [ ] Mount only the task repo/workdir required for the run; avoid broad host mounts.
- [ ] Provide `--dry-run` to show planned mounts/commands before live execution.

### Vector 2: API Key Leakage

| Field | Value |
|-------|-------|
| Description | API keys are printed, stored in reports, copied into containers, or committed |
| Prerequisites | Logging/env handling leaks secret values |
| STRIDE Category | Information Disclosure |
| Likelihood | Medium |
| Impact | High |
| Risk Score | Medium x High |

**Mitigation:**
- [ ] `doctor` reports only key presence/provider, never key values.
- [ ] Reports redact env vars matching key/secret/token patterns.
- [ ] Do not persist `.env`; require user-managed env or ignored local file.
- [ ] Include detect-secrets/pre-commit coverage for benchmark fixtures.

### Vector 3: Unbounded Spend

| Field | Value |
|-------|-------|
| Description | Benchmark matrix runs too many tasks/models/seeds or agent loops until high cost |
| Prerequisites | Missing or unenforced cost/task/step limits |
| STRIDE Category | Denial of Service |
| Likelihood | Medium |
| Impact | Medium |
| Risk Score | Medium x Medium |

**Mitigation:**
- [ ] Require `--max-cost-usd` for live runs.
- [ ] Enforce per-agent step/cost limits from config.
- [ ] Default to one cheap model, one task, one seed for smoke.
- [ ] Stop gracefully and report partial results when caps are hit.

### Vector 4: Prompt/Tool Injection from Repo Content

| Field | Value |
|-------|-------|
| Description | Repository files instruct the agent to exfiltrate secrets, ignore rules, or alter results |
| Prerequisites | Agent consumes untrusted repo text as instructions |
| STRIDE Category | Tampering / Information Disclosure |
| Likelihood | Medium |
| Impact | Medium-High |
| Risk Score | Medium x Medium-High |

**Mitigation:**
- [ ] System prompts distinguish repo content from instructions.
- [ ] No secrets are mounted into task containers except required provider env.
- [ ] Benchmark tasks should avoid real private repos by default.
- [ ] Reports include warnings when tasks are user-provided/untrusted.

### Vector 5: Misleading Benchmark Results

| Field | Value |
|-------|-------|
| Description | Non-determinism, task bias, or arm contamination produces false cost/benefit claims |
| Prerequisites | Single-shot runs, shared state, or curated tasks favor one arm |
| STRIDE Category | Repudiation / Tampering |
| Likelihood | High |
| Impact | Medium |
| Risk Score | High x Medium |

**Mitigation:**
- [ ] Use multiple seeds and report variance.
- [ ] Pin task commits and record model config/version.
- [ ] Include graph-irrelevant tasks and planted-defect tasks.
- [ ] Keep per-arm state isolated and report any arm failures separately.

## 6. Security Controls

### Existing Controls

| Control | Type | Effectiveness |
|---------|------|---------------|
| Existing secret scanning/pre-commit hooks | Detective | Medium |
| Plan 228 deterministic offline harness | Detective | Medium |
| Gitnexus eval prior art uses Docker per SWE-bench task | Preventive | Medium |

### Required Controls

| Control | Priority | Plan Reference | Status |
|---------|----------|----------------|--------|
| Mandatory container isolation for live `run` | P1 | Plan 229 Step 4 | Pending |
| `doctor` checks for Docker, benchmark deps, API key presence, and live-run caps | P1 | Plan 229 Step 2 | Pending |
| Required `--max-cost-usd` and explicit live confirmation | P1 | Plan 229 Step 3 | Pending |
| Secret redaction in logs/reports | P1 | Plan 229 Step 5/7 | Pending |
| Offline fixture tests for metric parsing/reporting | P2 | Plan 229 Step 8 | Pending |
| Multiple seeds + variance reporting | P2 | Plan 229 Step 7 | Pending |

## 7. Residual Risk

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Provider data retention may expose repo content | Medium | Medium | Accept only for explicit opt-in live runs; document provider trust boundary |
| Container isolation is not a perfect sandbox | Low-Medium | High | Further mitigate with minimal mounts and no host execution mode |
| Cost estimates may be incomplete for unknown models | Medium | Medium | Fail closed or mark cost unknown unless user explicitly accepts |
| Results can be over-generalized | High | Low-Medium | Report task set, variance, and limitations prominently |

## 8. Review Schedule

| Review Type | Frequency | Next Review |
|-------------|-----------|-------------|
| Threat Model Update | Before Plan 229 Ready and before each release changing live execution | Before implementation approval |
| Control Verification | Before live smoke and release | Before Plan 229 completion |

## 9. References

- `docs/ai/plans/229-agentscaffold-live-benchmarking-framework.md`
- `docs/ai/spikes/SPIKE-2026-06-15-agentscaffold-live-benchmark-harness.md`
- `packages/gitnexus/eval/README.md`
