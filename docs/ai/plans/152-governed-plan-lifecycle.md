# Plan 152: Governed Plan Lifecycle -- scaffold_begin_plan + scaffold_complete_plan

## 0. Metadata
- Plan: 152
- Branch: feature/plan-152-governed-plan-lifecycle
- Author: Dave Robb
- Approval Required: No
- Security Review: None
- Architecture Layer(s): AgentScaffold (agentscaffold)
- Superseded By: None
- Depends On: Plan 149 (hooks infrastructure), Plan 151 (BacklogItem nodes + batch findings)

## 1. Objective

Today the governance framework is a collection of correct but disconnected tools. An agent
implementing a plan can skip the pre-review, skip findings capture, skip the retro, and
nothing mechanical stops it -- as demonstrated when Plan 151 was implemented without calling
a single MCP tool.

This plan closes that gap by adding two composite tool chains and a strict-mode gate:

1. `scaffold_begin_plan` -- one command that runs orient, all three pre-reviews, auto-writes
   findings to the graph, and returns a structured summary for the agent to present to the
   user before asking whether to proceed.

2. `scaffold_complete_plan` -- one command that runs the post-implementation review and retro,
   auto-writes findings and backlog items to the graph, and returns structured output the
   agent uses to update learnings_tracker.md, backlog.md, workflow_state.md, and the plan
   appendix.

3. Strict-mode gate -- when `freshness.gate_strict = true`, `scaffold_prepare_implementation`
   checks that `scaffold_begin_plan` was called for the plan (via `reviewedAt` stamp on the
   Plan node). Implementation is deferred if the pre-review has not been completed.

4. Fix the broken `scaffold validate --pre-edit` hook -- add a `--warn-only` flag so pre-
   existing interface failures emit warnings rather than exit 1, allowing the gate to function
   as intended for new edits.

5. Clean up duplicate hooks in settings.json (two `scaffold orient` on SessionStart, two
   `scaffold index --incremental` on PostToolUse).

Success means:
- Saying "begin plan 152" runs the full pre-review chain, writes findings to graph, and
  presents three review perspectives to the user before asking to proceed
- Saying "wrap up plan 152" runs the full post-implementation chain and returns structured
  output for all file updates
- When `gate_strict = true`, attempting to implement before `scaffold_begin_plan` is called
  returns a deferred gate error with a clear message
- `scaffold validate --pre-edit` warns on pre-existing failures but does not exit 1

## 2. Non-Goals
- Automatically writing to plan appendix, backlog.md, learnings_tracker.md, or
  workflow_state.md from within the MCP tools themselves. The tools return structured output;
  the agent performs the file writes using that output. This preserves the correct boundary
  (tools own graph state; agent owns file state).
- Fixing the 151 pre-existing interface document validation failures (separate backlog item).
- Adding new review personas beyond what `scaffold_prepare_review` already generates.
- Orchestrating work on backlog items (separate workflow, separate user ask).
- A single end-to-end lifecycle tool that runs all phases without human gates.

## 3. Constraints / Invariants
- Must not break: existing `scaffold_prepare_review`, `scaffold_prepare_implementation`,
  `scaffold_prepare_retro`, `scaffold_record_finding`, `scaffold_record_findings_batch`
- Graph schema changes must be additive (new columns only, SCHEMA_VERSION bump to 6)
- `scaffold_begin_plan` and `scaffold_complete_plan` must work in non-strict mode
  (gate_strict = false) -- the tool chains are always available; the gate is optional
- Backward compatibility: all existing tests must pass
- The two new tools must follow the same dispatch pattern as existing composite tools

## 4. Current State

- Agent begins plan implementation without any forced pre-review step
- `scaffold_prepare_review`, `scaffold_prepare_implementation`, `scaffold_prepare_retro` exist
  as independent read-only tools
- ReviewFindings and BacklogItems must be written manually via separate tool calls
- `scaffold validate --pre-edit` always exits 1 due to 151 pre-existing interface failures,
  making the PreToolUse hook non-functional as a gate
- `settings.json` has duplicate `scaffold orient` on SessionStart (runs twice) and duplicate
  `scaffold index --incremental` on PostToolUse (runs twice)
- Plan node has no `reviewedAt` field; no way to gate implementation on completed review
- CLAUDE.md has no trigger phrases for lifecycle-scoped tool chains

## 5. Target State

### scaffold_begin_plan (new)

Triggered by "begin plan X", "start plan X", "kick off plan X", "let's start implementation
of plan X", "run the pre-reviews for plan X", "follow the collab protocol to begin plan X".

Behavior:
1. Runs `scaffold_orient` -- current project state
2. Runs `scaffold_prepare_review(plan_number)` -- all three review perspectives
3. Auto-writes ALL challenges + gaps as ReviewFindings via `record_findings_batch` with
   `review_type = 'pre_review'`, preserving each item's category and severity
