# Agent Operating Rules

## Repository Relationship
This repository is the private governance and development-control repo for the
public `drobbster/agentscaffold` codebase. It intentionally retains the
AgentScaffold planning and governance artifacts -- plans, spikes, studies, ADRs,
contracts, threat models, backlog, workflow state, rules, and standards -- so
those files remain separate from the shippable package repository.

When work requires code verification or implementation, use the sibling
`../agentscaffold` checkout for source, tests, packaging, and
release artifacts. Keep governance changes in this repo and code changes in the
`agentscaffold` repo unless a human explicitly requests otherwise.

## Source of Truth
- Configuration: `scaffold.yaml`
- Plan template (feature): docs/ai/templates/plan_template.md
- Plan template (bugfix): docs/ai/templates/plan_template_bugfix.md
- Plan template (refactor): docs/ai/templates/plan_template_refactor.md
- Plan review checklist: docs/ai/templates/plan_review_checklist.md
- Spike template: docs/ai/templates/spike_template.md
- Study template: docs/ai/templates/study_template.md
- ADR template: docs/ai/adrs/adr_template.md
- Studies directory: docs/studies/
- Plans directory: docs/ai/plans/
- Interface contracts: docs/ai/contracts/
- Implementation standards: docs/ai/standards/
- Backlog (active): docs/ai/backlog.md
- Backlog (archive): docs/ai/backlog_archive.md
- Workflow state: docs/ai/state/workflow_state.md
- Commands reference: docs/ai/commands.md
- **System architecture (6-layer)**: docs/ai/system_architecture.md **(READ-ONLY for agents)**
- **Architecture changelog**: docs/ai/architectural_design_changelog.md **(append-only for agents)**
- Collaboration protocol: docs/ai/collaboration_protocol.md
- Prompt templates: docs/ai/prompts/
- **Runbook**: docs/runbook/ (operational documentation)
- **Security**: docs/security/ (threat models, security documentation)

## AgentScaffold MCP Tools
Prefer AgentScaffold MCP tools first when a request matches a known intent
(orientation/status, plan review, decision lineage, symbol context/impact,
mid-implementation progress, recording findings/backlog). If a tool errors, is
stale, or lacks the specific detail, fall back to direct reads/search and state
one short reason.

Prefer call-compressed responses: use `recommended_actions` / `plan_progress`
from `scaffold_orient`, and inline `why_empty` / `grep_fallback` on empty
search/impact/context, before making redundant follow-up tool calls. The full
intent-to-tool map and call-compression rules are generated into platform agent
files (`.cursor/rules/agentscaffold.mdc`, `CLAUDE.md`, `.windsurfrules`, etc.)
via `scaffold agents generate-all`.

## Planning Rules (Mandatory)
- Any architectural or refactor work MUST begin with a plan file.
- Plans MUST use docs/ai/templates/plan_template.md exactly.
- No sections may be omitted. Use `TBD` if necessary.
- Plans must include:
  - File Impact Map
  - Tests section with test file paths
  - Execution Steps with checkboxes
  - Validation commands
  - Rollback Plan

## Architectural Research Gate (Mandatory)

Before creating or materially revising a plan that changes topology, public
contracts, persistence, security boundaries, or cross-repo resolution, search
the web (and local ADRs/studies) for how similar systems solve the problem.
Record the alternatives, source links, and pros/cons versus the design you
were already considering. You may keep your original design; you must not
skip the cross-check.

This gate does **not** apply to single-function bugfixes, typo/docs-only
edits, or plans that only restate an already-accepted ADR. If the web is
unreachable, say so and use local ADRs/studies only.

Generated copy shipped with Plan 272 (`rule_policy.py` +
`scaffold agents generate-all`). This project-owned copy remains the
full procedure.

## Plan Status Verification (Mandatory)
Before recommending or executing ANY plan, verify:

1. **Execution Steps**: Are all steps unchecked (needs work) or checked (done)?
2. **Code Existence**: Do the source directories contain the files listed in File Impact Map?
3. **workflow_state.md**: Is this plan listed as COMPLETE?
4. **Supersession**: Has this work been done by a different plan?
5. **Staleness**: Is the plan more than 2 weeks old since last update? (See Stale Plan Review below)

**Verification Rules:**
- If execution steps are checked but code doesn't exist, escalate as inconsistency.
- If workflow_state.md says COMPLETE but steps are unchecked, trust workflow_state.md.
- If multiple plans cover similar scope, do explicit gap analysis before recommendations.
- "Ready" status in system_architecture.md means "plan file exists" NOT "plan needs implementation."

**Code Existence Spot-Check (Mandatory):**
Do not trust checked execution steps alone. For each file in File Impact Map, verify
the file exists AND contains the expected exports:
- Run `python -c "from module import ClassName"` for key classes/functions
- Or grep for key function/class names: `rg "class ClassName" src/`
- If a plan claims to add N functions to a file, verify at least the function names exist

This catches the failure mode where a plan is marked COMPLETE but implementation steps
were skipped.

**Supersession Analysis (required when plans overlap):**
When multiple plans cover similar domains:
1. Check if any plan is marked SUPERSEDED in its metadata
2. Search workflow_state.md for COMPLETE markers on related plans
3. Verify actual code exists for claimed implementations
4. If overlap found, document which plan takes precedence before proceeding

