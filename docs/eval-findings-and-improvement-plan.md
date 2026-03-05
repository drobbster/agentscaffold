# AgentScaffold Evaluation Findings and Improvement Plan

Generated: 2026-03-05

## Part 1: Evaluation Report

### Run Summary

| Metric | Value |
|--------|-------|
| Total Scenarios | 55 |
| Passed (pytest) | 55/55 |
| Passed (evaluator score) | 52/55 |
| Pass Rate | 94.5% |
| Average Score | 0.92 |

### Category Scores

| Category | Pass Rate | Avg Score | Assessment |
|----------|-----------|-----------|------------|
| Lifecycle | 9/9 | 1.00 | Excellent -- indexing, incremental updates, sessions all solid |
| MCP Tools | 7/7 | 1.00 | Excellent -- all dispatches, JSON well-formed, errors handled |
| CLI | 6/6 | 1.00 | Excellent -- all commands work, templates clean |
| Conversation Replay | 2/2 | 1.00 | Excellent -- full Plan 139-style workflow works end-to-end |
| Benchmarks | 2/2 | 1.00 | Excellent -- search coverage, template quality |
| Review Quality | 9/9 | 0.94 | Good -- gap analysis for draft plans is shallow |
| Edge Cases | 10/12 | 0.88 | Good -- 2 genuine feature gaps exposed |
| Efficiency | 5/5 | 0.80 | Good -- strong call reduction, token compression varies |

### Efficiency Headline Numbers

| Metric | Value |
|--------|-------|
| Avg Token Reduction | 62% |
| Avg Call Reduction | 91% |
| Overall Compression | 3.2x |
| Best task (symbol lookup) | 97% token reduction, 37.6x compression, 14 calls -> 1 |
| Best task (orientation) | 77% token reduction, 39 calls -> 2 |

### Issues Found

Three categories of issues were identified: bugs, feature gaps, and UX friction.

#### Bugs

**BUG-1: Tree-sitter method extraction drops all methods after the first per class**

The `PYTHON_METHOD_QUERY` in `graph/queries.py` uses a nested pattern that matches a
`class_definition > body > block > function_definition`. When tree-sitter's `captures()`
processes this, it returns only the first `function_definition` per block match, silently
dropping subsequent methods.

Evidence: `DatenAnbieter` class has 3 methods (`__init__`, `hole_daten`, `validiere`) but
only `__init__` is extracted. This affects all Python classes with multiple methods.

Root cause: tree-sitter query structure. The pattern matches "a block containing a
function_definition" rather than "each function_definition within a block." This is a
known tree-sitter behavior for sibling captures.

Impact: HIGH. Every Python class with >1 method loses method-level graph data. This
degrades symbol lookup, caller/callee tracing, and method-level search.

Location: `src/agentscaffold/graph/queries.py:27-37`, `src/agentscaffold/graph/parsing.py:440-490`

#### Feature Gaps

**GAP-1: Contract drift detection is unimplemented**

The system ingests contract metadata (name, version, filepath) but never parses the
declared method signatures from contract markdown. No `CONTRACT_DECLARES_FUNC` or
`CONTRACT_DECLARES_CLASS` edges are created. The `scaffold_validate` MCP tool advertises
`contracts` as a check type but returns "not yet implemented."

Evidence: `execution_interface.md` declares `get_fill_rate()` which does not exist in
`engine.py`. The system does not detect this.

Impact: MEDIUM. Contract drift is a governance promise that goes unfulfilled. Agents
cannot verify that code matches its declared interface.

Location: `src/agentscaffold/graph/governance.py:130-150`, `src/agentscaffold/review/queries.py:131-150`

**GAP-2: Plan template graph context is hidden in HTML comments**

The `plan_template.md.j2` injects graph data (hot files, volatile modules) inside HTML
comments that are invisible to AI agents reading the rendered markdown. The agents never
see this information in practice.

By contrast, `agents_md.md.j2` and the critique/expansion prompts render graph data as
visible markdown sections. This inconsistency means the plan template -- the most
frequently generated artifact -- gets the least benefit from graph enrichment.

Evidence: A/B benchmark shows only +797 chars delta for plan template vs. +2,681 for
critique template. The plan template delta is entirely from comment text.

Impact: MEDIUM. The primary user-facing template does not surface graph intelligence to
the agent that will implement it.

Location: `src/agentscaffold/templates/core/plan_template.md.j2:84-95`

**GAP-3: Gap analysis produces thin results for early-stage plans**

