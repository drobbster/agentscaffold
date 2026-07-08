# Collaboration Protocol

This document defines a structured approach for human-AI collaboration.

---

## Session Types

| Type | Trigger | Process | Outputs |
|------|---------|---------|---------|
| Plan Creation | New feature/refactor/bugfix needs design | Draft a complete plan with scope, tests, validation, rollback | Plan file, dependencies, file impact map |
| Plan Review | Plan file created with all sections | Devil's advocate review, expansion review, dependency verification | Updated plan, identified gaps |
| Spike Session | High uncertainty or unvalidated assumptions | Time-boxed prototype (2-4 hrs); document findings | Spike findings, proceed/pivot/defer decision |
| Execution Session | Plan approved and ready | Implement steps in order; run validation; update checklist | Code, tests, updated plan |
| Retrospective | Plan execution complete | What worked, what was harder, discoveries, follow-ups | Retrospective notes, learnings, backlog items |
| Integration Review | Multiple plans or interfaces connect | Verify contracts, schemas, and data flow across boundaries | Contract updates, integration tests |

---

## Plan Lifecycle

```
Draft -> Review -> Ready -> In Progress -> Complete
```

### Gate: Draft -> Review

- [ ] Plan lint passes (`scaffold plan lint -p <PLAN_NUMBER>`)
- [ ] All required sections are present
- [ ] Dependencies are identified
- [ ] Architecture layer(s) and boundaries are declared

### Gate: Review -> Ready

- [ ] Devil's advocate review completed
- [ ] Expansion/gap review completed
- [ ] High-uncertainty assumptions spiked or resolved
- [ ] Interface contracts created or updated for exported APIs
- [ ] No blocking gaps remain

### Gate: Ready -> In Progress

- [ ] Plan review checklist completed
- [ ] Dependencies verified as complete/ready
- [ ] Approval obtained if the plan requires approval
- [ ] No blockers in `docs/ai/state/workflow_state.md`

### Gate: In Progress -> Complete

- [ ] Execution steps checked off
- [ ] Validation commands pass
- [ ] Tests pass
- [ ] Retrospective completed
- [ ] `workflow_state.md` updated

---

## Prompting Patterns

Use these as copy-paste starting points.

### Scoped Exploration

```
Before we work on [AREA], give me an overview of:
1. Current state of [AREA] in the codebase
2. How [AREA] relates to [RELATED_PLANS]
3. Key decisions already made
4. Open questions
```

### Devil's Advocate

```
Do a devil's advocate review of Plan [XXX].
What are the riskiest assumptions?
What could cause silent failures?
What alternatives exist?
```

### Gap Analysis

```
Read Plan [XXX] and identify:
- 5 edge cases the test plan does not cover
- 3 integration points that need more specification
- Any security or dependency concerns
```

### Alternative Design

```
Propose two alternative approaches to [SPECIFIC_COMPONENT].
Compare tradeoffs: complexity, performance, maintainability, testability.
```

### Stress Testing

```
How does [COMPONENT/PLAN] scale to [SCALE_FACTOR]?
What breaks first?
What would need to change?
```

### Dependency Verification

```
Verify that Plan [XXX]'s [INTERFACE] is compatible with what Plan [YYY] expects.
Check: method signatures, data schemas, error handling.
```

### Progressive Refinement

```
Let's refine Plan [XXX]'s [SECTION].
Read the current state and propose specific enhancements.
```

### Integration Focus

```
Walk through how [PLAN_A] and [PLAN_B] integrate.
What data flows between them?
What are the failure modes at the boundary?
```

---

## Driving Development

### Before Each Phase

1. Review `docs/ai/state/learnings_tracker.md` for pending learnings.
2. Incorporate relevant learnings before starting new work.
3. List plans in the phase and verify execution order.
4. Run `scaffold plan lint` / `scaffold plan lint -p <PLAN_NUMBER>` as applicable.
5. Verify interface contracts exist for cross-plan dependencies.

### Before Each Plan

1. Read the plan completely.
2. Verify dependencies and contracts.
3. Complete devil's advocate and expansion reviews.
4. Spike high-uncertainty assumptions.
5. Complete the plan review checklist.
6. Obtain approval if required.

### During Execution

1. Follow execution steps in order.
2. Check off steps as completed.
3. Document deviations with rationale.
4. Update the plan if scope changes.
5. Pause and escalate if blockers emerge.

### After Each Plan

