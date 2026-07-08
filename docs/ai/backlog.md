# Backlog -- agentscaffold

**Last Updated**: 2026-07-08

This file tracks active, pending, and future work only. Completed items are archived in backlog_archive.md.

When you decide to implement something, create a proper plan file using the appropriate template. When a backlog item is completed, move it to the archive.

---

## Active Items

| ID | Title | Priority | Effort | Status | Source |
|----|-------|----------|--------|--------|--------|
| B-149-1 | README reframe: governance/memory lead, efficiency downstream, three-claim table, when-to-use section | P2 | Small (2h) | Open | Plan 149 retrospective. Structural content can be written; fill measured numbers from next live eval run. |
| B-149-2 | Concurrent write hardening: add concurrent `record_finding()` test; investigate WAL contention with async freshness coordinator (Plan 148) | P2 | Small (2-3h) | Open | Plan 149 retrospective. Solo latency <200ms confirmed; concurrent-write test not yet implemented. |
| B-149-3 | `query_compat.ql()` dual-dialect maintenance burden -- document path to deprecate KuzuDB and collapse to DuckPGQ-only | P4 | Medium (plan) | Deferred | Plan 149 retrospective. Premature until KuzuDB formally deprecated via ADR update. |
| B-149-4 | Design AgentScaffold lineage-mapping skill backed by the knowledge graph | P2 | Medium (plan) | Open | Side-topic request 2026-04-28. Design a skill/tool path that maps implementation intent, code artifacts, plans, studies, ADRs, and backlog lineage via the graph instead of ad hoc text search. |
| B-149-5 | AgentScaffold multi-project / multi-user / durable-storage design study + phased plans (Phase 2) | P2 | Medium (study + plans) | In Progress | Design discussion 2026-06-14. Study `docs/studies/STU-2026-06-14-agentscaffold-multiproject-collab-durability.md`. Phase 1 (Plans 221-223) COMPLETE; Phase 2 (Plans 224-229, 231, 232) largely COMPLETE and released; Plan 234 (shared workspace asset layout) remains the open Phase 2 item. |
