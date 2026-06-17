# AgentScaffold Benchmark

AgentScaffold Benchmark is an opt-in live evaluation surface for comparing a
baseline plain-tools agent arm against an AgentScaffold-equipped arm. Live runs
can spend model-provider credits, so the first implemented commands are
preflight and dry-run only.

## Install

The base package does not install live benchmark dependencies. Install the
optional extra when you are ready to run live benchmarks:

```bash
pip install "agentscaffold[benchmark]"
```

This installs the runner libraries (`mini-swe-agent`, `litellm`, `datasets`) but
does not itself create model-provider charges. Cost only occurs when a live
benchmark starts model API calls.

## Commands

```bash
scaffold benchmark models
scaffold benchmark doctor
scaffold benchmark doctor --live --model claude-haiku
scaffold benchmark run --dry-run --model claude-haiku --task-slice 0:1
scaffold benchmark compare path/to/summary.json
scaffold benchmark report path/to/results-dir
```

Live execution is intentionally gated. A live run requires an API key, Docker,
optional benchmark dependencies, a positive cost cap, and explicit live
confirmation. Without those, the command fails before starting model calls:

```bash
scaffold benchmark run \
  --model claude-haiku \
  --task-slice 0:1 \
  --max-cost-usd 1.00 \
  --confirm-live
```

The live runner creates isolated task workspaces, runs baseline/equipped arms
through the guarded mini-swe-agent Docker adapter, installs container-local
`scaffold-*` wrappers for the equipped arm, runs task validation commands when
defined, extracts trajectory metrics, and writes `summary.json`.

## Manual Live Smoke

Live smoke is manual and opt-in only. Do not run it in CI.

```bash
cd packages/agentscaffold
pip install -e ".[benchmark]"
export OPENROUTER_API_KEY=...
scaffold benchmark doctor --live --model claude-haiku
scaffold benchmark run \
  --model claude-haiku \
  --task-slice 0:1 \
  --max-cost-usd 1.00 \
  --confirm-live \
  --output .scaffold/benchmark/results/smoke
scaffold benchmark report .scaffold/benchmark/results/smoke
```

The smoke should produce a `summary.json` with one task, both arms, real API
call/cost metrics when provider pricing is available, and a markdown report. If
pricing is unavailable, do not use the run for cost-savings claims.

## Cost And Pricing

Cost is read from the live model runner, not estimated from static proxy data.
The first implementation follows the `mini-swe-agent` + `litellm` pattern:

- `agent.cost` / trajectory `model_stats.instance_cost` for LLM API cost
- `agent.n_calls` / trajectory `model_stats.api_calls` for request count
- token fields when the model runner exposes them

Pricing source is recorded per model. Built-in configs currently use `litellm`
provider pricing. Cursor subscription pricing is not treated as equivalent to
provider API pricing; it would require a separate explicit pricing adapter or
usage import.

## Saved Results

`compare` and `report` read a benchmark `summary.json` file, or a result
directory containing one. The live runner will write this schema as it executes
paired arms:

```json
{
  "run_id": "run-1",
  "model": "claude-haiku",
  "model_id": "openrouter/anthropic/claude-3.5-haiku",
  "pricing_source": "litellm",
  "results": [
    {
      "task_id": "sample-router-tests",
      "arm": "equipped",
      "seed": 1,
      "passed": true,
      "defect_caught": null,
      "metrics": {
        "cost_usd": 0.15,
        "api_calls": 3,
        "wall_time_seconds": 8.0,
        "scaffold_tool_calls": 2,
        "pricing_source": "litellm"
      }
    }
  ]
}
```

Reports aggregate pass rate, planted-defect caught rate, total/average cost,
API calls, wall-clock time, and AgentScaffold tool calls by arm.

## Safety

- `doctor` reports missing Docker, optional dependencies, API keys, and pricing
  support without printing secrets.
- `run --dry-run` prints the planned model, arms, task slice, seeds, worker
  count, and cost cap without starting containers or model calls.
- Live execution is excluded from CI and requires explicit cost/task/worker
  bounds.
- Live tasks must run in isolated containers, never directly on the host.
