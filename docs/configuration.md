# Configuration Reference

This document describes every section and field in `scaffold.yaml`. After editing, run `scaffold agents generate` to regenerate AGENTS.md.

## Top-Level Sections

### framework

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| version | string | "1.0" | Framework version (informational) |
| project_name | string | "My Project" | Project name used in templates |
| architecture_layers | int | 6 | Number of layers in system architecture |

### profile

| Value | Description |
|-------|-------------|
| interactive | Human + AI in IDE. Agent asks questions when uncertain. |
| semi_autonomous | Agent invoked from CLI/CI without human. Adds session tracking, safety boundaries, notifications. |

Default: `interactive`

### rigor

| Value | Description |
|-------|-------------|
| minimal | Lightweight gates for prototypes and small projects |
| standard | Full plan lifecycle with reviews, contracts, retrospectives |
| strict | All gates enforced, domain implementation review, approval required |

Default: `standard`

### domains

List of installed domain pack names (e.g. `trading`, `webapp`, `mlops`). Domain packs add review prompts, standards, and approval gates. See [Domain Packs](domain-packs.md).

Default: `[]`

### extends (config inheritance)

Inherit shared policy from a base config instead of copying it into every repo.
The value is one of:

- A **filesystem path** to a base `scaffold.yaml` -- absolute, or relative to the
  directory of the file that declares `extends`. A path to a directory resolves
  to `<dir>/scaffold.yaml`.
- The literal **`home`** -- the org/user-level config at `$AGENTSCAFFOLD_HOME`
  (or `~/.agentscaffold/scaffold.yaml` when the env var is unset). An absent home
  config is a no-op, so `extends: home` is safe on a machine without shared config.

```yaml
# project scaffold.yaml
extends: home          # or: ../shared/scaffold.yaml
framework:
  project_name: MyService
domains: [trading]     # overrides the base's domains list
```

**Resolution precedence** (low to high): built-in defaults, then the `extends`
base chain (resolved recursively, base values lowest), then this project's
`scaffold.yaml`, then environment overrides (e.g. `AGENTSCAFFOLD_DB_PATH`).
Merging is per-field deep-merge; **lists are replaced wholesale**, not
concatenated (e.g. setting `domains` in the project replaces the base's
`domains` entirely). A child always overrides its base, so a project can tighten
policy but a shared base cannot silently loosen a stricter project setting.

Cycles (`A extends B extends A`) and a missing **explicit** base raise a clear
error; an absent **home** base is silent.

**Trust boundary**: a base/home config can influence gates and `approval_required`.
It is owned by the same user/org as the checkout, parsed as YAML data only (never
executed), and resolved only from the explicit path or the fixed home location
(no network, no implicit discovery). Inspect the effective result with:

```bash
scaffold config show   # prints the inheritance chain (base-first) + merged config
```

Default: unset (no inheritance; a repo without `extends:` behaves exactly as before).

---

## Gates

Gates control transitions between plan lifecycle states: Draft -> Review -> Ready -> In Progress -> Complete.

### gates.draft_to_review

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| plan_lint | bool | true | Require plan lint to pass |
| architecture_layer_check | bool | true | Verify plan maps to a layer in system_architecture.md |

### gates.review_to_ready

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| devils_advocate | bool | true | Require devil's advocate review |
| expansion_review | bool | true | Require expansion/gap analysis review |
| domain_reviews | list[str] | [] | Domain-specific review names (from domain packs) |
| spike_for_high_uncertainty | bool | true | Require spike when plan has high uncertainty |
| interface_contracts | bool | true | Require interface contracts for exports |
| security_review | bool | true | Require security review when applicable |

### gates.ready_to_in_progress

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| review_checklist | bool | true | Require plan review checklist completed |
| approval_gates | bool | true | Require human approval for approval-required changes |
| interactive_gate | bool | true | Require human confirmation when "review it with me" requested |

### gates.in_progress_to_complete

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| all_steps_checked | bool | true | All execution steps must be checked off |
| validation_commands | bool | true | Validation commands must pass |
| tests_pass | bool | true | Tests must pass |
| retrospective | bool | true | Retrospective must be completed |
| domain_implementation_review | bool | false | Domain-specific post-implementation review (e.g. quant_architect_implementation) |

