# Feature: AgentScaffold Graph Coverage and Trust Signaling

## 0. Metadata
- Issue: #TBD
- Branch: feature/214-agentscaffold-coverage-signaling
- Severity: Medium (context-blindness risk mitigation)
- Approval Required: No (developer tooling; additive, non-breaking; no live-trading/risk/secrets impact)
- Component: ``
- Source: Context-blindness mitigation assessment 2026-06-12 (P1 set).
- Architecture Layer(s): Cross-Cutting (developer tooling)
- Breaking change: No (additive fields on MCP tool output + additive rule section)

## 1. Objective

The knowledge graph reduces agentic search effort, but it can also cause *context
blindness* if relied on as ground truth. The core failure mode is "absence of evidence
read as evidence of absence": a structural tool returns an empty result and the agent
concludes the code is unused/safe to change.

Two coverage gaps drive this, and neither is currently signaled to the agent:

1. **Language coverage gap.** Call/import edges are only extracted for tree-sitter
   languages (python, javascript, typescript, go, rust, java, c, cpp). In this repo, of
   1409 indexed files only ~761 are deeply parsed; ~648 (`markdown` 423, `yaml` 157,
   `shell` 14, `sql` 12, `toml` 1, plus `unknown` 41) are `File` nodes with **no**
   structural edges. `scaffold_impact` returning `caller_count: 0` is indistinguishable
   from "this file type is not analyzed."

2. **Dynamic-dispatch gap.** Even within parsed Python, static analysis cannot see
   dynamic dispatch, reflection (`getattr`), dependency-injection registries, or
   config/string-driven wiring (Prefect flows, RL/Dirichlet config). An empty
   `callers` result is not proof of no callers.

Staleness is already well-handled by `mcp/freshness.py` (git-signal freshness oracle,
async refresh, optional strict gate). Coverage is not handled at all.

## 2. Scope (P1 only)

In scope (this plan):
- P1.1 Coverage caveat on `scaffold_impact` and `scaffold_context` output (structured
  field + markdown note) whenever a result is empty or the target is an unparsed file.
- P1.2 Repo coverage summary on `scaffold_orient` output (parsed vs unparsed by
  language).
- P1.3 A "Graph Trust Discipline" section in the generated MCP routing rules
  (`generate_rule_policy_document`) instructing the agent to treat empty structural
  results as `unconfirmed`, not `unused`, and to grep for safety-critical / cross-language
  / dynamic usage.

Out of scope (tracked as P2/P3 follow-ups, see Section 9):
- P2: surfacing edge `confidence` / flagging heuristic call resolutions; a dedicated
  coverage/`staleness_check` tool.
- P3: parsing configs/SQL or indexing config-string references; populating `ReviewFinding`
  institutional memory.

## 3. File Impact Map

| File | Change |
|------|--------|
| `src/agentscaffold/mcp/coverage.py` | New: parsed-language detection, `empty_result_caveat`, `repo_coverage` |
| `tests/test_mcp_coverage.py` | New: unit tests for the module + render caveat integration |
| `src/agentscaffold/mcp/server.py` | `_tool_impact`, `_tool_context`, `_tool_orient` attach coverage info |
| `src/agentscaffold/mcp/render.py` | `format_impact_markdown`, `format_context_markdown` accept an optional `caveat` note |
| `src/agentscaffold/agents/rule_policy.py` | Add Graph Trust Discipline section |
| `.cursor/rules/agentscaffold.md` | Regenerated artifact for this repo |

## 4. Tests

| Test File | Coverage |
|-----------|----------|
| `tests/test_mcp_coverage.py` | `language_for_path` / `is_parsed_language` for parsed and unparsed extensions; `empty_result_caveat` (unparsed-file, parsed+zero, parsed+nonzero -> None); `repo_coverage` totals/percentages/summary text; render helpers append the caveat note |
| `tests/test_hooks_generators.py` | Rule policy doc contains the Graph Trust Discipline section |

