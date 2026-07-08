# Plan Review Checklist

This checklist MUST be completed before executing any plan. It ensures cohesion with the overall architecture and validates integration points with dependent plans.

## Usage

1. Copy this checklist into the plan file as a pre-execution section
2. Complete ALL items before starting execution
3. If any item fails, document resolution or escalate as blocker

---

## I. Pre-Implementation Verification

| Check | Status | Notes |
|-------|--------|-------|
| [ ] Searched codebase for existing implementations of similar functionality | | |
| [ ] **Verified code does NOT already exist** for files in File Impact Map | | |
| [ ] **Checked workflow_state.md** for COMPLETE markers on this or related plans | | |
| [ ] **Verified plan is not SUPERSEDED** by checking metadata and related plans | | |
| [ ] Reviewed existing exception handling in affected code paths | | |
| [ ] External API documentation reviewed for quirks/limitations | | |
| [ ] Test dependencies identified and added to dev requirements | | |
| [ ] **Learnings Review**: Checked learnings tracker for pending items relevant to this plan's domain | | |
| [ ] **Enums/types**: If adding new enums/types, verify names against actual code | | |
| [ ] **Config files**: If adding/modifying config, verify param names match schema field names exactly | | |
| [ ] **Config safety**: If adding config-driven safety features, verify validation prevents dangerous misconfigurations | | |

---

## A. Architectural Alignment

## B. Dependency Readiness

| Dependency | Interface Contract Verified | Status | Notes |
|------------|---------------------------|--------|-------|
| Plan XXX | [ ] Types/schemas match | [ ] Ready | |
| Plan YYY | [ ] APIs compatible | [ ] Ready | |

**Dependency Verification Steps:**
1. For each dependency, read its plan's appendix (code examples)
2. Verify interface signatures match what this plan expects to consume
3. If dependency plan has TBD interfaces, create interface contract in `docs/ai/contracts/`
4. Document any gaps in Notes column

## C. Interface Contracts (What This Plan Exports)

| Export | Type | Consumers | Contract Location |
|--------|------|-----------|-------------------|
| `ClassName` | Class | Plans X, Y | `docs/ai/contracts/xxx.md` |
| `function_name` | Function | Plans Z | `docs/ai/contracts/yyy.md` |

## D. Data Contract Compliance

| Schema | Location | Version | Used By This Plan |
|--------|----------|---------|-------------------|
| TBD | TBD | v1 | [ ] Import only, no modifications |

**Rules:**
- NEVER modify existing data contracts without a breaking change plan
- New contracts require ADR if they affect multiple plans
- Reference specific schema versions in plan

## E. Cross-Cutting Concerns

| Concern | Standard Doc Reference | Implementation Approach |
|---------|----------------------|------------------------|
|  | `` | |
|  | `` | |

## F. Integration Points

| Integration Point | Protocol | Test Strategy | Mock Available |
|-------------------|----------|---------------|----------------|
| Module A -> This | Direct import | Unit test with fixture | [ ] Yes |
| This -> Module B | API call | Integration test | [ ] Yes |
| External Service | REST/gRPC | Mock in tests | [ ] Create mock |

## G. Best Practices Verification

| Practice | Status | Notes |
|----------|--------|-------|
| [ ] No hardcoded secrets/credentials | | |
| [ ] Configuration loaded from env/config files | | |
| [ ] All public functions have docstrings | | |
| [ ] Type hints on all function signatures | | |
| [ ] Exceptions are specific (not bare except) | | |
| [ ] Resources properly closed (context managers) | | |
| [ ] No circular imports in module design | | |
| [ ] Test coverage target specified and achievable | | |

---

## H. Gap Analysis

### Identified Gaps
<!-- List any gaps found during review -->
1. 

### Enhancement Opportunities
<!-- Best practices or improvements beyond minimum requirements -->
1. 

### Blockers Requiring Resolution
<!-- Issues that must be resolved before execution -->
1. 

---

## Review Sign-Off

| Reviewer | Date | Decision |
|----------|------|----------|
| Self-review | | [ ] Proceed / [ ] Block |
| Peer review (if required) | | [ ] Proceed / [ ] Block |

**Proceed only if all blocking items are resolved.**