The gap analysis engine (`review/gaps.py`) runs four checks: consumer audit, integration
points, similar plan patterns, and test coverage. For Draft plans with small file impact
maps (1-2 files), only the test coverage check typically triggers. This produces a single
gap, scoring 0.50.

Impact: LOW. Draft plans naturally have less context. But the engine could proactively
suggest what's missing rather than just checking what's present.

**GAP-4: `scaffold_validate` MCP tool advertises unimplemented checks**

The tool schema lists `layers`, `contracts`, and `staleness` as valid check types. Only
`staleness` is implemented. `layers` and `contracts` return a generic error message.

Impact: LOW. Agent tries the tool, gets an error, wastes a turn.

#### UX Friction

**UX-1: README documents wrong command (`scaffold cursor setup` vs. `scaffold agents cursor`)**

**UX-2: `scaffold init` default architecture layers (6) disagrees with docs/getting-started.md (3)**

**UX-3: Session ID discovery requires a separate `scaffold session list` call**

**UX-4: No post-`scaffold init` reminder to run `scaffold index` for graph features**

**UX-5: Hybrid search returns identical results to cypher search on small codebases**
The semantic embeddings don't add value until the codebase has enough diversity for
vector similarity to differentiate. On small projects, hybrid mode is overhead with no
benefit.

---

## Part 2: Improvement Plan

### Priority Framework

Items are prioritized by: impact on user experience x frequency of encounter x effort.

| Priority | Item | Category | Effort |
|----------|------|----------|--------|
| P0 | Fix tree-sitter method extraction | Bug | Small |
| P1 | Surface graph context in plan template | Feature | Small |
| P1 | Implement contract drift detection | Feature | Medium |
| P2 | Enrich gap analysis for early-stage plans | Feature | Small |
| P2 | Implement `scaffold_validate` layers/contracts checks | Feature | Small |
| P3 | Fix README command, docs inconsistencies | UX | Trivial |
| P3 | Add post-init graph setup prompt | UX | Trivial |
| P3 | Smart hybrid search fallback | Feature | Small |

### P0: Fix tree-sitter method extraction

**Problem**: Only the first method per class is captured.

**Fix**: Change the tree-sitter query to match each method independently, then derive
the parent class from context. Two approaches:

Option A -- Flatten the query to match `function_definition` nodes that are children of a
`class_definition`'s body, using separate captures:

```
(class_definition
  name: (identifier) @class_name
  body: (block
    (function_definition
      name: (identifier) @method_name
      parameters: (parameters) @params) @method))
```

If this still suffers from the sibling capture issue, use Option B:

Option B -- Run two separate queries. First query captures all class names and their line
ranges. Second query captures all `function_definition` nodes globally. Then in Python,
assign each function to its containing class by line range overlap:

```python
for func in all_functions:
    for cls in all_classes:
        if cls.start_line <= func.start_line <= cls.end_line:
            func.parent_class = cls.name
```

**Files to change**:
- `src/agentscaffold/graph/queries.py` -- update `PYTHON_METHOD_QUERY`
- `src/agentscaffold/graph/parsing.py` -- update `_extract_methods()` if using Option B
- `tests/` -- add test with multi-method class

**Validation**: Re-run eval, `unicode_methods_extracted` should pass with score 1.0.
All existing tests should continue to pass.

### P1a: Surface graph context in plan template as visible markdown

**Problem**: Graph-injected hot files and volatile modules are in HTML comments.

**Fix**: Add a visible "Codebase Context (Graph-Generated)" section to the plan template,
gated by `{% if graph_hot_files or graph_volatile_modules %}`. Include:

- Hot files with plan counts (alert: "high blast radius")
- Volatile modules (alert: "consider stability review")
- Active contracts relevant to the file impact map (if contract-file edges exist)

Place this section after the File Impact Map (Section 6) where it is most actionable.
Keep the HTML comments as additional detail.

**Files to change**:
- `src/agentscaffold/templates/core/plan_template.md.j2`

**Validation**: Re-run eval, `graph_enrichment` marker test for plan template should
pass. A/B delta should increase from +797 to >+1500 chars.

### P1b: Implement contract drift detection

**Problem**: Contracts are ingested as metadata-only nodes with no link to code.

**Fix**: Three changes:

1. **Parse contract method declarations** -- In `governance.py`, add a parser that
   extracts function/method signatures from the code blocks in contract markdown files.
   Store as `DeclaredInterface` nodes or simply as properties on the `Contract` node.