---

## Rigor Presets

Rigor presets override gate defaults. The preset is applied when loading config.

### minimal

- `architecture_layer_check`: false
- `devils_advocate`, `expansion_review`, `spike_for_high_uncertainty`, `interface_contracts`, `security_review`: false
- `review_checklist`, `approval_gates`, `interactive_gate`: false
- `retrospective`: false

### standard

No overrides. Uses default gate values.

### strict

- `security_review`: true
- `approval_gates`: true
- `domain_implementation_review`: true
- `ci.plan_lint`: true

---

## approval_required

Determines which change types require human approval before execution.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| breaking_changes | bool | true | Breaking API/schema changes |
| security_sensitive | bool | true | Auth, crypto, secrets |
| data_migrations | bool | true | Database migrations |
| infrastructure | bool | true | Terraform, Docker, infra |
| external_apis | bool | true | External API integrations |

Domain packs can add approval gates (e.g. `financial_calculations`, `model_deployment`).

---

## standards

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| core | list[str] | ["errors", "logging", "config", "testing"] | Core standards referenced in plans |
| domain | list[str] | [] | Domain-specific standards (from domain packs) |

---

## prohibitions

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| emojis | bool | false | Forbid emojis in code, docs, logs |
| patterns | list[str] | [] | Regex patterns to forbid (e.g. `TODO`, `FIXME`) |

---

## agents

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| agents_md | bool | true | Generate AGENTS.md |
| cursor_rules | bool | true | Generate .cursor/rules.md |

---

## semi_autonomous

Only applies when `profile: semi_autonomous` or `semi_autonomous.enabled: true`.

### semi_autonomous.enabled

| Type | Default | Description |
|------|---------|-------------|
| bool | false | Enable semi-autonomous enhancements |

### semi_autonomous.session_tracking

| Type | Default | Description |
|------|---------|-------------|
| bool | true | Track agent sessions in docs/ai/state/sessions/ |

### semi_autonomous.context_handoff

| Type | Default | Description |
|------|---------|-------------|
| bool | true | Support context handoff between sessions |

### semi_autonomous.safety

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| read_only_paths | list[str] | ["docs/ai/system_architecture.md", "scaffold.yaml", ".github/"] | Paths the agent must not modify |
| require_approval_paths | list[str] | ["infra/", "docs/security/"] | Paths requiring human approval before modification |

### semi_autonomous.notifications

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | true | Enable notification hooks |
| channel | str | "github_issue" | `stdout`, `github_issue`, or `slack` |
| slack_webhook_env | str | "SLACK_WEBHOOK_URL" | Env var for Slack webhook URL |
| notify_on | list[str] | ["plan_complete", "escalation", "validation_failure", "approval_required"] | Events that trigger notifications |

### semi_autonomous.cautious_execution

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_fix_attempts | int | 2 | Max auto-fix attempts before escalation |
| max_new_files_before_escalation | int | 5 | Max new files before escalating for review |

---

## import

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| conversation_dir | str | "data/conversations" | Directory for imported conversation files |

---

## collab

Collaboration ergonomics (Plan 226). Opt-in sharding of high-contention
governance files plus an advisory plan-ownership convention. All fields default
to today's single-file behavior, so a repo that does not set `collab.sharded`
is unaffected.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| sharded | bool | false | Store `workflow_state.md` / `backlog.md` as per-entry fragments assembled by `scaffold state render` |
| workflow_fragments_dir | str | "docs/ai/state/workflow_state/" | Directory of `workflow_state` fragments when sharded |
| backlog_items_dir | str | "docs/ai/state/backlog_items/" | Directory of `backlog` fragments when sharded |
| claims_dir | str | "docs/ai/state/claims/" | Directory of advisory plan-claim records |

**Sharding workflow.** With `collab.sharded: true`:

```bash
scaffold state split workflow_state   # shard the monolithic file into fragments (reversible)
# ... agents edit individual fragment files (low merge-conflict surface) ...
scaffold state render                 # reassemble canonical workflow_state.md / backlog.md
```

