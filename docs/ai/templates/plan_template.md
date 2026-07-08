# <PLAN_TITLE>

## 0. Metadata
- Plan: TBD
- Issue: #TBD (issue tracker reference, if applicable)
- Branch: feature/TBD or bugfix/TBD
- Author: TBD
- Reviewers: TBD (for critical changes)
- Approval Required: No | Yes (see Approval Gates)
- Security Review: None | Partial | Full (see Security Review criteria below)
- Architecture Layer(s): TBD (6)
- Superseded By: None | Plan XXX (if this plan's work was done elsewhere)

<!-- SUPERSESSION NOTE:
If this plan has been superseded by another plan, add "## STATUS: SUPERSEDED" header
at the top of the file and update the "Superseded By" field above.
Include a disposition table showing where each component moved.
-->

<!-- ARCHITECTURE LAYER GUIDANCE (see docs/ai/system_architecture.md):
CRITICAL: Components MUST consume output from their upstream layer, not bypass
intermediate layers. This is a hard architectural constraint.
-->
<!-- SECURITY REVIEW GUIDANCE:
- Full: Required for external API integrations, authentication, secrets handling
- Partial: Required for data storage, new persistence layers, internal service boundaries
- None: Internal refactors, documentation, UI-only changes

If Full or Partial, create/update threat model in docs/security/
-->

## 1. Objective
What does success mean? Be specific and testable.

## 2. Non-Goals
What is explicitly out of scope?

## 3. Constraints / Invariants
- Must not break:
- Backward compatibility:
- Performance constraints:
- Security constraints:
- Data integrity constraints:
- Breaking change: No | Yes (if yes, see Breaking Changes protocol)

## 4. Current State
Brief, factual description of how things work today.


## 5. Target State
Description of desired behavior after changes.

## 6. File Impact Map
| File | Change Type | Notes |
|-----|------------|-------|
| TBD | TBD | TBD |


## 7. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_TBD.py | TBD | TBD |

Test approach:
- [ ] Unit tests for core logic
- [ ] Integration tests (if applicable)
- [ ] Edge cases: TBD

## 8. Execution Steps

**Note**: If this plan creates a new interface contract, follow contract-first development:
1. Create the interface contract FIRST (docs/ai/contracts/)
2. Run integration verification to validate contract structure
3. THEN implement code to match the contract

- [ ] Step 1: Create interface contract (if applicable)
- [ ] Step 2: Write tests for TBD
- [ ] Step 3: Implement TBD
- [ ] Step 4: Verify tests pass

## 9. Validation
```bash
ruff format .
ruff check .
pytest -q
```

Expected results:
- Lint: no errors
- Tests: all tests pass

## 10. Rollback Plan
How to safely revert if validation fails (e.g., git revert).

## 11. Risks & Mitigations
Known risks and how they are mitigated.

## 12. Completion Checklist
- [ ] All execution steps checked off
- [ ] Tests written and passing
- [ ] No linter errors
- [ ] workflow_state.md updated
- [ ] Session log entry added (if multi-session)
- [ ] Code reviewed (self or peer)
- [ ] Approval obtained (if required)