**Stale Plan Review (required when plan is older than 2 weeks):**
Plans written more than 2 weeks ago may reference outdated interfaces, missing modules, or superseded architectural patterns. Before executing a stale plan:
1. Check the plan's `Created` and `Last Updated` dates in its metadata
2. List all plans completed AFTER the stale plan was last updated (search workflow_state.md)
3. For each completed plan, check if it modified any files or interfaces referenced by the stale plan
4. Verify the stale plan's dependencies still match actual code (imports, function signatures, data contracts)
5. If conflicts found, update the stale plan's File Impact Map, execution steps, and interface references before proceeding
6. Document what changed and why in the plan file before starting execution

**Common staleness indicators:**
- Plan references enums, dataclasses, or function signatures that have since been renamed or restructured
- Plan's File Impact Map lists files that have been moved, split, or deleted
- New architectural layers were added after the plan was written
- Interface contracts referenced by the plan have been bumped to a new major version

## Plan Lifecycle
Plans progress through defined states with gates:

```
Draft -> Review -> Ready -> In Progress -> Complete
```

### Gate: Draft -> Review

**Requirements:**
- Plan lint passes
- All required sections present
- Dependencies identified
- Architecture Layer(s) declared in plan metadata (see system_architecture.md)
- Layer alignment verified: plan consumes upstream layer outputs, does not bypass layers
### Gate: Review -> Ready

**Requirements:**
- Devil's advocate review completed (docs/ai/prompts/plan_critique.md)
- Expansion review completed (docs/ai/prompts/plan_expansion.md)
- **If Security Review: Full/Partial:** Threat model created/updated (docs/security/)
- If plan has "Uncertainty: High" in metadata: spike completed first
- Interface contracts created for exports
- No blocking gaps identified
- If plan proposes architectural changes: amendment added to architectural_design_changelog.md, human review required before proceeding
**Security Review Criteria:**

| Plan touches... | Security Review Level |
|-----------------|----------------------|
| Authentication, secrets, credentials | Full |
| External API integrations | Full |
| Data storage, new persistence | Partial |
| Internal service boundaries | Partial |
| Internal refactors, docs, UI-only | None |

Full = Create threat model using `docs/security/threat_model_template.md`
Partial = Document data flow and trust boundaries in plan's Risks section
**Escalate (do not proceed) if:**
- Spike reveals fundamental approach issue - requires human decision on pivot/proceed
- Devil's advocate identifies critical unmitigated risk - requires risk assessment
- Integration verification fails - identify root cause before proceeding

**Anti-patterns at this gate:**
- Skipping devil's advocate or expansion review to save time
- Ignoring spike findings that contradict the plan
- Proceeding with unresolved blocking gaps

### Gate: Ready -> In Progress

**Requirements:**
- Plan review checklist completed (docs/ai/templates/plan_review_checklist.md)
- Approval obtained (if Approval Required: Yes)
- Dependencies verified as complete/ready
- No blockers in workflow_state.md

### Gate: In Progress -> Complete

**Requirements:**
- All execution steps checked off
- Validation commands pass
- Tests pass with target coverage
- Lint passes
- Retrospective completed (docs/ai/prompts/retrospective.md)
- workflow_state.md updated

### Interactive Gate (Mandatory When Requested by Human)

If the human explicitly asks to "review it with me" (post-implementation review, retrospective, plan findings, etc.), the agent MUST:
- Treat this as a hard gate (do not continue implementation or apply follow-up patches)
- Surface the exact plan sections / artifacts to review
- Ask for explicit confirmation to proceed after the review
- Only resume work after the human confirms

This gate is in addition to the plan lifecycle gates above.

## Spike Requirements
For plans with high uncertainty, complete a spike before full implementation:

**When to Spike:**
- Plan has "Uncertainty: High" in metadata
- Devil's advocate review identifies unvalidated critical assumptions
- Implementation approach is unclear
- External dependency behavior is unknown

**Spike Process:**
1. Create spike using docs/ai/templates/spike_template.md
2. Time-box to 2-4 hours
3. Document findings and decision
4. Update parent plan based on findings
5. Only proceed to Ready state after spike validates approach

## Plan Cohesion Rules (Mandatory)
### Pre-Execution Review
Before executing ANY plan, complete the Plan Review Checklist (docs/ai/templates/plan_review_checklist.md):

1. **Architectural Alignment**
   - Verify plan maps to a specific layer in system_architecture.md
   - Verify file locations match system_architecture.md
   - Check module boundaries are respected (no cross-layer bypassing)
   - Confirm no duplicate functionality

2. **Dependency Verification**
   - For each dependency in the plan, verify:
     - Dependency plan exists and is complete (or TBD items documented)
     - Interface contracts match expected inputs/outputs
     - Data schemas are compatible
   - If dependency contracts don't exist, create them or escalate as blocker

3. **Interface Contract Definition**
   - Plans that export interfaces MUST create/update docs/ai/contracts/{module}.md
   - Document all public classes, functions, schemas
   - Version contracts and track consumers

4. **Standards Compliance**
   - Reference applicable standards from docs/ai/standards/
   - Document implementation approach for: errors, logging, config, testing

### Gap Analysis Process

Before starting a phase (group of related plans):

1. **Review learnings tracker** (`docs/ai/state/learnings_tracker.md`) for pending items
2. **Incorporate relevant learnings** into AGENTS.md, templates, or standards before proceeding
   - **CRITICAL**: If the new plan touches the same interfaces/modules as a recent plan with
     pending learnings, those learnings MUST be incorporated FIRST. Do not defer.
3. List all plans in the phase
4. For each plan, verify:
   - All dependencies have interface contracts defined
   - No circular dependencies
   - Data schemas are consistent across plans
   - Integration points are documented
5. Document gaps in workflow_state.md Blockers section
6. Create missing contracts or ADRs before proceeding