`split` is idempotent and lossless; `render` is its deterministic inverse
(concatenating fragments in ordinal order reproduces the source byte-for-byte,
and re-rendering unchanged fragments does not touch the file). The canonical
rendered file remains the source consumed by graph ingestion and CI.

**Advisory claims.** `scaffold plan claim <number> --owner <who>` writes a small
git-backed JSON record under `claims_dir`; `scaffold plan release <number>`
clears it. `scaffold plan status` shows an Owner column when any claims exist.
Claims are advisory visibility, not enforced locks: two writers can still edit
the same plan, and git resolves the result.

---

## task_runner

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| justfile | bool | true | Generate justfile |
| makefile | bool | true | Generate Makefile |

---

## ci

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| provider | str | "github" | CI provider (only `github` supported) |
| security_scanning | bool | true | Generate security workflow (Bandit, TruffleHog) |
| study_lint | bool | true | Run `scaffold study lint` in CI |
| plan_lint | bool | false | Run `scaffold plan lint` in CI (true for strict rigor) |
| semi_autonomous_pr_checks | bool | false | Generate semi-autonomous PR validation workflow |

---

## graph

Knowledge-graph backend, indexing, and governance paths.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| db_path | str | `.scaffold/graph.duckdb` | Graph database location. Relative values resolve against the project root (see below); absolute values are used as-is |
| backend | str | `duckpgq` | Graph backend (only `duckpgq` is supported) |
| plans_dir | str | `docs/ai/plans/` | Plans directory |
| contracts_dir | str | `docs/ai/contracts/` | Interface contracts directory |
| learnings_file | str | `docs/ai/state/learnings_tracker.md` | Learnings tracker |
| studies_dir | str | `docs/studies/` | Studies directory |
| adrs_dir | str | `docs/ai/adrs/` | ADRs directory |
| spikes_dir | str | `docs/ai/spikes/` | Spikes directory |
| workflow_state_file | str | `docs/ai/state/workflow_state.md` | Workflow state file |
| backlog_file | str | `docs/ai/backlog.md` | Active backlog |
| backlog_archive_file | str | `docs/ai/backlog_archive.md` | Archived backlog |
| standards_dir | str | `docs/ai/standards/` | Implementation standards |
| prompts_dir | str | `docs/ai/prompts/` | Prompt templates |
| templates_dir | str | `docs/ai/templates/` | Plan/spike/study templates |
| plan_completion_log_file | str | `docs/ai/state/plan_completion_log.md` | Plan completion log |
| security_dir | str | `docs/security/` | Security/threat-model docs |
| governance_artifact | str | `docs/ai/state/governance.json` | Git-committed system of record for findings/sessions/backlog (see below) |
| embeddings | bool | false | Generate code embeddings during indexing |
| communities | bool | true | Detect module communities during indexing |
| incremental_community_refresh | `"structure" \| "always" \| "threshold"` | `structure` | Controls when incremental indexing refreshes community clusters. `structure` refreshes on add/delete only; `always` preserves old per-run behavior; `threshold` refreshes when the changed-file count reaches `incremental_community_threshold` |
| incremental_community_threshold | int | `25` | Changed-file threshold used when `incremental_community_refresh: threshold` |
| incremental_min_interval_seconds | int | `0` | Minimum seconds between generated async structural-index hook runs. `0` disables the interval guard; the hook remains single-flight/coalesced |
| embedding_min_interval_seconds | int | `0` | Minimum seconds between async embedding refreshes. `0` disables the interval guard; requests remain single-flight/coalesced |
| async_embeddings | `"off" \| "idle" \| "interval" \| "commit"` | `off` | Controls whether AgentScaffold schedules background embedding refreshes. `off` preserves historical behavior and never loads the embedding model |

### Incremental index policy

Generated edit hooks run `scaffold index --incremental` in the background using a
single-flight lock and a coalesced trailing run. `incremental_min_interval_seconds`
adds an optional interval guard for very high-edit-volume sessions; leave it at
`0` to run after every coalesced edit burst.

