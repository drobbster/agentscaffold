# Architectural Design Changelog -- agentscaffold

**Baseline**: system_architecture.md

This changelog captures all architectural evolution without modifying the baseline document. Agents may APPEND entries here. Only humans may approve amendments that get merged into the baseline (triggering a version bump).

---

## Versioning Rules

| Change Type | Version Bump |
|-------------|--------------|
| Additive change (new component, clarification) | Minor (v1.x) |
| Breaking change (layer structure, removal) | Major (v2.0) |

---

## Current Version

v1.0

---

## Pending Amendments

Proposals that require human review before merging into the baseline.

<!-- Add amendment proposals here -->

(empty)

---

## Version History

| Version | Date | Summary |
|---------|------|---------|
| v1.0 | 2026-07-08 | Initial architecture |

---

## Log

Append-only record of architectural observations during plan execution.

Entries dated before 2026-07-08 were migrated from the `rebellion-trading-system`
monorepo when AgentScaffold was extracted into this standalone repository.

| Date | Plan/Study | Layer(s) | Entry | Type |
|------|-----------|----------|-------|------|
| 2026-06-16 | Plan 232 / SPIKE-2026-06-16-agentscaffold-resident-embedding-lane | Cross-cutting | AgentScaffold async embedding lane approved for implementation. `graph.async_embeddings` defaults to `off`; non-`off` policies schedule a background single-flight embedding worker; the MCP process keeps the model resident only after opted-in scheduling; commit-boundary hooks can request a non-blocking embedding reconcile. | architecture_change |
| 2026-07-08 | v1.0 baseline | All | Initial standalone-repo architecture baseline | baseline |
