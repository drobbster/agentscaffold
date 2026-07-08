# Spike: AgentScaffold path/root unification

### Metadata

| Field | Value |
|-------|-------|
| Parent Plan | Phase 1, Thread 1 of STU-2026-06-14-agentscaffold-multiproject-collab-durability (backlog B-149-5) |
| Time-box | 2-4 hours |
| Created | 2026-06-14 |
| Author | daverobb (AI-assisted) |
| Status | Complete |

### Goal

**One-sentence goal:**
> Validate that path/root resolution in AgentScaffold can be unified behind a
> single resolved-paths accessor with one project-root rule, by cataloguing
> every hardcoded path and root usage and prototyping the accessor, to determine
> whether a backward-compatible refactor is feasible for existing
> single-project repos.

### Questions to Answer

| # | Question | Success Criteria |
|---|----------|------------------|
| 1 | How many and where are the hardcoded `docs/ai/*` path callsites that bypass `GraphConfig`? | Complete file/line catalog |
| 2 | How many places use `Path.cwd()` (or an ad-hoc root) instead of one project-root rule? | Count + risk assessment |
| 3 | Can a single resolved-paths accessor stay backward-compatible for existing single-project repos? | Yes/No with a concrete default rule |

### Constraints

- Time-box: do not exceed 4 hours.
- Scope: only the three questions; no production refactor in the spike.
- Output: clear findings + a go/no-go decision for the Phase 1 plan.

### Approach

**Steps:**
1. [x] Grep the package `src/` for hardcoded `docs/ai`, `docs/studies`, `docs/security`, `docs/runbook` literals.
2. [x] Grep for `Path.cwd()` and `find_config()` usages to map root resolution.
3. [x] Compare against `GraphConfig` path fields to identify divergence.
4. [x] Sketch the resolved-paths accessor and a backward-compatible root rule.

### Findings

#### Question 1: Hardcoded `docs/ai/*` callsites that bypass `GraphConfig`

**Finding:** There are two path systems. `GraphConfig` (config.py:215-221) exposes
`plans_dir`, `contracts_dir`, `learnings_file`, `studies_dir`, `adrs_dir`,
`spikes_dir`, `workflow_state_file`. The graph/MCP layer honors them
(`graph/governance.py`, `validate/governance.py` with fallbacks, MCP
`_parse_workflow_state`). But a cluster of CLI commands hardcode the paths and
ignore the config:

| File:line | Hardcoded literal | Should use |
|-----------|-------------------|------------|
| `plan/create.py:51` | `Path("docs/ai/plans")` | `graph.plans_dir` |
| `plan/lint.py:70` | `Path("docs/ai/plans")` | `graph.plans_dir` |
| `plan/status.py:43` | `Path("docs/ai/plans")` | `graph.plans_dir` |
| `retro/check.py:40-41` | `docs/ai/plans`, `docs/ai/state/learnings_tracker.md` | `graph.plans_dir`, `graph.learnings_file` |
| `metrics/dashboard.py:57` | `Path("docs/ai/plans")` | `graph.plans_dir` |
| `validate/orchestrator.py:51` | `Path("docs/ai/plans")` | `graph.plans_dir` |
| `spike/create.py:25` | `Path("docs/ai/spikes")` | `graph.spikes_dir` |
| `study/create.py:26` | `Path("docs/studies")` | `graph.studies_dir` |
| `study/list_cmd.py:27` | `Path("docs/studies")` | `graph.studies_dir` |
| `study/lint.py:59` | `Path("docs/studies")` | `graph.studies_dir` |
| `domain_packs/loader.py:46-48` | `docs/ai/prompts`, `docs/ai/standards`, `docs/security` | new path fields |

Additionally, `init_cmd.py` template-output map and several generated docs (MCP
completion checklist strings at server.py:2517-2519, reviewer hints at 1636,
`agents/rule_policy.py:70`) embed literal paths. `GraphConfig` also lacks fields
for: backlog, backlog_archive, standards_dir, prompts_dir, templates_dir,
plan_completion_log, security_dir.

**Evidence:** grep of `src` for `docs/ai|docs/studies|docs/security|docs/runbook`.
**Confidence:** High. Roughly 11 CLI callsites + the init map + generated-string literals.

#### Question 2: `Path.cwd()` / ad-hoc root usages

