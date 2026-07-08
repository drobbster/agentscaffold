# Interface Contract: MCP Write-Path Tools

**Version**: 1.0
**Plan**: 149 — AgentScaffold Architecture Evolution
**Status**: Stable
**Source**: `src/agentscaffold/graph/findings.py`,
           `src/agentscaffold/mcp/server.py`

---

## Overview

Two MCP tools introduced in Plan 149 write state into the knowledge graph during active
coding sessions. They complement the existing read-only MCP tools by closing the
review-finding loop: reviewers surface issues, agents record them, and the graph persists
them across sessions.

| Tool | Direction | Latency target |
|---|---|---|
| `scaffold_record_finding` | Write — creates `ReviewFinding` node | < 200 ms |
| `scaffold_resolve_finding` | Write — updates `ReviewFinding` status | < 200 ms |

---

## scaffold_record_finding

**Intent**: Record a review finding discovered during a plan review session.

### MCP Arguments

```json
{
  "plan_number":  123,
  "review_type":  "quant_architect",
  "category":     "correctness",
  "finding":      "Risk bounds not enforced for leveraged positions",
  "severity":     "high",
  "file_paths":   ["libs/risk/manager.py"],
  "function_ids": []
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `plan_number` | int | Yes | Plan number this finding belongs to |
| `review_type` | str | Yes | Reviewer name or type label |
| `category` | str | Yes | e.g. "correctness", "performance", "security" |
| `finding` | str | Yes | Human-readable finding description |
| `severity` | str | No | "low" \| "medium" \| "high" \| "critical" (default: "medium") |
| `file_paths` | list[str] | No | Repo-relative paths of affected files |
| `function_ids` | list[str] | No | IDs of affected Function nodes |

### Response

```json
{
  "id":          "rf::a3f9c12d8b4e",
  "status":      "open",
  "plan_number": 123,
  "review_type": "quant_architect",
  "category":    "correctness",
  "severity":    "high",
  "elapsed_ms":  42.3,
  "created_at":  "2026-03-16T11:00:00+00:00"
}
```

### Behaviour

- `id` is deterministic: SHA-1 of `plan_number + review_type + category + finding[:64]`.
  Calling the tool twice with identical arguments creates duplicate nodes. Callers should
  check whether a finding already exists before re-recording.
- Creates `FINDING_ABOUT_FILE` edges for each entry in `file_paths` (silently skips any
  path not indexed as a `File` node).
- Creates `FINDING_ABOUT_FUNC` edges for each entry in `function_ids`.

---

## scaffold_resolve_finding

**Intent**: Mark an existing `ReviewFinding` as resolved.

### MCP Arguments

```json
{
  "finding_id": "rf::a3f9c12d8b4e",
  "resolution": "Added bounds check in RiskManager.validate_position()"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `finding_id` | str | Yes | The `id` returned by `scaffold_record_finding` |
| `resolution` | str | Yes | Human-readable description of how it was fixed |

### Response

```json
{
  "id":         "rf::a3f9c12d8b4e",
  "status":     "resolved",
  "resolution": "Added bounds check in RiskManager.validate_position()",
  "elapsed_ms": 18.7
}
```

### Behaviour

- Sets `status = "resolved"` and writes `resolution` text in-place on the node.
- The node is not deleted — resolved findings remain queryable for retrospectives and
  history.
- Calling on an already-resolved finding is a no-op (idempotent).

---

## Effect on scaffold_prepare_review

`scaffold_prepare_review` surfaces open findings in its context output:

```json
{
  "open_findings": [
    {
      "id": "rf::a3f9c12d8b4e",
      "severity": "high",
      "category": "correctness",
      "finding": "Risk bounds not enforced for leveraged positions"
    }
  ]
}
```

Findings are filtered to `status = "open"` and sorted by severity (critical → high →
medium → low). Resolved findings do not appear.

---

## Intent Routing

The `route_tool_from_prompt()` function in `mcp/server.py` routes natural-language
prompts to these tools. Key signal tokens and normalizer rules (as of Plan 149):

| Prompt pattern | Routes to |
|---|---|
| "record finding", "log finding", "note a finding" | `scaffold_record_finding` |
| "review found [X]" | `scaffold_record_finding` (normalizer: `review found` → `record finding`) |
| "review discovered [X]" | `scaffold_record_finding` (normalizer: `review discovered` → `record finding`) |
| "mark finding resolved", "close finding" | `scaffold_resolve_finding` |
| "[issue] has been fixed" | `scaffold_resolve_finding` (normalizer: `has been fixed` → `resolved finding`) |

---

## Security Notes

- These tools write to the local DuckDB file. No network calls are made.
- Input is sanitized via single-quote doubling (`_esc()`) before interpolation into SQL.
  Parameterised queries should be preferred in a future hardening pass.
- No authentication or authorization gate is applied at the MCP layer. The MCP server
  runs locally on stdio; access control is the host platform's responsibility.