## 5. Execution Steps
- [x] 5.1 Add `mcp/coverage.py` (detection + caveat + repo_coverage).
- [x] 5.2 Extend render helpers with optional `caveat` note.
- [x] 5.3 Wire coverage into `_tool_impact`, `_tool_context`, `_tool_orient`.
- [x] 5.4 Add Graph Trust Discipline section to `generate_rule_policy_document`.
- [x] 5.5 Tests for coverage module + render + rule section (13 tests).
- [x] 5.6 Regenerate `.cursor/rules/agentscaffold.md`.
- [x] 5.7 Full agentscaffold suite (541 passed) + ruff clean.

## 6. Validation
```bash
uv run python -m pytest tests/test_mcp_coverage.py -q
uv run python -m pytest -q
uv run ruff check src/agentscaffold/mcp/coverage.py
```

## 7. Rollback Plan
All changes are additive. Revert the modified functions to drop the `coverage` field and
the markdown note; delete `mcp/coverage.py` and `tests/test_mcp_coverage.py`; revert the
rule_policy section and regenerate rules. No data migration involved.

## 8. Architecture Alignment
Cross-cutting developer tooling. MCP tools remain the consumption boundary; coverage is
additive metadata on existing tool contracts. No upstream layer bypass.

## 9. P2/P3 Follow-ups (assessment after P1)

P1 closed the highest-leverage gap (silent empty results). Live demo on this repo:
`scaffold_orient` reports "761/1410 files (54.0%) have call/import coverage"; a `.yaml`
config now returns an explicit coverage-gap caveat while real Python targets return none.

**P2 (moderate, recommended next):**
- **Edge-confidence surfacing.** CALLS/METHOD_CALLS carry a `confidence` already queried in
  `_tool_impact`/`_tool_context` but never shown. Surface it and flag heuristic (low-conf)
  resolutions so impact distinguishes solid edges from guesses. Low risk, additive; the
  data already exists.
- **Dedicated coverage/staleness tool.** A `scaffold_coverage` (or extend
  `scaffold_validate check=coverage`) returning `repo_coverage` + per-directory parsed
  ratios, so a human/agent can audit blind spots on demand. Reuses `repo_coverage`.

**P3 (higher effort, 0.4.0):**
- **Broader static coverage via config-reference indexing.** VALIDATED by
  SPIKE-2026-06-12-config-reference-resolution. Extracting fully-qualified dotted references
  under an allowlist of keys (`class`, `_target_`, `type`, ...) resolves at 96.9% precision
  with zero false positives on the indexed config corpus. Value is concentrated in
  `configs/strategies/strategy_registry.yaml` (60+ strategy classes) -- exactly the
  dynamically-dispatched symbols whose call edges are heuristic (Plan 215). Scope the
  implementation to allowlisted-key FQN only, resolve package `__init__` re-exports, reuse
  the graph ignore set, and emit `CONFIG_REFERENCES` edges (file+class=0.9, file-only=0.7).
  Tracked as backlog B-214-1.
- **Populate `ReviewFinding` institutional memory.** Currently ~2 nodes; the "graph as
  memory" value is unrealized. No technical uncertainty (write-back already wired in
  Plans 212/213) -- this is a usage/workflow change: drive finding write-back during
  reviews/retros so the `[PATTERN]` detector and reviewer memory become non-empty.

Recommendation: P2 done (Plan 215). Config-reference indexing is validated and ready for a
0.4.0 implementation plan (B-214-1); ReviewFinding population is a workflow habit, not a
build.

## 10. Retrospective

What worked: the gap was diagnosed from live data (language histogram + edge counts), so
the fix targeted the real blind spot (46% of files unparsed) rather than a hypothetical.
Reusing `File.language` (already populated by structure ingest) meant coverage needed no
new indexing. Additive tool fields + an optional render `caveat` kept the change
non-breaking; all 528 prior tests still pass alongside 13 new ones.

Harder/discovered: staleness was already well-handled by `mcp/freshness.py`, so the initial
"add staleness signaling" framing was wrong -- coverage, not freshness, was the open gap.
Confirming this saved duplicate work. `scaffold agents cursor` also regenerates the Cursor
hooks (via the Plan-pre wiring), so regenerating rules harmlessly re-emitted the debounced
hook script -- verified byte-identical with the venv path intact.

Follow-ups: P2/P3 captured in Section 9.