Incremental indexing keeps embeddings out of the per-edit hot path. If you pass
`--embeddings` explicitly with `--incremental`, AgentScaffold scopes embedding
work to the changed-file neighborhood and preserves the existing content-hash
skip. If there are no structural changes, an incremental embedding run performs a
content-hash reconcile so missing embeddings can be backfilled asynchronously.
Run a full `scaffold index --embeddings` when you want an authoritative
semantic-search reconcile.

`async_embeddings` controls automatic background embedding refresh:

- `off`: default. No background embedding work and no embedding model load.
- `idle`: MCP may schedule one background embedding refresh when retrieval is
  degraded and the structural index lock is idle.
- `interval`: same as `idle`, additionally bounded by
  `embedding_min_interval_seconds`.
- `commit`: generated git `post-commit` and `post-merge` hooks request a
  non-blocking embedding refresh at commit boundaries; MCP degradation repair can
  still schedule a single background refresh when needed.

### Project-root resolution

All governance paths above are resolved relative to a single **project root**,
determined in this order: the directory of the nearest `scaffold.yaml`, then the
nearest ancestor containing `.git`, then the current working directory. Every
CLI command uses this same rule, so running e.g. `scaffold plan create` or
`scaffold graph search` from a subdirectory behaves the same as running it from
the project root.

A relative `db_path` resolves against the **workspace root** (the nearest
`workspace.yaml`, or the project root for a lone repo), so `scaffold index`
(which writes the graph) and graph queries (which read it) always agree on the
location regardless of the working directory -- and every project in a
multi-project workspace shares one cache. For a single-project repo the
workspace root is the project root, so this is byte-for-byte the previous
behavior. If you set an absolute `db_path`, it is honored unchanged.

### Multi-project workspaces

A `workspace.yaml` at the workspace root lets several projects share one graph
cache:

```yaml
projects:
  - name: api
    path: services/api
  - name: web
    path: apps/web
```

| Field | Type | Description |
|-------|------|-------------|
| projects[].name | str | Unique project namespace (`[A-Za-z0-9._-]+`; no whitespace, quotes, or `::`). Used to qualify node IDs (`{name}::{raw_id}`) and scope reads |
| projects[].path | str | Project root (the dir with its `scaffold.yaml`); relative values resolve against the workspace root |

Manage it with `scaffold workspace onboard <dir> [--name <name>]` (adds a
project, creating the manifest on first use) and `scaffold workspace list`.
Behavior:

- **No manifest (default):** a single synthesized project; nothing is
  ID-prefixed and every scope predicate is a no-op -- identical to pre-workspace
  behavior.
- **More than one project:** the workspace is multi-project. Nodes are
  ID-prefixed by project and stamped with a `project` column. Reads (search,
  governance queries, prune) default to the **current** project (resolved from
  the working directory); pass `--project <name>` to target a sibling or
  `--all-projects` to federate (federated results carry per-row provenance).
- **Re-keying an existing cache:** `scaffold workspace onboard <dir>
  --migrate-existing <name>` rewrites an existing single-project cache into the
  named project in place (atomic, idempotent, rollback-safe, integrity-checked).
  Otherwise re-index.

#### Current project resolution in agent sessions

Agents usually do not need to mention the workspace. The current project is
resolved from the process working directory: AgentScaffold finds the nearest
workspace root, then checks which registered project contains the current path.

For example:

```text
~/dev/trading-stack/
  workspace.yaml
  market-data-service/
    scaffold.yaml
  strategy-engine/
    scaffold.yaml
```

When an agent runs from `market-data-service`, unqualified reads stay in that
project:

```bash
cd ~/dev/trading-stack/market-data-service
scaffold graph search "symbol normalization"     # market-data-service only
```

When the agent runs from `strategy-engine`, the same unqualified command stays
in `strategy-engine`:

```bash
cd ~/dev/trading-stack/strategy-engine
scaffold graph search "symbol normalization"     # strategy-engine only
```

Use explicit scope only for cross-project work:

```bash
scaffold graph search "symbol normalization" --project market-data-service
scaffold graph search "symbol normalization" --all-projects
scaffold graph duplicates --table Function
```

Generated agent rules reinforce this default: current-project first, explicit
scope widening for sibling/federated reads, and project provenance preserved in
cross-project results.

