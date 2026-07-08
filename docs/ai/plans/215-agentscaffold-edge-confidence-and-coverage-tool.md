# Feature: AgentScaffold Edge-Confidence Surfacing and Coverage Check

## 0. Metadata
- Issue: #TBD
- Branch: feature/215-agentscaffold-edge-confidence
- Severity: Low/Medium (trust-signal refinement)
- Approval Required: No (developer tooling; additive, non-breaking)
- Component: ``
- Source: Plan 214 Section 9 (P2 follow-ups).
- Architecture Layer(s): Cross-Cutting (developer tooling)
- Breaking change: No (additive fields + new `check` value)

## 1. Objective

Two P2 refinements from Plan 214's context-blindness work:

1. **Edge confidence is hidden.** CALLS/METHOD_CALLS edges store a `confidence`
   (live distribution: 0.5 / 0.6 = heuristic guesses, 0.85 = resolved, 0.9 = high).
   `_tool_impact` / `_tool_context` already SELECT `r.confidence` but never surface it,
   so an agent treats a guessed edge the same as a resolved one.

2. **Coverage is not queryable on demand.** Plan 214 added `repo_coverage`, surfaced only
   in `scaffold_orient`. There is no way to audit coverage explicitly.

## 2. Scope (P2)
- P2.1 Surface edge confidence: annotate low-confidence (`< 0.75`) callers/callers-into-file
  in `context`/`impact` markdown, add `heuristic_caller_count` to structured output.
- P2.2 Add `check="coverage"` to `scaffold_validate` returning `repo_coverage`.

Out of scope: config-reference indexing and ReviewFinding memory (P3, 0.4.0).

## 3. File Impact Map

| File | Change |
|------|--------|
| `src/agentscaffold/mcp/coverage.py` | Heuristic-confidence helpers + threshold constant |
| `src/agentscaffold/mcp/render.py` | Optional confidence annotation in bullets + section counts |
| `src/agentscaffold/mcp/server.py` | `_tool_context`, `_tool_impact` heuristic counts; `_tool_validate` coverage check; validate schema enum |
| `tests/test_mcp_coverage.py` | Extend with confidence + coverage-check tests |

## 4. Tests

| Test File | Coverage |
|-----------|----------|
| `tests/test_mcp_coverage.py` | `is_heuristic_confidence` threshold behavior (0.5/0.6 true; 0.85/0.9 false; junk false); `count_heuristic` over rows; render low-confidence bullet annotation + header count and high-confidence unannotated; `_tool_validate(check="coverage")` returns `repo_coverage` shape |

## 5. Execution Steps
- [x] 5.1 Add heuristic-confidence helpers + threshold to `coverage.py`.
- [x] 5.2 Annotate confidence in render bullets + section counts.
- [x] 5.3 Wire heuristic counts into `context`/`impact`; add `coverage` check to validate (+ schema enum).
- [x] 5.4 Tests (18 in `test_mcp_coverage.py`).
- [x] 5.5 Full suite (546 passed) + ruff clean.

## 6. Validation
```bash
uv run python -m pytest -q
uv run ruff check src/agentscaffold/mcp/
```

## 7. Rollback Plan
Additive; revert the modified functions and the new `check` branch.

## 8. Retrospective

What worked: the confidence data already existed on edges and was already queried, so
surfacing it was a pure rendering/aggregation change -- no schema or query changes. The
`< 0.75` threshold cleanly separates the observed heuristic band (0.5/0.6) from resolved
(0.85/0.9). Extending `scaffold_validate` with a `coverage` check (vs a new Tool) kept the
MCP surface small and reused `repo_coverage` from Plan 214.

Discovered: the live demo on `handle_strategy_nans` showed 38/39 callers are heuristic
(confidence 0.5) -- it is dispatched dynamically across strategy modules, exactly the
"static analysis can't pin this" case the annotation is meant to flag. This validates the
signal on a real high-fan-in symbol. (Observed separately: `context` caller queries are not
deduped the way `impact` is -- a minor cosmetic dedup opportunity, out of scope here.)

Net: P2 complete; P3 (config-reference indexing + ReviewFinding memory) remains the 0.4.0
follow-up, spike-first.