2. **Create `CONTRACT_DECLARES` edges** -- Link each declared method/class name to the
   corresponding `Function`/`Method`/`Class` node if it exists in the graph. If it
   does not exist, record it as an unresolved declaration.

3. **Add drift check** -- In `graph/verify.py` or a new `review/drift.py`, compare
   declared interfaces against code. Report:
   - Methods declared in contract but not found in code (missing implementation)
   - Methods in code but not declared in contract (undocumented API)
   - Signature mismatches (parameter count/type changes)

4. **Implement `scaffold_validate contracts`** -- Wire the drift check into the MCP
   `scaffold_validate` tool and the CLI `scaffold graph verify` command.

**Files to change**:
- `src/agentscaffold/graph/governance.py` -- add method signature parsing
- `src/agentscaffold/graph/store.py` -- add `DeclaredInterface` node type if needed
- `src/agentscaffold/graph/verify.py` or new `src/agentscaffold/review/drift.py`
- `src/agentscaffold/mcp/server.py` -- implement `contracts` check in `_tool_validate`
- `tests/` -- contract drift tests

**Validation**: Re-run eval, `contract_drift_detection` should pass with score 1.0.
`scaffold_validate contracts` should return meaningful results.

### P2a: Enrich gap analysis for early-stage plans

**Problem**: Draft plans with small file impact maps produce only 1 gap.

**Fix**: Add two new gap checks to `review/gaps.py`:

1. **Dependency completeness** -- For each file in the impact map, check if it imports
   modules that are not also in the impact map. If so, flag as "upstream dependency not
   in scope."

2. **Missing sections** -- Check for required plan sections that are still TBD. Flag
   as "plan section needs completion" gaps. This is especially useful for Draft plans
   where most sections are placeholders.

**Files to change**:
- `src/agentscaffold/review/gaps.py`
- `tests/` -- gap analysis tests for draft plans

### P2b: Implement remaining `scaffold_validate` checks

**Problem**: `layers` and `contracts` checks are advertised but not implemented.

**Fix**:
- `layers`: Check that each file in the graph is assigned to exactly one architecture
  layer, and that import edges don't bypass layers (Layer 4 importing Layer 1 directly).
- `contracts`: Wire to the contract drift detection from P1b.

**Files to change**:
- `src/agentscaffold/mcp/server.py` -- implement `layers` check in `_tool_validate`
- `src/agentscaffold/graph/verify.py` -- add layer conformance check

### P3: Documentation and UX fixes

These are all trivial, independent fixes:

1. **README**: Change `scaffold cursor setup` to `scaffold agents cursor`
2. **getting-started.md**: Align default architecture layers with `init_cmd.py` (both
   should say 6, or both should say 3 with 6 being a flag)
3. **Post-init**: Add `scaffold index` to the "next steps" printed after `scaffold init`
4. **Session ID UX**: Print session ID prominently after `scaffold session start` and
   suggest `scaffold session end <ID>` as the next step
5. **Hybrid search**: When the codebase has <100 files, default search mode to `cypher`
   and skip embedding generation. Log a note: "small codebase, using structural search"

**Files to change**:
- `README.md`
- `docs/getting-started.md`
- `src/agentscaffold/cli/init_cmd.py` -- post-init message
- `src/agentscaffold/cli/session_cmd.py` -- session start output
- `src/agentscaffold/graph/search.py` -- small-codebase fallback

### Execution Order

```
P0 (method extraction)  ->  re-run eval to confirm fix
P1a (plan template)     ->  re-run eval to confirm enrichment
P1b (contract drift)    ->  re-run eval to confirm drift detection
P2a (gap enrichment)    ->  re-run eval to confirm improved scoring
P2b (validate checks)   ->  re-run eval
P3 (docs/UX fixes)      ->  manual verification
```

P0 should be done first because it affects the quality of all downstream graph features.
P1a and P1b are independent and can be done in parallel. P2a and P2b depend on P1b for
contract-related checks. P3 items are independent and can be done at any time.

### Expected Impact on Eval Scores After All Fixes

| Category | Current | Expected |
|----------|---------|----------|
| Edge Case | 0.88 | 1.00 (unicode + drift fixed) |
| Review | 0.94 | 0.97+ (gap analysis improved) |
| Efficiency | 0.80 | 0.80 (no change -- efficiency is structural) |
| Unknown (graph enrichment) | 0.44 | 1.00 (plan template renders markers) |
| Overall | 0.92 | 0.97+ |