4. Stamps `Plan.reviewedAt = now` on the Plan node (schema v6)
5. Returns structured output:
   - `orient`: current project state summary
   - `pre_review`: brief, challenges, gaps, governing_adrs, open_findings, open_backlog_items
   - `findings_written`: {ids, count} -- what was written to graph
   - `proceed_prompt`: formatted string the agent uses to present reviews to user and ask
     whether to proceed

The agent then:
- Presents the three review perspectives (brief as context, challenges as devil's advocate,
  gaps as gap analysis)
- Writes review summaries to the plan appendix
- Asks the user: "Pre-review complete. [N findings recorded]. Ready to proceed with
  implementation, or would you like to discuss anything first?"

### scaffold_complete_plan (new)

Triggered by "wrap up plan X", "complete plan X", "post-implementation for plan X",
"close out plan X", "run the retro for plan X", "follow the collab protocol to close plan X".

Behavior:
1. Runs `scaffold_prepare_retro(plan_number)` -- retro enrichment + verification
2. Auto-writes retro insights as ReviewFindings via `record_findings_batch` with
   `review_type = 'post_retro'`
3. If `backlog_items` argument provided, calls `record_backlog_items_batch`
4. Returns structured output:
   - `retro`: verification results, retro insights
   - `findings_written`: {ids, count}
   - `backlog_items_written`: {ids, count} (if provided)
   - `structured_learnings`: list of learning dicts formatted for learnings_tracker.md
   - `completion_checklist`: what the agent should update in files

The agent then:
- Writes learnings to learnings_tracker.md
- Writes any new backlog items to backlog.md
- Updates workflow_state.md plan status
- Marks completed steps in the plan file
- Writes retro summary to plan appendix

### scaffold_prepare_implementation gate (strict mode)

When `config.freshness.gate_strict = True`:
- Check `Plan.reviewedAt IS NOT NULL` for the plan
- If null: return `{"error": "scaffold_begin_plan must be called before implementation...",
  "gate_deferred": True}`
- If not null: proceed as normal

### scaffold validate --warn-only

New flag: `scaffold validate --pre-edit --warn-only`
- Outputs validation failures as warnings (prefixed WARN:) instead of errors
- Always exits 0
- Update `settings.json` PreToolUse hook to use `--warn-only`
- Allows the gate to surface issues without blocking all edits

### settings.json dedup

Remove duplicate hook registrations:
- SessionStart: keep one `scaffold orient`, remove duplicate
- PostToolUse: keep one `scaffold index --incremental`, remove duplicate

## 6. File Impact Map

| File | Change Type | Notes |
|------|------------|-------|
| `src/agentscaffold/graph/duckpgq_schema.py` | Modify | Add `reviewedAt VARCHAR` to Plan table; bump SCHEMA_VERSION to 6 |
| `src/agentscaffold/mcp/server.py` | Modify | Add `scaffold_begin_plan`, `scaffold_complete_plan` tools + handlers + NL triggers |
| `src/agentscaffold/review/queries.py` | Modify | Add `stamp_plan_reviewed()` and `get_plan_reviewed_at()` helpers |
| `src/agentscaffold/cli/validate.py` | Modify | Add `--warn-only` flag to `validate` command |
| `tests/test_governed_lifecycle.py` | New | Tests for scaffold_begin_plan, scaffold_complete_plan, strict gate |
| `tests/test_duckpgq_schema.py` | Modify | Update SCHEMA_VERSION assertion (6), node table count |
| `.claude/settings.json` | Modify | Dedup hooks; add `--warn-only` to pre-edit hook |
| `CLAUDE.md` | Modify | Add NL triggers for scaffold_begin_plan, scaffold_complete_plan |
| `AGENTS.md` | Modify | Document the two-phase lifecycle protocol |

## 7. Tests

| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| `tests/test_governed_lifecycle.py` | begin_plan, complete_plan, strict gate, dedup hooks | Integration against real in-memory DuckDB |

Test approach:
- [x] Unit tests for core logic (begin_plan, complete_plan handlers)
- [x] Integration tests against real in-memory DuckDB (no mocks)
- [x] Edge cases: begin_plan on plan with no existing findings, complete_plan with empty
      backlog items, strict gate pass (reviewedAt stamped), strict gate fail (reviewedAt null),
      begin_plan then complete_plan full lifecycle

## 8. Execution Steps

- [x] Step 1: Bump schema to v6 -- add `reviewedAt VARCHAR` to Plan table in
      `duckpgq_schema.py`; update `test_duckpgq_schema.py` counts; update all positional
      INSERT INTO Plan VALUES statements in tests to include 9th column
- [x] Step 2: Add `stamp_plan_reviewed()` and `get_plan_reviewed_at()` to `review/queries.py`
- [x] Step 3: Add `--warn-only` flag to `scaffold validate` CLI; update `settings.json`
      PreToolUse hook to `scaffold validate --pre-edit --warn-only`; remove duplicate hooks