The workspace is a single trust domain: project scoping is a relevance and
correctness boundary (no cross-project misorientation), not a security isolation
boundary.

### Durable vs ephemeral cache location

`db_path` is resolved for both persistent and ephemeral environments:

1. The `AGENTSCAFFOLD_DB_PATH` environment variable, if set, overrides
   `graph.db_path` entirely. Point it at a mounted/durable volume on a persistent
   box, or a scratch path on an ephemeral devbox -- without editing the committed
   `scaffold.yaml`.
2. Otherwise `graph.db_path` is used.

The chosen value then has `${VAR}`/`$VAR` environment placeholders and a leading
`~` expanded, so one committed config works across machines (e.g.
`db_path: ${XDG_CACHE_HOME}/agentscaffold/graph.duckdb`). Relative results still
resolve under the project root; absolute results are honored as-is.

Because the cache is a derived index, an ephemeral devbox can start with no cache
at all: `scaffold index` rebuilds it from source plus the committed governance
artifact (below) and reports `Restored N governance record(s) ... from the
committed artifact` when it does so.

### Git-backed governance (system of record)

Review findings, sessions, and backlog items are agent-generated knowledge that
the code graph cannot reconstruct from source. They are serialized to
`graph.governance_artifact` (a versioned JSON file, committed to git) whenever
they are recorded or resolved. The DuckDB graph is a derived index: `scaffold
index` ingests the artifact (idempotently) so a fresh clone or a rebuilt cache
reproduces the same governance.

- **Commit the artifact** (`docs/ai/state/governance.json` by default) so
  teammates share findings/sessions/backlog and so the knowledge survives a
  deleted cache or an ephemeral devbox.
- Writes are atomic (temp file + rename) and rows are emitted in a stable order,
  so re-serializing an unchanged graph produces an identical file.
- A missing artifact is a clean no-op; a corrupt artifact is logged and skipped
  so indexing still completes.

Because the artifact is rewritten as a whole snapshot, concurrent edits by
multiple users can produce git merge conflicts on this file; resolve them like
any other JSON conflict and re-run `scaffold index`.

---

## freshness

Controls optional async graph freshness behavior for MCP tool calls.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| async_enabled | bool | true | Enable cheap request-path freshness checks and background refresh scheduling |
| debounce_seconds | int | 120 | Minimum interval between refresh trigger attempts |
| gate_strict | bool | false | Defer gate-transition calls when freshness is stale/unknown/refreshing |
| background_queue_enabled | bool | true | Coalesce in-flight refresh triggers by setting a pending rerun |

When enabled, MCP request handlers avoid synchronous re-indexing. They return freshness
metadata and schedule eligible refreshes asynchronously.

---

## Retrieval and Search

`scaffold graph search` and the MCP `scaffold_search` tool support three retrieval modes:

| Mode | What it does | Requires |
|------|--------------|----------|
| keyword | Structural term-overlap match on names/paths/signatures (custom, not BM25) | nothing beyond the graph |
| semantic | Vector cosine similarity against code embeddings | `agentscaffold[search]` + embeddings indexed (`scaffold index --embeddings`) |
| hybrid | Keyword + semantic merged via reciprocal rank fusion (default) | best with both; falls back to keyword |

Retrieval can degrade gracefully. A capability oracle reports one of three statuses, surfaced
in MCP responses under `meta` (`retrieval_status`, `retrieval_effective_mode`,
`retrieval_requested_mode`, `retrieval_reason`) and printed as a warning by the CLI:

| Status | Meaning |
|--------|---------|
| available | Requested mode can run fully |
| degraded | Runs in a reduced form (e.g. `hybrid` with no embeddings, or with the model not yet provisioned, runs keyword-only) |
| unavailable | Cannot run (pure `semantic` requested but `sentence-transformers` is missing or the model weights are not provisioned offline) |

Keyword search is intentionally a lightweight custom term-overlap matcher; the project does
not depend on `rank-bm25`.

### search (embedding model + provisioning)

