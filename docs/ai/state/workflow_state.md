# Workflow State -- agentscaffold

**Last Updated**: 2026-07-08

Tracks blockers and next steps only. Plan status lives in plan files. History lives in git.

> Migration note (2026-07-08): AgentScaffold governance (plans, spikes, studies,
> ADR-023, interface contracts, the live-benchmark threat model, and the
> multi-project design study) was extracted from the `rebellion-trading-system`
> monorepo into this standalone repository. Plan numbers retain their original
> monorepo IDs so historical references stay searchable. The trading system now
> consumes AgentScaffold as a pinned PyPI dependency.

## Blockers

None

## Current Implementation

| Plan | Title | Status | Branch |
|------|-------|--------|--------|
| 234 | Shared workspace asset layout + MCP cwd fix | Draft (approval pending; execution steps unchecked) | - |
| 229 | Live two-arm benchmarking framework | In Progress (offline complete; opt-in live smoke pending) | - |

## Recently Released

- **0.9.0 (2026-06-23)**: multi-project workspace hardening -- MCP `working_path`
  dynamic project scoping, retrieval-status pinning, project-scoped findings and
  backlog, and `.mdc` Cursor rule delivery. Plans 233-adjacent tooling fixes.
- **0.8.0 (2026-06-16)**: Plan 231 (incremental indexer scoping + hook debounce)
  and Plan 232 (async embedding lane and resident embedder).
- **0.7.0 (2026-06-16)**: Phase 1 foundation chain (Plans 221-223) plus Phase 2
  (Plans 224-229): namespaced multi-project workspace, config inheritance,
  collaboration ergonomics, semantic search quality, eval coverage, and the
  benchmark CLI foundation.
- **0.6.0 (2026-06-14)**: Trust and Safety hardening batch (Plans 217-220).

Earlier completed AgentScaffold plans (pre-0.6.0): 148, 149, 151, 152, and
212-216.

## Next Steps

- Plan 234: run the pre-review chain and obtain approval before implementation.
- Plan 229: run the opt-in live smoke (requires `agentscaffold[benchmark]`
  dependencies, a model API key, and a cost budget), then close out.
- Release: cut the next AgentScaffold version once 234/229 settle.