### Enhancement Identification

During plan review, identify and document:

1. **Best Practice Opportunities**: Patterns that could improve the plan
2. **Cross-Cutting Improvements**: Shared utilities that multiple plans could use
3. **Architectural Insights**: Better ways to structure the system

Document enhancements in plan's Gap Analysis section or create backlog items.

## Interface Contract Rules
### Creating Contracts

- When a plan exports public interfaces, create docs/ai/contracts/{module}_interface.md
- Include: class signatures, function signatures, data schemas, behavioral contracts
- Reference from plan's File Impact Map
- **Update the registry table in docs/ai/contracts/README.md** with the new contract

### Consuming Contracts

- Before implementing a dependent plan, read all dependency contracts
- Verify expected interfaces match contract definitions
- Document any mismatches in Plan Review Checklist

### Updating Contracts

- Additive changes: increment minor version (v1.1)
- Breaking changes: increment major version (v2.0), require ADR
- Update all consumer plan checklists when contracts change
- **Update version in docs/ai/contracts/README.md registry table**

## Test Requirements
- Every feature or bug fix MUST include corresponding tests.
- Tests MUST be written in the same context as the implementation, not deferred.
- Test files MUST be listed in both the File Impact Map and Tests section of plans.
- Prefer writing tests before or alongside code (test-first or test-alongside).
- No work is complete without test coverage for changed behavior.
- Execution steps should include test creation before or with implementation.- Follow patterns in docs/ai/standards/testing.md

## Smoke Test Requirements (Milestone-Based)
Smoke tests validate critical system paths work end-to-end. Unlike unit tests (required per feature), smoke tests are required at **milestone boundaries**.

### When Smoke Tests Are Required

Add/update smoke tests when completing plans that:
- Complete a major phase of work
- Add new integration boundaries
- Modify critical paths through the system

### Plan Template Addition

For plans that cross integration boundaries, add these items to the plan's Tests section:
- [ ] Smoke test added/updated in `tests/smoke/`
- [ ] `pytest -m smoke` passes

### Not Required For

- Internal module refactors (no cross-boundary changes)
- Pure unit-level changes within a single module
- Documentation-only changes
- Bug fixes within a single component

### Running Smoke Tests

```bash
pytest -m smoke -v
pytest -m smoke --tb=short
pytest -m smoke && pytest -m "not smoke"
```

## Implementation Standards
All code must follow standards defined in docs/ai/standards/:

| Standard | File | Mandatory |
|----------|------|-----------|
| Errors | errors.md | Yes |
| Logging | logging.md | Yes |
| Config | config.md | Yes |
| Testing | testing.md | Yes |

Reference applicable standards in plan review checklist.

## Breaking Changes Protocol
A breaking change is any modification to:
- Public APIs (function signatures, return types, exceptions)
- Data contracts (schemas in data_contracts/)
- Interface contracts (docs/ai/contracts/)
- Configuration schemas
- Database schemas or migrations
- External integrations

When making breaking changes:
1. Mark "Breaking change: Yes" in plan Constraints section
2. Document migration path in plan
3. Use plan_template_refactor.md for structural changes
4. Include rollback steps for data migrations
5. Consider feature flags for gradual rollout
6. Require peer review (set Approval Required: Yes)
7. Update affected interface contracts with new version

## Approval Gates
Certain changes require human approval before agent execution:

| Change Type | Approval Required |
|-------------|-------------------|
| Breaking changes | Yes |
| Security-sensitive code (auth, crypto, secrets) | Yes |
| Data migrations | Yes |
| Infrastructure changes | Yes |
| External API integrations | Yes |
| Interface contract breaking changes | Yes |
| Normal features | No |
| Bug fixes (non-critical) | No |
| Documentation only | No |

To request approval:
1. Set "Approval Required: Yes" in plan Metadata
2. List reviewers in plan Metadata
3. Do NOT execute until approval is documented
4. Record approval in workflow_state.md before proceeding