```yaml
search:
  embedding_model: all-MiniLM-L6-v2   # sentence-transformers model id
  cache_dir: .scaffold/models          # where weights are cached (relative -> project root)
  rerank: false                         # optional cross-encoder rerank (off by default)
  rerank_model: cross-encoder/ms-marco-MiniLM-L-6-v2
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| embedding_model | str | `all-MiniLM-L6-v2` | Model used to embed code/query text |
| cache_dir | str | `.scaffold/models` | Weights cache (passed as the sentence-transformers `cache_folder`). Empty/null uses the default `~/.cache/huggingface`. |
| rerank | bool | `false` | If true, rerank final search results with a sentence-transformers CrossEncoder. Optional and slower; off by default. |
| rerank_model | str | `cross-encoder/ms-marco-MiniLM-L-6-v2` | CrossEncoder model id used when `rerank` is enabled. |

**Why this exists -- the package vs. weights distinction.** Installing
`agentscaffold[search]` provides the *library* (sentence-transformers + torch) but
**not** the model *weights*. By default sentence-transformers downloads the weights
lazily on first index/search, which fails when offline/air-gapped/CI/sandboxed.
Pinning `cache_dir` plus an explicit provisioning step makes the model load
deterministically and offline after one warm. (Forcing the dependency at install
time would not bundle the weights and would bloat every install, so `[search]`
stays optional.)

**Provision once (needs network):**

```bash
scaffold graph warm           # download + cache the configured model
scaffold graph model-status   # package installed? weights cached? cache dir?
```

If the weights are not provisioned and there is no network, semantic/hybrid search
**degrades to keyword-only** with an actionable message rather than failing
mid-query.

Embedding rows record the model that produced them plus a stable hash of the
embedded text. If you change `search.embedding_model`, semantic search refuses to
compare incompatible vectors and tells you to re-index:

```bash
scaffold index --embeddings
```

The text hash also lets embedding generation skip rows whose input text and model
are unchanged, so re-indexing after a small change avoids re-encoding the entire
graph.

### Governance Recall

Search can target code, governance, or both:

```bash
scaffold graph search "have we seen stale plan issues before?" --kind governance
scaffold graph search "router safety" --kind all
scaffold graph search "data provider" --kind code --rerank
```

`--kind governance` searches plans, learnings, review findings, studies, ADRs,
spikes, and backlog items. MCP clients can call `scaffold_recall_governance` for
the same governance-only recall path. Semantic search remains advisory: results
carry provenance and may include stale/resolved governance entries, so agents must
still inspect status/resolution before acting on a hit.

### HNSW Acceleration

When DuckDB's optional `vss` extension is available, AgentScaffold creates a
best-effort HNSW index for `EmbeddingStore`. If `vss` cannot be installed or the
index creation fails offline, exact `list_cosine_similarity` remains the fallback,
so correctness is unchanged and only performance differs.

Embedding text is enriched at index time with each definition's docstring or leading comment
(read from its source slice), not just `name + signature + module`, and vectors are
L2-normalized at store time -- so semantic matches reflect intent rather than identifiers
alone. Re-index (`scaffold index --embeddings`) to regenerate vectors after upgrading.

In a multi-project workspace both halves of search default to the current project; pass
`--project <name>` to target a sibling or `--all-projects` to federate (federated hits carry a
`project` provenance field). `scaffold graph duplicates` surfaces cross-project near-duplicate
definitions to drive shared-library reuse.

---

## How Gates Interact with Lifecycle

```
Draft --[draft_to_review]--> Review --[review_to_ready]--> Ready
  |                              |                            |
  | plan_lint                    | devils_advocate            | review_checklist
  | architecture_layer_check     | expansion_review           | approval_gates
                                 | domain_reviews             | interactive_gate
                                 | spike_for_high_uncertainty |
                                 | interface_contracts        |
                                 | security_review            |

Ready --[ready_to_in_progress]--> In Progress --[in_progress_to_complete]--> Complete
                                        |                                    |
                                        |                                    | all_steps_checked
                                        |                                    | validation_commands
                                        |                                    | tests_pass
                                        |                                    | retrospective
                                        |                                    | domain_implementation_review
```

Disabling a gate skips that requirement. For example, `devils_advocate: false` allows a plan to move from Review to Ready without running the devil's advocate prompt.