- [x] Step 4: Implement `_tool_begin_plan()` handler in `server.py`:
      - Add graph-health pre-check (verify graph is indexed, warn if empty)
      - Call `_tool_orient()` internally -- return compact summary, not full output
      - Call `_tool_prepare_review()` internally
      - Map challenges + gaps to `record_findings_batch` format (verify field mapping)
      - Write findings via `record_findings_batch(review_type='pre_review')`
      - Stamp `Plan.reviewedAt`
      - Return structured output with `proceed_prompt`
- [x] Step 5: Add `scaffold_begin_plan` Tool definition + dispatch case in `server.py`
- [x] Step 6: Implement `_tool_complete_plan()` handler in `server.py`:
      - Add graph-health pre-check (verify graph is indexed, warn if empty)
      - Call `_tool_prepare_retro()` internally
      - Write retro insights via `record_findings_batch(review_type='post_retro')`
      - Write backlog items if provided via `record_backlog_items_batch()`
      - Return structured output with `structured_learnings` + `completion_checklist`
- [x] Step 7: Add `scaffold_complete_plan` Tool definition + dispatch case in `server.py`
- [x] Step 8: Update `scaffold_prepare_implementation` strict gate: when `gate_strict = True`,
      check `Plan.reviewedAt IS NOT NULL` before proceeding; return gate error if null;
      handle missing Plan node gracefully (warn, don't crash)
- [x] Step 9: Add NL trigger phrases to `TOOL_INTENTS`, `_TOOL_SIGNAL_TOKENS` in `server.py`
- [x] Step 10: Update `CLAUDE.md` intent map with trigger phrases for both new tools
- [x] Step 11: Update `AGENTS.md` with the two-phase lifecycle protocol
- [x] Step 12: Write `tests/test_governed_lifecycle.py` -- include edge cases:
      - begin_plan on plan not in graph (clear error)
      - begin_plan called twice (idempotent, updates reviewedAt)
      - complete_plan before begin_plan (succeeds independently)
      - complete_plan with empty vs missing backlog_items
      - strict gate when Plan node doesn't exist in graph
- [x] Step 13: Run full test suite -- no regressions
- [x] Step 14: Live test full lifecycle end-to-end: begin_plan -> implementation gate check
      (strict mode) -> complete_plan

## 9. Validation

```bash
cd agentscaffold
ruff check src/ --fix
ruff format src/
python -m pytest tests/test_governed_lifecycle.py tests/test_duckpgq_schema.py -v
python -m pytest tests/ -q --tb=short

# Verify pre-edit hook no longer exits 1
scaffold validate --pre-edit --warn-only; echo "exit: $?"

# Live test strict gate
python -c "
from agentscaffold.mcp.server import _dispatch_tool
# Attempt implementation without begin_plan -- should defer
r = _dispatch_tool('scaffold_prepare_implementation', {'plan_number': 152, 'gate_transition': True})
print('gate_deferred:', r.get('gate_deferred'))
"
```

Expected results:
- Lint: no errors
- New tests: all pass
- Existing tests: no regressions
- `scaffold validate --pre-edit --warn-only` exits 0
- Strict gate test: `gate_deferred: True`

## 10. Rollback Plan

All changes are additive. New tools do not modify existing tool behavior except:
- `scaffold_prepare_implementation` gains a new gate check (only active when gate_strict=True)
- `scaffold validate --pre-edit` gains a `--warn-only` flag (old behavior unchanged without flag)
- `settings.json` hook dedup (removes functional duplicates -- no behavioral change)

Rollback: `git revert` the commits. Delete `.scaffold/graph.db` and re-index to drop the
`reviewedAt` column from Plan.

## 11. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `scaffold_begin_plan` generates many ReviewFindings (all challenges + gaps) that clutter the graph | Use `review_type='pre_review'` to distinguish from user-recorded findings; `get_open_findings` already filters by plan_number so clutter is scoped |
| Plan node `reviewedAt` is NULL for all existing plans -- strict gate would block everything | Gate only applies when `gate_transition=True` is explicitly passed; existing workflows unaffected until strict mode is explicitly enabled |
| `scaffold_complete_plan` called before `scaffold_begin_plan` | Not an error -- complete_plan is independent; the gate only lives in `scaffold_prepare_implementation` |
| challenges/gaps written as ReviewFindings don't map cleanly to finding format | Use challenge.text as `finding`, challenge.category as `category`, challenge.severity as `severity`. Same fields, compatible schema. |
| Agent skips file writes after receiving `scaffold_complete_plan` output | AGENTS.md protocol documents what the agent must do with the structured output; CLAUDE.md triggers enforce calling the right tools |
| Graph not indexed -- composite tools run on empty graph, return misleading "success" | Add graph-health pre-check at start of both composite tools; warn in output if graph appears empty |
| Orient output is ~92KB -- including verbatim in begin_plan bloats response | Return compact orient summary (stats + workflow state summary), not full output |
| Strict gate crashes if Plan node doesn't exist in graph | Handle missing Plan node gracefully -- return gate error with clear message, not KeyError |

## 12. Completion Checklist
- [x] All execution steps checked off
- [x] Tests written and passing
- [x] No linter errors
- [x] workflow_state.md updated
- [x] Backlog items for any discovered follow-ups added to backlog.md