**Finding:** `Path.cwd()` appears ~38 times across ~18 modules (cli.py x7,
agents/cursor.py x4, agents/claude.py x3, agents/windsurf.py x3,
agents/prompt.py x3, config.py x3 incl. `find_config` default,
agents/generate.py x2, mcp/server.py x2, plus singletons in graph/__init__.py,
validate/*, ci/setup.py, taskrunner/setup.py, hooks/engine.py,
domain_packs/*). The walk-up `find_config()` (the correct root rule) is used in
relatively few places; most code assumes cwd == project root. The known
divergence bug is `open_graph()`/`_resolve_db_path` (graph/__init__.py) resolving
`db_path` relative to cwd while `run_pipeline()` resolves it relative to the
index root.

**Evidence:** grep count of `Path.cwd()|find_config(`.
**Confidence:** High for the count; Medium on per-callsite intent (some `cwd`
uses are legitimately "operate on the current directory" rather than "find the
project root"). The refactor must classify each: project-root-relative vs
genuinely-cwd-relative.

#### Question 3: Backward-compatible accessor feasible?

**Finding:** Yes. A single accessor can default to today's behavior. Proposed
shape: a `ResolvedPaths` object built once from `(config, root)` where:

```python
def resolve_root(start: Path | None = None) -> Path:
    cfg = find_config(start)            # nearest scaffold.yaml
    if cfg is not None:
        return cfg.parent
    # fallback: nearest .git, else cwd (preserves today's behavior)
    return _git_root(start) or (start or Path.cwd())

class ResolvedPaths:
    # all derived from GraphConfig defaults, joined to root
    plans_dir, contracts_dir, learnings_file, studies_dir, adrs_dir,
    spikes_dir, workflow_state_file, backlog_file, standards_dir, ...
```

Because `GraphConfig` already carries the same default strings the CLI currently
hardcodes (`docs/ai/plans/`, etc.), routing the hardcoded callsites through the
accessor is behavior-preserving for any repo that has not customized them. The
only behavior change is the intended one: customized `graph.*` paths finally
take effect in the CLI, and `open_graph` joins to the project root instead of
cwd. New `GraphConfig` fields (backlog, standards_dir, prompts_dir, etc.) keep
the existing literals as defaults, so fresh and existing repos are unaffected.

**Evidence:** `GraphConfig` defaults (config.py:215-221) already equal the
hardcoded CLI literals; `validate/governance.py` already demonstrates the
gc-with-fallback pattern.
**Confidence:** High.

### Unexpected Discoveries

| Discovery | Impact on Parent Plan |
|-----------|----------------------|
| `GraphConfig` is missing fields the CLI/init already use as literals (backlog, standards, prompts, templates, plan_completion_log, security) | Phase 1 plan must add these fields (additive, default to current literals) before routing callsites |
| Some `Path.cwd()` uses are genuinely cwd-relative, not root-relative | Refactor must classify each callsite; not a blind find/replace |
| Generated artifacts (MCP strings, agents rule docs, init map) embed literal paths | Either keep literals (doc text) or template them from config; decide per-callsite in the plan |

### Blockers Discovered

| Blocker | Severity | Resolution Path |
|---------|----------|-----------------|
| None critical | Minor | The `open_graph` vs `run_pipeline` db_path divergence is a real bug but bounded; fix within the Phase 1 plan |

### Decision

Based on spike findings:

- [x] **Proceed (modify plan)** - The unification is feasible and
  backward-compatible. Derive a Phase 1 refactor-template plan with the
  catalog above as its File Impact Map. Approval Required: Yes (breaking-change
  surface: path resolution + new config fields).

### Plan Modifications Required

| Section | Change Required |
|---------|-----------------|
| File Impact Map | Use the Question 1 callsite table + the ~18 `Path.cwd()` modules from Question 2 |
| Execution Steps | (1) add missing `GraphConfig` path fields (additive, defaults = current literals); (2) add `resolve_root()` + `ResolvedPaths` accessor; (3) route hardcoded CLI callsites through it; (4) fix `open_graph` to join db_path to root; (5) classify and migrate `Path.cwd()` callsites; (6) backward-compat tests for an uncustomized repo |
| Risks | Breaking change to path resolution; mitigate with defaults == current literals + regression tests run from a subdir and from repo root |

### Time Tracking

| Activity | Planned | Actual |
|----------|---------|--------|
| Setup | 0.25h | 0.1h |
| Exploration | 2h | ~0.75h |
| Documentation | 0.75h | ~0.5h |
| **Total** | ~3h | ~1.35h |

---

## Spike Cleanup

- [x] No prototype code committed (analysis-only spike)
- [x] Findings recorded here; parent study to reference this spike
- [x] No new workflow_state blockers (none critical)
- [x] Discovered work folded into the Phase 1 plan scope (no separate backlog items needed)