**CRITICAL REMINDER**: When a plan has "Approval Required: Yes", the agent MUST:
1. Present the pre-reviews (devil's advocate, expansion)
2. Explicitly ASK: "Do you approve proceeding with Plan XXX implementation?"
3. WAIT for explicit "yes" or approval before ANY execution
4. Record the approval in workflow_state.md BEFORE starting execution
5. NEVER create todos or start coding until approval is recorded

## Execution Rules
### Before Coding

1. Read workflow_state.md for blockers and context
2. Read the plan file completely
3. **Complete Plan Review Checklist** (Section 12.5 of plan)
4. Verify all dependencies are ready (not just planned)
5. Do not execute if:
   - Plan is incomplete
   - Review checklist has unresolved blockers
   - Required approvals not obtained
   - Dependency contracts missing or incompatible

### During Execution

- Follow steps in order
- Check off steps as completed
- Update the plan if deviation is required (with rationale)
- Follow implementation standards for all code
- Verify integration points early (after creating contracts/interfaces, before writing tests) to catch gaps while they are cheap to fix

**Escalate (pause and discuss with human) if:**
- Estimated effort exceeds plan by >50% - requires scope review
- External dependency unavailable or changed - requires impact assessment
- Security concern identified - requires security review
- Breaking change to interface contract needed - requires ADR and consumer notification

**Anti-patterns during execution:**
- Modifying plan scope silently without documenting rationale
- Over-engineering beyond what the plan specifies
- Adding features or refactoring beyond the current task
- **Blindly auto-fixing linter warnings** - see Linter Warning Protocol below

**Fixing pre-existing defects (immediate vs backlog):** when a pre-existing defect
blocks the current governed plan and the validation context is already loaded, fix it
in the same session -- UNLESS the fix changes scope, security posture, or architecture,
in which case pause and escalate. Use a backlog item only for separable work that is
not blocking the current plan. Do not silently expand scope; note in-session fixes in
the plan's execution log.

### After Execution

- Run validation commands
- **Complete retrospective** using docs/ai/prompts/retrospective.md
- Update workflow_state.md:
  - Add to **Blockers** if work cannot proceed (missing deps, approvals, decisions needed)
  - Add to **Next Steps** if work is paused mid-plan with pending items
  - Clear items when resolved
  - Leave as "None" if work completed cleanly
- Update interface contracts if public APIs added/changed
- **Update runbook** if feature adds user-facing commands or operations (see Runbook Rules)
- Create backlog items for discovered work (see Backlog Rules below -- keep items minimal and actionable)
- Detailed changes go in git commits and PR descriptions

**Escalate (before marking complete) if:**
- Test coverage target unreachable - requires scope review or target adjustment

**Anti-patterns after execution:**
- Skipping retrospective to move faster
- Under-documenting changes (missing docstrings, no runbook update)
- Leaving technical debt undocumented

### Session Handoff Hygiene

Do not leave uncommitted or in-flight state across a handoff or session boundary.
Before pausing or handing off work -- especially work that touched deploys, schedules,
migrations, or other operational mutations -- commit, stash, or explicitly document the
uncommitted state and what is safe to resume. The next agent or human must be able to
tell what is done, what is in flight, and what is safe to touch.

## Linter Warning Protocol (Mandatory)
Linters catch syntax issues but can suggest fixes that break **semantic correctness**. Not all warnings should be auto-fixed.

### Safe to Auto-Fix (use `--fix`)

- Unused imports (F401) - unless re-exported for public API
- Trailing whitespace, line length reformatting
- Import sorting
- Missing newlines at end of file

### NEVER Auto-Fix Without Review

| Warning | Risk | Review Question |
|---------|------|-----------------|
| F841 (unused variable) | **HIGH** | Is this variable needed for state tracking, future code, or debugging? |
| F811 (redefinition) | MEDIUM | Is the redefinition intentional (e.g., overwriting in loop)? |
| E501 (line too long) | LOW | Does splitting break readability or introduce bugs? |

### Protocol

1. Run linter without `--fix` first
2. Review each warning manually
3. For F841 (unused variable), ask: "Is this state that future code or the next loop iteration needs?"
4. Only use `--fix` for safe categories above
5. If uncertain, leave the warning and add a `# noqa` comment with rationale

### Example: When NOT to fix F841

A variable flagged as "assigned but never used" may be state that later code,
a subsequent loop iteration, or error/debugging paths depend on. Removing it can
silently change behavior.

```python
# Linter says: F841 Local variable `previous_value` is assigned to but never used
# WRONG: delete the assignment.
# RIGHT: keep it - the next loop iteration compares against it.
previous_value = current_value  # noqa: F841 - read on the next iteration
```

## Retrospective Requirements (Mandatory)
After completing any plan execution, complete a retrospective within 24 hours:

1. **What worked well** - Patterns to repeat
2. **What was harder than expected** - Improve estimation
3. **Discoveries not in the plan** - Improve planning
4. **What would we do differently** - Process improvement
5. **Actionable follow-ups** - Only concrete, near-term work (not wish lists)

Use docs/ai/prompts/retrospective.md template. Archive completed retrospectives in plan file or workflow_state.md.

### Continuous Improvement Loop

Learnings from retrospectives feed back into guardrails:

1. After retrospective, add significant learnings to `docs/ai/state/learnings_tracker.md`
2. Periodically review all learnings and incorporate into appropriate files:
   - Process rules -> `AGENTS.md`
   - Plan structure -> `docs/ai/templates/`
   - Risk patterns -> `docs/ai/prompts/plan_critique.md`
   - Coding patterns -> `docs/ai/standards/`
3. Log incorporated learnings in `docs/ai/state/learnings_tracker.md`

## Study Documentation (A/B Tests and Experiments)
When running empirical comparisons, ablation studies, or experiments, document findings using the study template.

### When to Create a Study

- A/B comparisons
- Ablation studies (removing components to measure impact)
- Hyperparameter sensitivity analysis
- Infrastructure changes with measurable outcomes
- Any experiment where findings should be preserved

### Study Workflow

1. **Before experiment**: Create study file from template
   ```bash
   cp docs/ai/templates/study_template.md docs/studies/STU-YYYY-MM-DD-description.md
   ```
2. **Document hypothesis** in Overview section
3. **Run experiment** and record results in variants
4. **Document results** with metrics table and analysis

### Study Naming Convention

`STU-YYYY-MM-DD-short-description.md`

### Study Artifact Naming

Do not create output-artifact filenames that look like new study IDs unless they are
standalone study documents. When artifacts belong to an existing study, nest them under
the parent study slug and encode the plan number in the directory, not by appending it
to the study date prefix:

- Good: `outputs/studies/STU-2026-05-21-cost-realism/plan209/financials/summary.json`
- Bad: `outputs/studies/STU-2026-05-21-financials-plan209-summary.json`

References in plans, studies, workflow state, and summaries must use the canonical
nested path.

## Quality Gates
### Plan Quality Checklist

Before marking a plan "Ready for Implementation":
- [ ] All sections completed (no TBD on critical items)
- [ ] Dependencies listed with contract references
- [ ] File Impact Map includes test files
- [ ] Execution steps are atomic and verifiable
- [ ] Validation commands will catch regressions
- [ ] Rollback plan tested or documented

### Code Quality Checklist

Before marking execution complete:
- [ ] All tests pass
- [ ] Coverage targets met
- [ ] No linter errors
- [ ] Standards compliance verified
- [ ] Interface contracts updated if needed
- [ ] workflow_state.md updated
- [ ] Runbook updated if user-facing operations added

## Hard Prohibitions
- Do NOT execute plans with incomplete review checklists.
- Do NOT skip dependency verification.
- Do NOT create interfaces without contracts.
- Do NOT skip devil's advocate review before execution.
- Do NOT skip retrospective after execution.
- Do NOT modify `docs/ai/system_architecture.md` without explicit human approval and a version bump recorded in `docs/ai/architectural_design_changelog.md`.
- Do NOT create plans that bypass upstream architecture layers. See `docs/ai/system_architecture.md` for the 6-layer framework.

## Architecture Changelog Scope
`docs/ai/architectural_design_changelog.md` is for durable, higher-level architecture
evolution only. Keep the signal high by recording an entry there ONLY when the system
shape changes in an enduring way:

- Topology, boundaries, or responsibilities between components
- Orchestration model or long-lived runtime lanes
- Layer alignment or the layer framework itself

Do NOT log routine implementation detail there: bug fixes, crash-debugging notes,
performance tweaks (batching, memory trims), queue/cache cleanup, or one-off recovery
steps. That lower-level history belongs in `docs/ai/state/workflow_state.md`, the
relevant plan appendix/retrospective, or the runbook.

## Runbook Rules (Mandatory)
The runbook (docs/runbook/) contains human-readable operational documentation.

### When to Update Runbook

Update the runbook when implementing features that:
- Add new CLI commands or scripts
- Add new data pipelines or scheduled jobs
- Change infrastructure configuration
- Add new environment variables
- Modify database schemas or migrations
- Add new external integrations
- Change how users interact with the system

### Runbook Quality

- Include copy-paste ready commands
- Show both Python API and CLI usage where applicable
- Add troubleshooting sections
- Keep commands tested and current
- No stale documentation

### Verification

Before marking a plan complete, verify:
1. Any new user-facing commands are documented
2. Environment variable changes are listed
3. New scheduled jobs have execution instructions
4. Troubleshooting covers common errors

## Backlog Rules (Mandatory)
The backlog is split into two files:
- `docs/ai/backlog.md` -- Active, pending, blocked, and future items only
- `docs/ai/backlog_archive.md` -- Completed backlog items only

### Adding Items

- Only add **actionable, concrete work** that someone would actually prioritize and execute
- Each item needs: ID, title, priority, effort estimate, status
- Do NOT add speculative "nice to have" ideas, brainstorming, or wish-list items
- Do NOT generate a long tail of follow-up items from retrospectives or reviews --
  if an item would not realistically be worked on in the next 1-2 months, omit it
- If a follow-up naturally belongs inside an existing plan, note it there instead of creating a standalone backlog entry

### Completing Items

- When a backlog item is done, move it from `backlog.md` to `backlog_archive.md`
- Archive entry should be minimal: ID, title, completion date, one-line summary
- Do NOT add plan completion summaries, deliverable lists, or other bloat to
  the archive -- that information belongs in `workflow_state.md` and
  `docs/ai/state/plan_completion_log.md`

### Backlog Hygiene

- `backlog.md` should never contain items marked COMPLETE
- `backlog_archive.md` should only contain completed backlog items, nothing else
- Periodically prune items that are stale, superseded, or no longer relevant
- Include "Last Updated" timestamps in both files

## Collaboration Protocol
For detailed guidance on human-AI collaboration, see docs/ai/collaboration_protocol.md.

Key session types:
- **Plan Review**: Critique and expand plans before execution
- **Spike Session**: Validate uncertainty via time-boxed prototype
- **Execution Session**: Implement a plan following steps
- **Retrospective**: Learn from execution

Prompt templates available in docs/ai/prompts/:
- plan_critique.md - Devil's advocate review
- plan_expansion.md - Gap and edge case analysis
- retrospective.md - Post-execution learning

### Two-Phase Governed Lifecycle

Governed plans move through a two-phase tool chain. The boundary is simple: the
tools own graph state and the agent owns file state. Concretely, **the tools write
ReviewFindings and BacklogItems to the graph and return structured output; the agent
uses that output to update the markdown files** (plan appendix, `backlog.md`,
`learnings_tracker.md`, `workflow_state.md`, and the plan's execution checkboxes).

**Phase 1 -- Pre-implementation review** (begin-plan chain: orient -> prepare_review's
devil's advocate + expansion + gap analysis -> record findings -> stamp the plan as
reviewed). After it runs, the agent MUST:
1. Present the review perspectives (brief, challenges, gaps) to the human.
2. Write the review summary to the plan appendix.
3. Ask whether to proceed, and wait for explicit confirmation before coding.

**Phase 2 -- Post-implementation review / retrospective** (complete-plan chain:
prepare_retro -> record retro insights -> optionally record backlog items). After it
runs, the agent MUST write learnings to `learnings_tracker.md`, add any new backlog
items, update `workflow_state.md`, check off completed plan steps, and write the retro
summary to the plan appendix.

**Strict-mode gate.** When `freshness.gate_strict` is enabled in `scaffold.yaml`, a
gated transition into implementation checks that the pre-implementation review has run
(the plan has been stamped as reviewed). If it has not, implementation is deferred --
run Phase 1 first. Do not work around the gate by editing state manually.

## Review Output Format (Mandatory)
All reviews must be **readable in markdown**:

**Use prose paragraphs for:**
- Findings and explanations
- Risk assessments and recommendations
- Architectural analysis
- Any content requiring more than a few words

**Use tables ONLY for:**
- Pass/fail checklists (single word or short phrase per cell)
- Numeric metrics and scores
- Quick reference summaries

**Anti-pattern**: Do NOT compress narrative findings into table cells. Tables with multi-sentence cells or wrapped content are hard to read.

**Correct pattern**: Use a heading + prose paragraph for each finding, then optionally a summary table with short cell values.

## Review Terminology (Human-Readable)
The governed lifecycle is driven by MCP tools (for example `scaffold_begin_plan`,
`scaffold_complete_plan`, `scaffold_prepare_retro`). Those tool names are an
implementation detail of how work is invoked -- they are NOT the words to use as
the primary description in human-facing artifacts.

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

## Execution Mode
Determine your execution mode before starting any work:

- **Interactive**: You are in an IDE conversation with a human present. Follow standard rules above. Ask when uncertain.

<!-- BEGIN AGENTSCAFFOLD MANAGED SECTION -->
<!-- Managed by AgentScaffold. The content between these markers is regenerated by `scaffold agents ...`; edits inside the block are overwritten. Everything OUTSIDE the markers is always preserved. To take full ownership of this file, add an HTML comment `agentscaffold: managed=false` near the top. Deleting the markers is not ownership: the next generation will append one more block. -->

---
alwaysApply: false
---

# AgentScaffold Tool Routing

Use this file for MCP routing behavior and fallback discipline.
The governance manual above the managed markers is project-owned.

## AgentScaffold Tool Selection Policy (MCP-First with Practical Fallback)

You MUST attempt AgentScaffold MCP tools first when the request matches a known intent.
If MCP output is insufficient, direct file reads/search are allowed.

## Required Procedure

1. Classify the request into an AgentScaffold intent.
2. If matched, call the mapped MCP tool first.
3. If the tool fails or is insufficient, fall back to direct reads/search.
4. Before fallback, state one short reason.
5. If intent is unclear, ask one concise clarification question.

## Fallback Is Allowed When

- MCP tool errors or times out.
- Graph/index is unavailable or stale.
- MCP output does not contain the specific detail needed.

## Situational Tool Use

Match the job class to the first tool. Use as many tools as the job
needs. Count is not the metric. Do not substitute grep, memory, or a
diary dump for the tool named for that job.

| Job | MUST use first | Do not substitute |
|-----|----------------|-------------------|
| Where did we leave off | `scaffold_orient` | diary file dump |
| What's left on a plan | `scaffold_diff_plan_vs_code` | re-read the plan |
| Review / critique a plan | `scaffold_prepare_review` | grep the plan |
| Why was this decided | `scaffold_decision_context` | re-read ADRs ad hoc |
| Any prior experiment | `scaffold_find_studies` / `scaffold_prior_experiments` | memory |
| What ADR governs X | `scaffold_find_adrs` | glob `docs/ai/adrs` |
| Blast radius of a file | `scaffold_impact` | grep imports only |
| Callers of a symbol | `scaffold_context` | grep the name only |
| Parsed vs invisible | `scaffold_validate` (`check=coverage`) | assume the graph is complete |
| Do these plans overlap | `scaffold_compare_plans` | eyeball File Impact |
| Record a strategic call | `scaffold_session_record_decision` | chat only |

## Call Compression Discipline

Do not undo fused responses with redundant follow-ups. Compression
applies only to fields already on the response. It is not a session
budget and not a preferred call count.

- After `scaffold_orient`, act on `recommended_actions` /
  `plan_progress` / `next_action_focus` instead of calling
  `scaffold_next_action` again.
- After empty `scaffold_search`, `scaffold_impact`, or missing-symbol
  `scaffold_context`, use inline `why_empty` and `grep_fallback`
  instead of immediately calling `scaffold_why_empty` or
  `scaffold_grep_graph`.
- Use standalone `scaffold_why_empty`, `scaffold_grep_graph`, and
  `scaffold_next_action` only when fused fields are missing or
  insufficient.
- Prefer `scaffold_diff_plan_vs_code` over dumping or re-reading the
  full plan file just to check progress.
- After `scaffold_orient`, use embedded `session_context` rather than
  calling `scaffold_session_context` unless that field is absent.

## Architectural Research Gate

Before creating or materially revising a plan that changes topology,
public contracts, persistence, security boundaries, or cross-repo
resolution, search the web and local ADRs/studies for how similar
systems solve it. Not required for typo fixes, single-function
bugfixes, or docs-only edits.

- Record alternatives, source links, and pros/cons vs the design you
  were already considering (an Industry cross-check in the plan).
- You may keep the original design.
- If the web is unreachable, say so and use local ADRs/studies only;
  do not skip the alternatives table.
- Full procedure: project-owned `AGENTS.md` Architectural Research Gate.

## Session Working Rhythm

At session start, call `scaffold_session_start` before other writes.
When a strategic, architectural, or operational call is made
(approve, defer, stay the course, change scope), call
`scaffold_session_record_decision` immediately with `kind` and evidence.
Do not record findings, backlog items, or micro-implementation choices
as decisions. Those have their own tools.
At session end, call `scaffold_session_end`. Extra decisions on end append.
Decision lineage for a plan: `scaffold_decision_context` (ADRs, spikes,
studies, plus session decisions for that plan). Prefer that over
re-reading prose.

## Graph Trust Discipline (Avoid Context Blindness)

AgentScaffold's graph is a fast first-pass, not ground truth. Treat its
structural results as evidence to narrow your search, not as proof.

- An empty result (`0 callers`, `0 importers`, no impact) means
  `unconfirmed`, NOT `unused`. Do not conclude code is safe to change
  from an empty graph result alone.
- When search/impact/context returns empty, read `why_empty` and
  `grep_fallback` on that same response before a follow-up tool or
  treating the target as unused.
- Call/import edges exist ONLY for parsed languages (python, javascript,
  typescript, go, rust, java, c, cpp). Markdown, YAML, shell, SQL, JSON,
  and config files are invisible to structural queries. Check the
  `coverage` field on tool output; heed any `caveat`.
- Static analysis cannot see dynamic dispatch, reflection (`getattr`),
  dependency-injection registries, or config/string-driven wiring.
- A non-empty result is also not proof of completeness. `EXTENDS`
  shows the declared class hierarchy; it does not show decorator
  registries, YAML wiring, or other dynamic registration. Do not treat
  "all subclasses of X" as "every registered X".
- Before changing safety-critical, cross-language, or dynamically-wired
  code, confirm usage with a text search (grep) in addition to the graph
  (inline `grep_fallback` counts when present).
- If `scaffold_orient` reports low parsed coverage, lean more on grep.

## Multi-Project Workspace Discipline

If the repo is part of a multi-project workspace (a `workspace.yaml` at the
workspace root lists more than one project), several projects share one
graph. Otherwise (a lone repo) this section is a no-op -- there is exactly
one project and nothing is scoped.

- Reads default to the CURRENT project (resolved from the working
  directory): search and governance queries (plans, findings, learnings,
  studies, ADRs) return only this project's knowledge. Plan numbers and
  file paths are NOT unique across projects, so do not assume a result
  belongs to a sibling.
- VIA MCP TOOLS the server runs from one fixed directory and cannot infer
  which project you are editing. On every project-scoped tool call, pass
  `working_path` = the file or dir you are working on; the server resolves
  the owning project from it and scopes the read accordingly. Omitting it
  falls back to the server's default project.
- To look at another project, pass `project=<name>` (tools) / `--project
  <name>` (CLI); to search across all of them, pass `all_projects=true` /
  `--all-projects` (federated results carry a `project` provenance field --
  always report which project a cross-project hit came from).
- `scaffold graph duplicates` surfaces cross-project near-duplicate
  definitions (shared-library reuse candidates); treat hits as advisory.
- Scoping is a relevance boundary within a single trust domain, not a
  security isolation boundary. When unsure which project you are in, run
  `scaffold workspace list`.

## Governance Guardrails (Always Apply)

- Read and follow `AGENTS.md` before every task.
- Do NOT execute plans with incomplete review checklists.
- Do NOT skip dependency verification.
- Do NOT create interfaces without contracts.
- Do NOT modify `docs/ai/system_architecture.md` without human approval.
- Every feature or bug fix MUST include corresponding tests.
- Emojis are forbidden in repository content.
- Follow core standards: `errors`, `logging`, `config`, `testing`.

## Intent Map

### scaffold_prepare_review

Trigger phrases:
- "review plan X"
- "critique plan X"
- "devil's advocate on plan X"
- "prepare plan X for review"
- "let's review plan X"
- "following the collab protocol for plan X"
- "pre-reviews for plan X"
- "all three reviews for plan X"
- "pressure-test plan X"
- "stress test plan X"
- "challenge this plan before coding"

### scaffold_prepare_implementation

Trigger phrases:
- "implement plan X"
- "start plan X"
- "execute plan X"
- "begin implementation of plan X"
- "what do I need to implement plan X"
- "prep for implementing plan X"
- "approved to go on plan X"
- "begin implementation per collab protocol"
- "start building plan X"
- "begin building plan X"
- "ready to build plan X"

### scaffold_compare_plans

Trigger phrases:
- "does plan X conflict with plan Y"
- "overlap between plans"
- "check plan X vs plan Y"
- "compare plans X and Y"
- "any overlapping concerns between plan X and Y"
- "do plans X and Y overlap"
- "check for conflicts between X and Y"
- "do these plans step on each other"
- "are these plans stepping on each other"

### scaffold_staleness_check

Trigger phrases:
- "is plan X stale"
- "is this plan still valid"
- "is plan X still valid"
- "staleness review on plan X"
- "has anything changed since plan X"
- "does plan X need updating"
- "check if plan X needs refactoring"
- "has this plan gone out of date"
- "is this plan out of date"

### scaffold_prepare_rewrite

Trigger phrases:
- "rewrite plan X"
- "update plan X"
- "expand plan X"
- "refresh plan X with current state"
- "revise plan X"
- "update plan X to use Y"

### scaffold_prepare_retro

Trigger phrases:
- "retro on plan X"
- "retrospective for plan X"
- "post-implementation review"
- "quant architect review on plan X"
- "post implementation review and retro for plan X"
- "share the review and retro"
- "post implementation retrospective"
- "let's do the post-implementation retrospective"

### scaffold_orient

Note: Answers four questions: current work, blockers for that work, related items, and idle-next (`session_brief`). Prefer `recommended_actions` / `plan_progress` / `next_action_focus` over a follow-up `scaffold_next_action` call. Never treat another `scaffold_orient` as the next action.

Trigger phrases:
- "where did we leave off"
- "what's the current state"
- "what's blocked"
- "what are the next steps"
- "where are we"
- "what should I work on now"
- "what are the next priorities"
- "latest blockers and what's next"
- "current blockers and next steps"

### scaffold_session_start

Note: Open a graph Session at the start of a working session so later orientation can read it back. A second start while one is open returns the same id.

Trigger phrases:
- "start a working session"
- "open a scaffold session"
- "begin recording this session"
- "start session tracking"

### scaffold_session_end

Note: Close the open Session with a summary. Extra decisions on end are appended, not replaced. Findings and backlog stay on their own tools -- they are not session decisions.

Trigger phrases:
- "end this session"
- "close the working session"
- "end session with summary"
- "close this working session"

### scaffold_session_record_decision

Note: Record a strategic, architectural, or operational call (approve, defer, stay the course, change scope). Do not record findings, backlog items, or micro-implementation choices.

Trigger phrases:
- "record this decision"
- "log a session decision"
- "note a strategic decision"
- "record this architectural call"
- "capture this operational decision"

### scaffold_session_context

Note: Fallback only. Prefer the `session_context` field already embedded in `scaffold_orient` when sessions exist.

Trigger phrases:
- "recent session context"
- "show session context"

### scaffold_session_list

Trigger phrases:
- "list sessions"
- "show recent sessions"
- "list working sessions"

### scaffold_find_studies

Trigger phrases:
- "any studies on X"
- "experiments related to X"
- "what did we test for X"
- "show me studies about X"
- "prior experiments about X"
- "any prior experiments about X"

### scaffold_prior_experiments

Trigger phrases:
- "has this been tested"
- "prior experiments for plan X"
- "any evidence for this approach"
- "what experiments relate to plan X"

### scaffold_find_adrs

Trigger phrases:
- "any ADRs about X"
- "what architectural decisions cover X"
- "show me ADRs related to storage"
- "which ADR governs X"
- "what ADR blocks plan X"
- "the ADR blocking them"
- "which architecture decision governs X"
- "what architecture decision governs X"

### scaffold_decision_context

Trigger phrases:
- "what's the decision history for plan X"
- "was there a spike for plan X"
- "what ADR governs plan X"
- "show me the full decision chain for plan X"
- "what was the original intent for plan X"
- "trace the decisions for plan X"
- "trace the rationale chain for plan X"
- "why was this plan decided this way"

### scaffold_search

Note: On empty results, read inline `why_empty` and `grep_fallback` before calling `scaffold_why_empty` or `scaffold_grep_graph`.

Trigger phrases:
- "search the workspace for X"
- "search across all projects for X"
- "find code related to X"
- "find duplicates across projects"
- "look for duplicate code in the workspace"
- "search all projects for similar implementations"
- "look across every project for similar implementations"

### scaffold_record_finding

Trigger phrases:
- "record finding"
- "log finding"
- "note a finding"
- "discovered issue in plan"
- "review found an issue"
- "I found an issue in plan X"
- "log this review finding"
- "capture this finding"

### scaffold_resolve_finding

Trigger phrases:
- "mark finding resolved"
- "close finding"
- "fix has been addressed"
- "resolved finding"
- "finding has been closed"
- "mark this issue as resolved"
- "resolve this finding"
- "finding is resolved"

### scaffold_record_findings_batch

Trigger phrases:
- "record all findings"
- "log all findings"
- "record findings batch"
- "record multiple findings"
- "save all review findings"
- "batch record findings"
- "record findings in the plan appendix"
- "log these findings"
- "capture all findings"
- "write all findings to graph"

### scaffold_record_backlog_item

Trigger phrases:
- "add backlog item"
- "record backlog item"
- "log backlog item"
- "add to backlog"
- "create backlog item"
- "note backlog item"
- "track backlog item"

### scaffold_resolve_backlog_item

Trigger phrases:
- "resolve backlog item"
- "close backlog item"
- "mark backlog item done"
- "complete backlog item"
- "archive backlog item"
- "mark backlog item complete"
- "backlog item is done"

### scaffold_begin_plan

Trigger phrases:
- "begin plan X"
- "start plan X"
- "kick off plan X"
- "let's start implementation of plan X"
- "run the pre-reviews for plan X"
- "follow the collab protocol to begin plan X"
- "pre-review chain for plan X"
- "run begin plan for plan X"

### scaffold_complete_plan

Trigger phrases:
- "wrap up plan X"
- "complete plan X"
- "post-implementation for plan X"
- "close out plan X"
- "run the retro for plan X"
- "follow the collab protocol to close plan X"
- "run complete plan for plan X"
- "finish plan X"

### scaffold_diff_plan_vs_code

Note: Preferred mid-implementation progress check (next unchecked step, disk/graph presence, symbol spot-checks). Prefer over re-reading the full plan body for status.

Trigger phrases:
- "diff plan X vs code"
- "what's left on plan X"
- "plan vs implementation for plan X"
- "which planned files are missing"
- "mid-implementation progress on plan X"

### scaffold_grep_graph

Note: Fallback only. Prefer inline `grep_fallback` on empty search/impact when present; otherwise use for low coverage / non-parsed languages.

Trigger phrases:
- "grep the workspace for X"
- "ripgrep for X in the project"
- "text search the repo for X"
- "scaffold grep for X"

### scaffold_why_empty

Note: Fallback only. Prefer inline `why_empty` on empty search/impact/context responses when present.

Trigger phrases:
- "why is search empty"
- "why no callers"
- "why empty impact"
- "explain empty scaffold result"

### scaffold_next_action

Note: Fallback only. Prefer `recommended_actions` from `scaffold_orient` when present.

Trigger phrases:
- "what should I do next"
- "next action"
- "what tool should I call next"
- "route me to the next step"

<!-- END AGENTSCAFFOLD MANAGED SECTION -->