1. Complete the retrospective.
2. Add significant learnings to `docs/ai/state/learnings_tracker.md`.
3. Update `workflow_state.md`.
4. Create actionable backlog items for near-term discovered work.
5. Update interface contracts if APIs changed.
6. Verify dependent plans still hold.

---

## Future Regret Evaluation

During devil's advocate review, classify each "future regret" item by effort and
choose an action:

| Future Regret Item | Effort | Action |
|--------------------|--------|--------|
| Small | < 1 hour | Include in the current plan execution steps |
| Medium | 1-4 hours | Add an explicit backlog item |
| Large | > 4 hours | Create a plan stub |

Discuss these during pre-implementation review and document the decision in the
plan checklist or appendix.

---

## Escalation Triggers

Pause and discuss with a human when:

| Trigger | Action |
|---------|--------|
| Spike reveals a fundamental approach issue | Review findings, decide pivot/proceed |
| Integration verification fails | Identify root cause, update contracts |
| Devil's advocate identifies critical unmitigated risk | Risk assessment, mitigation plan |
| Estimated effort exceeds plan by >50% | Scope review, re-estimation |
| External dependency unavailable or changed | Impact assessment, workaround |
| Security concern identified | Security review and approval gate |
| Breaking change to interface contract | ADR or explicit migration path |
| Test coverage target unreachable | Scope review, target adjustment |
| Plan bypasses declared architecture boundaries | Fix plan data flow before implementation |

---

## Quality Checkpoints

### Code Quality

- [ ] Formatter passes
- [ ] Linter passes
- [ ] Type checks pass, if enabled
- [ ] Tests pass
- [ ] Coverage target met, if applicable

### Plan Quality

- [ ] Plan lint passes
- [ ] Review checklist complete
- [ ] Interface contracts updated
- [ ] Tests included in the plan

### Integration Quality

- [ ] Cross-plan integration verified
- [ ] Interface contracts consistent
- [ ] No circular dependencies
- [ ] Data schemas compatible

---

## Communication Patterns

### Status Updates

When providing status, include what completed, what is in progress, any blockers
or concerns, and the next step.

### Asking for Clarification

When requirements are unclear, state your current understanding, ask specific
questions, and propose a default if no answer is given.

### Proposing Changes

When suggesting deviations from the plan, state the deviation, explain why it is
needed, describe impact on the plan, and request approval if significant.

---

## Review Terminology (Human-Readable)

The governed lifecycle is driven by MCP tools (for example `scaffold_begin_plan`,
`scaffold_complete_plan`, `scaffold_prepare_retro`). Those tool names are an
implementation detail of how the work is invoked -- they are NOT the words to
use when writing human-facing artifacts.

In plans, plan appendices, study notes, the architecture changelog,
`workflow_state.md`, commit messages, and PR descriptions, describe the activity
in plain review language:

| Use this human-readable phrasing | Not the raw tool name |
|----------------------------------|------------------------|
| Pre-implementation review (devil's advocate + expansion + gap analysis) | `scaffold_begin_plan` |
| Post-implementation review / retrospective | `scaffold_complete_plan`, `scaffold_prepare_retro` |
| Plan review / critique | `scaffold_prepare_review` |
| Orientation / status check | `scaffold_orient` |

A raw tool name may appear only as light provenance inside a parenthetical (for
example "pre-implementation review (begin-plan chain), 2026-06-17"), never as the
primary description of what happened. Checklist entries, headings, and summaries
must read naturally to a human who does not know the tool surface.

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It Is Bad | Instead |
|--------------|---------------|---------|
| Skipping review gates | Bugs, rework, integration issues | Complete all gates |
| Executing without approval | Risk exposure, trust erosion | Wait for explicit approval |
| Modifying plan silently | Tracking lost, scope creep | Document all deviations |
| Ignoring spike findings | Wasted effort, wrong approach | Act on findings |
| Skipping retrospective | No learning, repeated mistakes | Always reflect |
| Over-engineering | Delayed delivery, complexity | Minimum viable scope |
| Under-documenting | Knowledge loss, onboarding issues | Document as you go |
| Leaking raw MCP tool names into human-facing artifacts | Plans and summaries read like tool logs, not review history | Use human-readable review terminology |

---

## Prompt Templates

Reference prompt templates for each session type:

- Plan critique: `docs/ai/prompts/plan_critique.md`
- Plan expansion: `docs/ai/prompts/plan_expansion.md`
- Retrospective: `docs/ai/prompts/retrospective.md`
