# Bugfix: <BUG_TITLE>

## 0. Metadata
- Plan: TBD
- Issue: #TBD (issue tracker reference)
- Branch: bugfix/TBD
- Severity: Low | Medium | High | Critical
- Approval Required: No (unless Critical)

## 1. Bug Description
What is the bug? Include reproduction steps if known.

## 2. Root Cause
What is causing the bug? (May be TBD until investigation)


## 3. Constraints / Invariants
- Must not break:
- Regression risk:

## 4. File Impact Map
| File | Change Type | Notes |
|-----|------------|-------|
| TBD | TBD | TBD |

## 5. Tests
| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| tests/test_TBD.py | Regression test for bug | TBD |

Test approach:
- [ ] Regression test that fails before fix, passes after
- [ ] Edge cases related to bug

## 6. Execution Steps
- [ ] Step 1: Write failing regression test
- [ ] Step 2: Identify and implement fix
- [ ] Step 3: Verify regression test passes
- [ ] Step 4: Run full test suite

## 7. Validation
```bash
ruff format .
ruff check .
pytest -q
```

Expected results:
- Lint: no errors
- Tests: all tests pass (including new regression test)

## 8. Rollback Plan
How to safely revert if fix causes new issues.

## 9. Completion Checklist
- [ ] All execution steps checked off
- [ ] Regression test written and passing
- [ ] No linter errors
- [ ] workflow_state.md updated
- [ ] Issue linked and ready to close
