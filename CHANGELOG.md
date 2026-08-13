# Changelog

All notable changes to AgentScaffold are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to semantic versioning (pre-1.0: minor versions may
introduce additive features and small behavior changes).

## [Unreleased]

## [0.10.6] - 2026-08-13

**Upgrade note (multi-workspace installs only).** A tool call that omits both
`working_path` and `project`, made against a server whose launch directory
contains several registered projects, now refuses with `ambiguous_project` where
it previously answered. The previous answer came from a project that does not
exist in your registry, so it was describing a different codebase than the one
you asked about. Pass `working_path` (the file or directory you are working on)
or `project=<name>`; `scaffold_projects` lists what the server can answer for.
Single-workspace installs are unaffected. Breaking contract change behind
ADR-026.

### Fixed
- **A no-argument MCP call can no longer be answered from the wrong project.**
  With several workspaces registered, a call carrying no `working_path` was
  answered from a project synthesised out of the launch directory's basename:
  well-formed, plausible, and about somebody else's code. One field report saw
  942 files and 0 plans returned for a project holding 274 files and 23 plans.
  Two things composed into it -- a one-level-deep glob that could only ever find
  a shallow workspace, so "exactly one match" reflected directory layout rather
  than intent, and a marker check that accepted any directory holding a
  `scaffold.yaml` or `.git`, including a home directory with a dotfiles repo. A
  directory with registered project roots beneath it is now treated as a place
  that *contains* projects rather than being one, and the glob stands down once
  the registry has something better to say.
- **A relative `working_path` now resolves against your registered roots.** It
  was joined onto the server's own launch directory, which is a launch artefact
  unrelated to your workspace, so `src/main.py` matched nothing and the call
  quietly fell back to the anchor. A relative path is accepted when exactly one
  registered root explains it, and left unmatched when several do.
- **A synthesised project uses the name its `workspace.yaml` declares.** Falling
  back to the directory basename let resolution succeed while every scoped read
  filtered on a name no row had been written under: results were empty and
  nothing said why.
- **Refusals name commands that exist.** `ambiguous_project` and
  `unknown_project` pointed at `scaffold workspace list`, which reports the
  current workspace manifest rather than the registry the candidates come from;
  a registry error pointed at `scaffold workspace register`, which is not a
  command. They now name `scaffold project list` and `scaffold_projects`.

### Added
- **Responses say which project answered and why.** Tool `meta` now carries
  `project`, `project_root`, `resolution_source` and `project_registered`, plus
  `working_path_unmatched` when a supplied path resolved to no project and was
  therefore ignored. Previously only `scaffold_projects` disclosed any of this,
  which is why a mis-scoped answer was indistinguishable from a correct one.
- **`ambiguous_project` carries `retry_with`**, naming the arguments that would
  make the same call succeed.
- **Package docs match the refusal.** `docs/multi-project.md`,
  `docs/platform-integration.md`, `docs/cli-reference.md`, `docs/user-guide.md`
  and the README now say that a no-argument call with several workspaces
  registered is refused, and that `--workspace` in a shared `mcp.json` is a
  single-workspace option only.

## [0.10.5] - 2026-08-13

**Upgrade note.** Restart the MCP server after upgrading. Writable opens apply
any missing additive columns (including `BacklogItem.resolution` from 0.10.4)
automatically; no re-index or hand ALTER is required. Schema version stays 10.

### Fixed
- **Opening a graph now applies additive columns that `init_schema` used to own.**
  0.10.4 added `BacklogItem.resolution` only inside `init_schema`, so MCP writes
  against a pre-0.10.4 graph raised `BinderException: Referenced update column
  resolution not found in table!`. Writable opens now reconcile
  `ADDITIVE_COLUMNS`; `scaffold doctor` reports a graph that is still behind
  without writing anything. No rebuild; schema version stays 10.

## [0.10.4] - 2026-08-12

**Upgrade note (superseded by 0.10.5).** 0.10.5 applies the missing
`BacklogItem.resolution` column on writable open. On 0.10.4 alone, re-index
(`scaffold index`) or run
`ALTER TABLE BacklogItem ADD COLUMN IF NOT EXISTS resolution VARCHAR DEFAULT ''`
on `.scaffold/graph.duckdb`. No graph rebuild is required.

### Fixed
- **Resolve tools no longer report success for writes that did not happen.**
  `scaffold_resolve_backlog_item` and `scaffold_resolve_finding` used to echo
  `archived` / `resolved` after a zero-row `UPDATE`, and backlog `resolution`
  notes were accepted then discarded (`BacklogItem` had no column). A miss now
  returns `status: not_found` with `error_code: not_found`. Backlog resolution
  notes are stored. Human IDs like `DQ-043` archive a uniquely matching title;
  ambiguous prefixes refuse rather than guess.

## [0.10.3] - 2026-08-07

### Fixed
- **Abandoned graph write locks no longer block every writer for ten minutes.**
  When a holder dies without cleaning up `.scaffold/graph.write.lock/`, waiters
  (MCP writes at 8s, index at 30s) used to fail with `graph_locked` while the
  reaper waited for a 600s mtime gate. The reaper now clears the lock immediately
  when `owner.json` records a dead pid, keeps the mtime fallback for missing
  metadata / unknown liveness, and releases the directory if owner metadata
  cannot be written after acquire. Timeout and `GraphLockError` messages name the
  lock path and stop claiming a writer is "still running" when clearing may be
  what is needed.

## [0.10.2] - 2026-08-07

Fixes a regression, reported from the field, in which the last step of the documented
0.10 upgrade undid the first one.

**Upgrade note.** If you already ran `scaffold agents generate-all` after migrating,
check for a `.cursor/mcp.json` in your project roots and delete any that contain an
`agentscaffold` entry. `scaffold doctor` now finds them for you. They are not removed
automatically because these files are per-repo and often committed, so deleting one on
your behalf could travel into a colleague's checkout through version control.

### Fixed
- **`scaffold agents generate-all` recreated the per-project MCP config that
  `scaffold mcp install --migrate` exists to retire.** Running the two commands in the
  documented order left you back where you started, and the README recommends
  `generate-all` right after `index` — the closing step of the upgrade sequence. Two
  plans had drifted apart: one taught the generator to write a per-project config pinning
  the resolution anchor, and 0.10 replaced per-project servers with a single shared one
  without retiring that writer. The contradiction was already sitting in the source,
  where `mcp/install.py` classifies the very same file as a deprecated registration and
  asks you to delete it.

  The generator now skips the per-project config when a shared server already covers the
  repo — when the root is registered, or when the canonical entry is installed. A lone
  repo with neither still gets the file, so `scaffold init` continues to work with no
  further setup.

- **`generate-all --dry-run` wrote `.cursor/mcp.json` for real.** The writer took no
  dry-run argument, so the caller had nothing to pass and the guard was bypassed rather
  than mislabelled. It also ran its own `mkdir`, so a dry run created `.cursor/` as well.
  Both now touch nothing. `scaffold init --dry-run` was never affected.

- **`scaffold doctor` could not see a stray per-project config** and reported the
  migration as clean while one sat on disk, making the regression invisible to the
  command meant to verify it. It now scans registered roots, and flags a per-project
  config only when a shared server exists to make it redundant — a lone repo whose
  per-project config is its only registration is not misconfigured.

  The one existing warning about these files was emitted through the logger from inside
  the MCP server process, where no human reads it.

## [0.10.1] - 2026-08-07

A documentation-accuracy release. Nothing here requires action on upgrade.

The README on PyPI described a system a version behind in the places that matter most
to a new user, and correcting it turned up one live defect — the reviewer hint below,
which had been silently dead since the Cursor rules file was renamed.

### Fixed
- **The Cursor routing-policy reviewer hint never fired.** `scaffold_prepare_review`
  looks for `.cursor/rules/agentscaffold.md` and adds it to the reviewer hints. Cursor
  only loads `.mdc` rule files, so the generator writes that extension and deletes any
  stale `.md` beside it — meaning the file being looked for is one no current project
  has. The lookup now prefers `.mdc` and falls back to `.md` for projects that have not
  regenerated since the rename.

  The existing test passed throughout, because it created the `.md` file itself and
  asserted on the world the code expected rather than the one the generator produces.

### Documentation
- Corrected `.cursor/rules/agentscaffold.md` to `.mdc` across the README, getting
  started, platform integration, and user guide, plus the source docstrings. Every one
  named a file that is removed on each run.
- Fixed two README commands that did not exist: `scaffold retro check` and `scaffold ci
  setup` are `scaffold retro` and `scaffold ci`.
- The README documents all 31 MCP tools (13 were missing, including the
  `scaffold_begin_plan` / `scaffold_complete_plan` lifecycle pair), the 0.10.0 setup
  path (`scaffold mcp install`, `scaffold project register`, `scaffold doctor`,
  `scaffold gc`), where the graph actually lives now, and what skills are.

## [0.10.0] - 2026-08-07

**One MCP server for a whole workspace, and a graph that sees your relative imports.**

The headline is Plan 249: AgentScaffold no longer needs one MCP server process per
project. A single project-aware server resolves which project each call belongs to from
the path you are working on, which is what makes monorepos and multi-repo workspaces
practical. Alongside it, generated guidance and mutable state stop being copied into
every project root.

Phases A and B ship together deliberately. Phase A alone would have delivered a breaking
change to MCP registration plus a state migration with no tool to tell you whether the
migration worked. That tool is ``scaffold doctor``, and it lands in Phase B. Releasing a
migration a version ahead of its diagnostic would create exactly the kind of invisible
failure this work exists to remove.

Because Phase A changed how *every* tool resolves the project it answers from, the
release was gated on a per-tool conformance sweep rather than on the unit suite alone.
That sweep (Phase F) is what produced most of the fixes below, including two defects it
found in the graph itself.

Also included: the finding-extraction fix from Plan 250, the relative-import fix from
Plan 252, and the parts of Plan 251 that were completed early because the conformance
work depended on them — the ``layers`` check and the scoping conformance suite.

**Two things to know before upgrading.** Your graph rebuilds on the first ``scaffold
index`` (see *Fixed*, relative imports). And if you have been running one MCP server per
project, see *Changed* for the migration — old registrations keep working behind a
deprecation notice rather than breaking.

### Added
- **``scaffold doctor``** (Plan 249 Phase B) diagnoses an installation: registered roots
  that no longer exist, a workspace recorded under two different ids, generated rule
  files that have drifted from their canonical source, legacy or interpreter-pinned MCP
  entries, version skew between the MCP server and your CLI, and where the graph
  actually resolves. It only reads — it never repairs — so it is safe to run on a setup
  you already believe is broken. The default exits 0 whatever it finds, so it is safe in
  a shell profile or a hook; ``--strict`` exits non-zero and is the CI gate.
- **``scaffold doctor --tools``** calls every MCP tool once and reports how each behaved,
  answering the question the configuration checks cannot: whether the tools work in your
  installation right now. A graph held by another process reports as ``busy`` rather than
  as a failure, because an index running in the next terminal is routine and a diagnostic
  that cries wolf during it stops being read. Write tools are skipped by default;
  ``--include-writes`` exercises them against a temporary throwaway project with its own
  database, so the command cannot leave findings or backlog items in your governance
  record either way. A database predating the current schema reports once as "graph schema
  is out of date" rather than as a dozen broken tools.
- **``scaffold_validate`` with ``check="layers"``** now works. It was advertised in the
  tool schema and returned "not yet implemented" when called. It enforces the layering
  rule your ``AGENTS.md`` states — a component consumes the layer directly below it and
  does not bypass intermediate ones — reporting both shapes that break it: an
  **inversion**, where a lower layer imports a higher one, and a **skip**, which reaches
  past an intermediate layer.

  It has a third answer besides pass and fail. The check needs layer definitions from
  ``system_architecture.md`` and code files matching their path patterns in the *same*
  graph, and plenty of repositories have one without the other — an architecture document
  governing a codebase that lives elsewhere, for instance. In that case it returns
  ``not_evaluable`` with a reason and a remediation, rather than an empty violation list.
  "No violations found" from a graph containing no layered files would be a claim about
  nothing while reading as a clean bill of health, which for a drift-detection check is
  the most convincing way it could mislead you. Treat ``not_evaluable`` as unknown, never
  as fine.
- **``scaffold graph prune --malformed-findings``** removes findings created by the
  extraction defect described below. Removal covers both the graph and the
  ``governance.json`` artifact that re-indexing restores from — purging only the graph
  would let the next index bring them straight back. Dry run by default, like the rest of
  ``prune``; a clean project reports nothing to remove.
- **The version-skew check** compares what each MCP entry actually launches against the
  running CLI. An entry naming an absolute interpreter keeps launching whatever is left
  at that path after a virtualenv rebuild; the server still starts, just with an old
  AgentScaffold, and nothing says so. It reads the console script's shebang and asks that
  interpreter directly, so it works against installs too old to answer ``--version``.
- **``scaffold gc``** reclaims state directories for workspaces that are gone and
  registry entries pointing at missing roots. It reports only; ``--apply`` is required to
  delete. It removes only what it can *prove* is orphaned, from a record each state
  directory keeps of the root it was created for — a workspace absent from the registry
  is **not** treated as an orphan, because the manifest is the source of truth and its
  graph is live. Directories predating that record are reported and kept.
- **``scaffold --version``**.
- **``scaffold workspace migrate-state``** moves an existing graph out of the working
  tree, with copy-verify-remove semantics and ``--restore`` to go back. Dry run is the
  default. It refuses while any process holds the database, so a live MCP server cannot
  have a file moved out from under it.
- **``scaffold init --dry-run``** reports what init would write without writing it.
- **Canonical routing guidance.** A workspace using the shared asset layout gets one
  committed source of routing policy at its root, and each project's generated rule files
  carry a copy stamped with its content hash. The policy stays inline rather than being
  replaced by a pointer — an agent has to act on the rules without a tool call to fetch
  them — and the stamp is what makes the duplication safe, since a copy that has fallen
  behind becomes detectable rather than merely different. Also served as the
  ``agentscaffold://guidance/routing`` MCP resource. Single-project repositories are
  unaffected and emit byte-identical output to 0.9.x.
- **One project-aware MCP server** (Plan 249 Phase A). A single MCP entry now serves
  every registered project, replacing one server per repository. New user-level registry
  at ``~/.agentscaffold/registry.yaml`` (or ``$AGENTSCAFFOLD_HOME``), maintained with
  ``scaffold project register/unregister/list``.
- ``scaffold mcp install [--migrate] [--dry-run] [--config <path>]`` writes exactly one
  entry: ``{"command": "scaffold", "args": ["mcp"]}``. No ``cd`` binding, no launcher
  hook, no hardcoded interpreter path, so it survives a virtualenv rebuild and resolves
  ``scaffold.exe`` through ``PATH`` on Windows. Unrelated entries in a shared
  ``mcp.json`` are verified unchanged before anything is written, and an unparseable
  config is refused rather than guessed at.
- ``scaffold_projects`` MCP tool enumerates registered projects and reports which one a
  call resolved to and why. It is the recovery path from an ``ambiguous_project``
  refusal.
- Opt-in federated discovery: ``all_projects=true`` extends from ``scaffold_search`` to
  the governance discovery tools, with ``project`` provenance on every hit.
- ``--restrict-to`` limits a server instance to an explicit allowlist of projects.

### Changed
- **The graph now lives outside your working tree — for registered projects only.**
  A registered workspace resolves to
  ``~/.local/state/agentscaffold/<workspace-id>/graph.duckdb`` (honouring
  ``$XDG_STATE_HOME``; ``%LOCALAPPDATA%\agentscaffold\State`` on native Windows),
  created readable and writable by you alone. An unregistered repository is unchanged
  and keeps ``<repo>/.scaffold/graph.duckdb``. ``AGENTSCAFFOLD_DB_PATH`` and an explicit
  ``graph.db_path`` still take precedence, in that order.
- **Upgrading does not move your graph.** An existing in-tree database keeps winning over
  an empty state directory, because flipping a default is not a migration: doing so
  would point resolution at nothing, silently re-index from scratch, and leave your
  populated database orphaned in the tree. Move it deliberately with
  ``scaffold workspace migrate-state --apply``.
- ``scaffold init`` inside a workspace now joins it — registering the project in both the
  manifest and the registry under one shared id — instead of cloning the workspace's
  shared assets into the project. Re-running it reports "no changes" and writes zero
  bytes.
- **Breaking: an unscopeable tool call is now refused, not federated.** A call that
  cannot be narrowed to exactly one project returns a structured ``ambiguous_project``
  error naming the candidates and the remediation, instead of quietly searching
  everything. Silently answering from the wrong project is worse than an actionable
  error.
- Tool calls scope per call through a context variable rather than by ``os.chdir``, so
  two projects can be active at once and the graph handle pool is actually reachable.
- Embedding weights resolve to one user-level cache (``~/.cache/agentscaffold/models``,
  honouring ``XDG_CACHE_HOME``) instead of one copy per repository. Measured at 87 MB
  per project across four projects on one machine. Repositories with an already-warm
  local cache keep using it, so existing installs do not re-download.
- Registry roots are compared as paths rather than strings, and matching is
  path-flavour correct: case-insensitive for Windows and UNC roots, case-sensitive for
  POSIX and WSL ``/mnt/<drive>`` roots. Windows and WSL roots do not cross-match, since
  the two have separate registries and ``/mnt`` mappings cannot be known from here.

### Deprecated
- **Per-project MCP entries.** They keep working. The server names them once at startup
  along with the command that collapses them. Entries in your shared ``mcp.json`` are
  removed by ``scaffold mcp install --migrate``, which backs the file up first;
  per-repository ``.cursor/mcp.json`` files are reported but never edited
  automatically, because they are often committed and a deletion could reach another
  checkout.

### Fixed
- **Finding extraction matched ``[CATEGORY]`` tokens anywhere in a line** (Plan 250),
  instead of only at the start where a real finding marker sits. Ordinary prose that
  happened to mention one produced a garbled finding with truncated text — including,
  with some irony, the plan documents that described the bug, which regenerated the bad
  rows on every re-index. The pattern is now anchored to the line start and a write-time
  guard rejects malformed text before it reaches the graph. Existing bad rows are not
  removed automatically; see ``scaffold graph prune --malformed-findings`` above.
- **Relative Python imports produced no ``IMPORTS`` edge** (Plan 252), so ``scaffold
  impact`` under-reported blast radius on any package that uses them — 22.8% of ``from``
  statements across 88 real packages, with 75 of the 88 affected. ``from .core import x``
  built a candidate path with a doubled separator (``src/pkg//core.py``); ``is_file()``
  normalised that and returned true, so the resolver reported success and returned a
  string the file map could never match, and the import was filed unresolved. Relative
  imports now resolve by counting the leading dots — one dot is the importing file's own
  package, each further dot ascends a level — within that package only. A relative import
  naming a module that is not there stays unresolved rather than matching a same-named
  file elsewhere in the tree.

  AgentScaffold's own source contains no relative imports at all, which is why indexing
  itself constantly never revealed this.

  **Existing graphs are affected and heal automatically.** A graph built before this fix
  is structurally valid and quietly missing edges, which is the worst state for impact
  analysis: an under-reported blast radius is indistinguishable from a small one. The
  graph schema version is bumped from 9 to 10 so those graphs rebuild on the next index,
  preserving findings, sessions and backlog items as any schema rebuild does. No action is
  required beyond running ``scaffold index`` as usual; the first run after upgrading will
  take a full-rebuild's time rather than an incremental one.
- A workspace could end up recorded under two different ids: ``scaffold workspace
  onboard`` generated one into ``workspace.yaml`` while registration independently minted
  another for the registry. Resolution prefers the manifest, so the graph kept working
  while the registry reported an id that keyed nothing — and removing the manifest would
  have re-keyed state and orphaned a populated graph. An id that already exists in either
  place is now adopted rather than regenerated.
- ``scaffold workspace migrate-state`` left the freshness watermark and governance
  fingerprint behind, so a freshly migrated graph looked stale and re-indexed on first
  use — the exact failure the sidecar handling existed to prevent. It carried a list of
  two filenames (``freshness.json``, ``graph_meta.json``) that nothing in the codebase
  has ever written, and the test seeded those same invented names, so both agreed with
  each other and neither matched the disk. The filenames now come from one shared
  constant that the writers and the migration both import.
- ``mcp/freshness.py`` resolved the database path itself instead of going through the
  shared resolver, so freshness could be tracked against a different file than the graph
  was read from.
- Registry writes are serialised by a lock spanning the whole read-modify-write cycle.
  Atomic writes (added earlier in this phase) ruled out torn reads but not lost updates:
  registering is read-modify-write, and two interleaved cycles could discard one
  workspace while leaving a well-formed file.
- ``scaffold workspace onboard`` now mirrors its manifest into the user-level registry,
  so the existing onboarding path does not need a second registration step.

## [0.9.6] - 2026-07-15

### Fixed
- MCP ``detail=summary`` trim (Plan 248): ``apply_detail`` no longer raises
  ``AttributeError: 'int' object has no attribute 'endswith'`` when a review payload
  contains an evidence dict keyed by non-string values (e.g. the ``similar_plans``
  gap evidence keyed by plan number). This crashed ``scaffold_begin_plan`` for any
  plan whose review produced a ``SIMILAR_PATTERN`` gap, since begin-plan always runs
  ``prepare_review`` through the default summary trim. Non-string keys are now
  preserved and recursed into; string-key markdown-stripping and list caps are
  unchanged, and ``detail=full`` was never affected.

## [0.9.5] - 2026-07-14

### Added
- Workspace shared asset layout (Plan 234): a first-class ``asset_layout`` policy
  in ``workspace.yaml``. ``layout: shared_workspace`` promotes reusable *process*
  assets (prompts, standards, templates, collaboration protocol, commands, shared
  security templates) to a single committed copy at the workspace root while each
  registered project keeps its own system of record (plans, ADRs, contracts,
  spikes, state, backlog, architecture, vision). The default remains
  ``project_local`` (fully backward compatible; a workspace with no
  ``asset_layout`` block is unchanged).
- MCP resolution anchor (Plan 234): ``scaffold mcp --workspace <root> --project
  <name>`` and the ``AGENTSCAFFOLD_WORKSPACE_ROOT`` / ``AGENTSCAFFOLD_PROJECT``
  environment variables pin the project resolution anchor so no-argument tools
  (``scaffold_orient``, staleness validate) resolve the intended project even when
  the IDE opens a parent folder. Generated ``.cursor/mcp.json`` emits the
  ``--workspace`` / ``--project`` args in a multi-project workspace.
- Stub-first agent files (Plan 234): under ``shared_workspace`` the project
  ``AGENTS.md`` is a thin pointer to shared process assets, and a thin
  workspace-root router ``AGENTS.md`` is generated. Managed ``.gitignore`` block
  now also ignores personal overlays (``AGENTS.local.md``,
  ``.cursor/rules/local.*.mdc``) without untracking team files.
- ``scaffold workspace migrate-layout`` (Plan 234): brownfield migrator with
  ``--dry-run`` (default) / ``--apply`` / ``--prefer-project`` / ``--keep-diverged``
  / ``--force`` / ``--json``. Promotes identical/unique process assets, requires an
  explicit policy for diverged copies, never moves project system-of-record files,
  refuses a dirty worktree without ``--force``, and is idempotent. ``scaffold
  workspace onboard --shared-layout`` writes the ``asset_layout`` block directly.

## [0.9.4] - 2026-07-12

### Added
- MCP call-compression hardening (Plan 247): empty ``scaffold_search`` /
  ``scaffold_impact`` / missing-symbol ``scaffold_context`` responses inline
  ``why_empty`` + bounded ``grep_fallback``; ``scaffold_orient`` embeds
  ``recommended_actions``, ``plan_progress``, and ``next_action_focus``;
  compare/staleness expose ``lead_shared_files`` / ``lead_overlap`` with
  frequency demotion for ubiquitous paths; ``diff_plan_vs_code`` returns
  ``next_unchecked_step`` and symbol spot-checks. Checkbox counts are scoped
  to the Execution Steps section only. Shared agent rule policy (Cursor,
  Claude, Windsurf, prompt) teaches call-compression: prefer fused fields
  over redundant ``why_empty`` / ``grep_graph`` / ``next_action`` hops;
  mid-impl progress routes to ``scaffold_diff_plan_vs_code``. Eval harness
  covers the new tools, fused empty-result fields, adoption intents, and a
  call-compression efficiency scenario; README efficiency figures refreshed
  from ``eval/reports/latest.md`` (120 scenarios).
- Agent MCP tool pack (Plan 246): ``scaffold_diff_plan_vs_code``,
  ``scaffold_grep_graph``, ``scaffold_why_empty``, ``scaffold_next_action``;
  embedded ``plan_card`` (no full plan dump); ``dry_run`` on begin/complete;
  ``detail=summary|full`` on heavy read composites; fail-loud required-arg
  validation (e.g. empty ``scaffold_impact`` target).

### Fixed
- MCP read tools no longer block ~20s+ on the exclusive graph write lock while
  an in-process incremental refresh runs (Plan 244). ``open_graph(read_only=True)``
  skips the AgentScaffold writer wait; same-process DuckDB concurrent readers
  succeed and set ``meta.read_during_refresh`` / ``freshness_status=refreshing``.
  Cross-process DuckDB file locks still soft-fail quickly with
  ``refresh_in_progress`` rather than the old multi-retry hard wait. Write tools
  keep exclusive lock semantics.
- Staleness / compare / prior-experiment overlap signals ignore ubiquitous
  governance docs by default (Plan 245): ``docs/ai/contracts/README.md``,
  ``workflow_state.md``, ``backlog.md``, and ``architectural_design_changelog.md``.
  Meaningful code/config overlaps still drive ``is_stale`` and ``conflict_risk``;
  filtered noise is reported via ``overlap_noise_filtered*``. Override with
  ``graph.overlap_noise_paths`` in ``scaffold.yaml``.
- Keyword / hybrid code search no longer misses symbols outside a blind
  ``LIMIT`` window (Plan 243). ``_keyword_search`` filters candidates with
  SQL ``contains(lower(...), term)`` before capping rows, then keeps Python
  scoring. Fixes empty ``scaffold_search`` results for names like
  ``normalize_feeds`` on large graphs when embeddings are absent.

## [0.9.3] - 2026-07-11

### Fixed
- MCP stdio transport no longer breaks when async freshness or embedding refresh
  runs an in-process incremental index (Plan 242). Rich progress / Index Summary
  output is suppressed via `index(..., quiet=True)` in background workers, and
  MCP server startup installs a quiet pipeline console so stdout stays JSON-RPC
  only. Symptom was Cursor logging `Unexpected token 'I', "Incrementa"... is not
  valid JSON` followed by `Not connected` on tools like `scaffold_orient`.

## [0.9.2] - 2026-07-10

### Added
- Auto `.gitignore` managed block in the install sequence (Plan 241). `scaffold
  init` and `scaffold agents generate-all` now ensure the project `.gitignore`
  contains an AgentScaffold-managed section that ignores the runtime artifacts
  the package writes into a consumer repo (`.scaffold/` -- graph DB, model cache,
  hook logs, index lock/stamp, schema-migration exports -- plus the
  `.venv-scaffold/` dedicated-venv convention and `*.duckdb`/`*.duckdb.wal`
  globs). The writer uses `#`-comment markers and is never destructive: it
  creates the file if absent, refreshes only the region between its markers, or
  appends the block to a pre-existing `.gitignore` without touching any user
  lines (there is deliberately no wholesale-replace path, even under `--force`).
  These entries were previously hand-added by consumers; they now ship for every
  generated project.
- Generic governance controls in the generated `AGENTS.md` template (Plan 240).
  The shipped `agents/agents_md.md.j2` now documents the Two-Phase Governed
  Lifecycle (begin-plan/complete-plan agent action checklists, the
  `freshness.gate_strict` strict-mode deferral, and the "tools own graph state;
  agent owns file state" boundary), an Architecture Changelog Scope section
  (durable architecture changes only), Session Handoff Hygiene, an
  immediate-fix-vs-backlog decision rule, and a Study Artifact Naming convention.
  A parity one-line changelog-scope prohibition is added to the Cursor rules
  summary. These were previously hand-added by consumers; they now ship for every
  generated project.

### Fixed
- Query escaping, search provenance, and coverage honesty (Plan 239). SQL string
  literals are now escaped consistently and correctly for DuckDB via a single
  `sql_escape` helper (quotes are doubled; backslashes are left literal), fixing a
  latent bug where identifiers containing an apostrophe (file paths, study
  outcomes, spike titles, session summaries, contract symbol names) could break a
  query or slip past the ad-hoc backslash escaping used in most of the review
  query layer. Federated `scaffold_search` now reports project provenance:
  `SearchResult` carries a `project` field and `format_search_results` shows a
  Project column for multi-project results (single-project output is unchanged).
  The plan/governance read tools are more honest about an empty graph:
  `scaffold_orient`, `scaffold_compare_plans`, `scaffold_staleness_check`, and
  `scaffold_decision_context` attach a `graph_warning` when the graph has 0 files
  and 0 plans so a confident negative (`is_stale: false`,
  `has_full_decision_chain: false`) is not mistaken for a confirmed absence, and
  `compare_plans` labels `conflict_risk` with its heuristic basis.
- Graph-tool rendering and signal hygiene (Plan 238). `scaffold_staleness_check`
  and the rewrite context no longer miss completed plans whose status carries a
  trailing date or note (e.g. `COMPLETE (2026-07-09)`); completed detection now
  uses tolerant status normalization. `scaffold_orient` no longer lists an ADR
  with a descriptive status like `Superseded by ADR-030` as active. The
  plan/governance composites (`orient`, `prepare_review`, `decision_context`,
  `prior_experiments`, `find_studies`, `find_adrs`) now strip internal
  `alias.field` query-column prefixes from agent-facing output, matching
  `search`/`context`/`impact`, and tools that echo plan status expose a
  normalized value alongside the raw string.

### Added
- Architecture-layer and contract-to-file graph ingestion (Plan 237). The
  `system_architecture.md` baseline is now parsed into `ArchitectureLayer` nodes
  and each source file is linked to its most-specific layer via `BELONGS_TO_LAYER`
  (matching the machine-readable path globs in the doc's Components tables). This
  activates the previously-inert LAYER challenge, INTEGRATION_POINTS gap, and the
  brief's `layer_coverage` signal for repos whose graph contains both the
  architecture doc and the source tree. Contracts additionally gain a direct
  `CONTRACT_ABOUT_FILE` edge (derived from the files declaring their functions and
  classes), and `get_contracts_for_file` resolves via that edge with a fallback to
  the declares-join. Governance freshness now also watches
  `docs/ai/system_architecture.md`.

### Changed
- Pre-review signal quality (Plan 236). `scaffold_begin_plan` now persists only
  high-value findings (high severity, de-duplicated against already-open
  findings) instead of writing every generated challenge and gap, so repeated
  reviews no longer flood the finding graph. The full challenge/gap lists remain
  in the returned payload.
- Modification-frequency ("architectural instability") challenges and the brief
  frequency signal, plus missing-test-coverage gaps, now apply only to parsed
  source files. Append-only governance/docs artifacts (workflow_state, contract
  registries, studies, runbooks) are no longer flagged as unstable or untested.
- `LEARNING` challenges are capped and ranked per file (unincorporated first,
  then most recent) with an explicit disclosure that linkage is by plan
  co-occurrence, not semantic relevance.
- The compact orient summary in `scaffold_begin_plan` now reports methods,
  classes, and import/call edge counts (not just top-level functions), and the
  brief surfaces `layer_coverage`/`contract_link_count` so absent layer and
  contract data reads as unconfirmed rather than a clean result.
- Prior-plan status is normalized to a known vocabulary and a trailing
  `(YYYY-MM-DD)` date is recovered from status text in review briefs.

## [0.9.1] - 2026-07-08

### Fixed
- Added shared graph write coordination across indexing, MCP graph opens, and
  runtime governance writes. `scaffold_begin_plan`, `scaffold_complete_plan`,
  and other MCP graph-backed paths now retry transient DuckDB lock contention
  before returning `graph_locked`, while generated Cursor edit hooks defer their
  background incremental index when lifecycle/governance writes are active.
- Governance freshness now watches `docs/ai/backlog.md`,
  `docs/ai/backlog_archive.md`, and `docs/ai/state/governance.json`, preventing
  backlog/governance artifact edits from staying invisible to graph-backed
  orientation and review tools.

## [0.9.0] - 2026-06-23

Multi-project workspace hardening discovered while running AgentScaffold against
real multi-project workspaces. Five related fixes; all preserve single-project
behavior (scoping is a no-op there, and `project=None` reproduces prior IDs and
queries byte-for-byte).

### Added
- MCP tools accept an optional `working_path` argument (advertised on every
  object-schema tool). In a multi-project workspace the server resolves the
  owning project root from that path and scopes the call to it, so reads follow
  the file the agent is editing even though the editor launches the MCP server
  from one fixed directory. Empty/unresolvable `working_path` keeps the default
  root; explicit `project` / `all_projects` still take precedence.
- `_route_root_for_working_path` resolves a project root from an absolute or
  workspace-relative path; `_dispatch_tool` chdir's into it per call so all
  cwd-derived project scoping retargets without per-tool changes.

### Fixed
- MCP: a federated fail-open default. When the effective root is not a
  registered project and the caller did not scope explicitly, the call now
  federates across all projects instead of raising `ScopingError`.
- MCP: accurate `retrieval_status` for cold tools (e.g. `scaffold_stats`). The
  embedding weights cache is now pinned from config in `_dispatch_tool` before
  the retrieval-status probe, so cold tools no longer report `degraded` while
  semantic search actually works.
- Findings: review findings are now project-scoped. `_finding_id` folds the
  owning project into its hash key (plan numbers are not unique across
  projects), `record_finding` / `record_findings_batch` stamp the `project`
  column and scope `File` lookups, and `resolve_finding` / `get_open_findings`
  accept a `project` filter. MCP finding handlers and `scaffold_prepare_review`
  resolve the active project via `_current_project_or_none()`.
- Backlog: same class of fix on the backlog path. `_backlog_id` folds the
  project into its hash key; `record_backlog_item` / `record_backlog_items_batch`
  stamp the `project` column and scope the `Plan` lookup; `resolve_backlog_item`,
  `get_open_backlog_items`, and `get_backlog_items_for_plan` (in both
  `graph/backlog` and the `review/queries` wrappers) accept `project`. The
  orient open-backlog count is project-scoped to match the list.
- Agent rule delivery: the generated Cursor routing rule is now written as
  `.cursor/rules/agentscaffold.mdc` with `alwaysApply: true` (Cursor only loads
  `.mdc` rules), per-reviewer rules are written as `<reviewer>.mdc`, and stale
  `.md` files from older generations are removed. The `AGENTS.md` template gains
  "AgentScaffold MCP Tools" and "Multi-Project Workspace Discipline" sections so
  the `working_path` discipline reaches every agent platform.

### Migration
- Code stamps `project` only on new writes. Graphs that already hold findings or
  backlog items written before this release will have rows with an empty
  `project` column; backfill them per project (regenerate the project-scoped ID,
  rewire the `BACKLOG_ITEM_OF` edges, then re-sync governance write-through) or
  rebuild with `scaffold index`. Existing projects should re-run
  `scaffold agents` / `scaffold agents cursor` to adopt the `.mdc` rule outputs.

## [0.8.0] - 2026-06-16

### Added (Plan 232 - async embedding lane and resident embedder)
- Added `graph.async_embeddings` (`off | idle | interval | commit`, default
  `off`) so projects can opt into background embedding refresh without changing
  historical behavior. With `off`, AgentScaffold schedules nothing and never
  loads the embedding model.
- MCP responses now include async embedding lane state and can schedule a
  single-flight background embedding refresh when retrieval is degraded (for
  example, no embeddings are indexed) and the structural index lock is idle.
- The embedding scheduler reuses the existing process-level model cache, making
  the resident model lazy and opt-in, and honors
  `graph.embedding_min_interval_seconds` for debounce.
- Generated git `post-commit` and `post-merge` hooks can request a non-blocking
  `scaffold index --incremental --embeddings` reconcile for the `commit` policy.
- Incremental `--embeddings` can now reconcile missing embeddings even when
  there are no structural changes, while changed-file runs remain scoped to the
  affected neighborhood.
- Tightened the scoped Plan 232 validation target by typing legacy MCP
  decorator/helper signatures and isolating the governance migration test from
  the repo-level governance artifact; the package suite is back to all-green.
- Live benchmark execution now validates the expected mini-swe-agent Docker API
  before constructing a live environment, so unsupported mini-swe-agent releases
  fail closed instead of starting a container and then crashing on a missing
  method.

### Changed (Plan 231 - incremental indexer scoping and hook debounce)
- `scaffold index --incremental` now keeps per-edit work proportional to the
  changed-file neighborhood: unchanged files use an `(mtime, size)` metadata
  prefilter before hashing; empty changesets exit as explicit no-ops; import and
  call re-resolution are scoped to changed files plus direct importers; config
  references refresh only for changed configs or configs that referenced refreshed
  code; and community detection is skipped on content-only edits by default.
- Incremental `--embeddings` runs now pass the changed-file scope into
  `generate_embeddings`, preserving the existing content-hash skip while avoiding
  per-node existence checks across the whole store.
- Generated edit hooks remain non-blocking and single-flight, and now honor
  `graph.incremental_min_interval_seconds` as an optional interval guard. Claude
  Code built-in freshness hooks route through the same wrapper script instead of
  launching a blocking raw `scaffold index --incremental` command.
- Generated collaboration protocol docs are richer out of the box: prompting
  patterns, communication patterns, quality checkpoints, future-regret triage,
  escalation triggers, anti-patterns, and human-readable review terminology now
  ship in the package template. Domain review sessions render only when domains
  are configured.

## [0.7.0] - 2026-06-16

Phase 1 foundation chain (Plans 221-223) plus Phase 2 (Plans 224-229):
multi-project / durability groundwork, shared-policy inheritance, namespaced
multi-project workspaces, collaboration ergonomics, semantic search quality,
eval harness coverage, and the AgentScaffold Benchmark CLI.

### Fixed (trust/safety: never clobber org/user-owned agent or skill files)
- **Project-owned agent docs are never overwritten -- guidance is appended into a
  managed block.** `scaffold agents generate-all`, `scaffold agents generate`,
  `scaffold agents cursor`, and a fresh `scaffold init` previously overwrote
  `AGENTS.md`, `CLAUDE.md`, `.windsurfrules`, and `.cursor/rules.md`
  unconditionally, silently destroying hand-authored content (a real footgun for
  established repos and multi-user/org teams). These project-owned docs are now
  written via a new `write_managed_block` helper that delimits generated guidance
  with sentinel markers
  (`<!-- BEGIN AGENTSCAFFOLD MANAGED SECTION -->` ... `<!-- END ... -->`):
  - **File absent** -> created with the managed block.
  - **File has the markers** -> only the region between them is refreshed;
    everything outside is preserved (idempotent, no duplication on re-runs).
  - **File exists WITHOUT markers (org/user-owned)** -> a fresh managed block is
    **appended** to the end; not one existing byte is touched.
  - `--force` rewrites the whole file, saving a `.bak` snapshot first.
- **User/org-authored skills are never overwritten.** Generated `SKILL.md` files
  now carry a `managed_by: agentscaffold` frontmatter marker. `scaffold agents
  skills` writes a skill only when it is absent or previously generated by
  AgentScaffold; a same-named file lacking the marker is preserved (a warning is
  logged). `--force` overwrites it after saving a `.md.bak` snapshot.
- Machine-owned files (`.cursor/rules/agentscaffold.md` routing/trust policy,
  per-reviewer rules, enforcement hooks, agent stubs) are still regenerated every
  run so policy/config updates land; `.cursor/mcp.json` remains skip-if-exists.
- Added `--force` to `scaffold agents generate`, `agents cursor`,
  `agents generate-all`, and `agents skills`.
- These safety guarantees are documented in `docs/platform-integration.md`
  ("File Safety: What AgentScaffold Will and Will Not Overwrite") and summarized in
  the README.

### Changed (agent guidance for new capabilities)
- **Multi-project workspace discipline in generated rules**: the shared rule
  policy rendered into `.cursor/rules/`, `CLAUDE.md`, and other platform agent
  files now teaches project scoping -- reads default to the current project,
  plan numbers and file paths are not unique across projects, `--project` /
  `--all-projects` widen scope (with provenance on federated hits), and
  `scaffold graph duplicates` finds cross-project reuse candidates. The section
  is a no-op for lone single-project repos. Run `scaffold agents generate-all`
  to refresh existing agent files.
- **Multi-project docs now show real-time agent scoping.** README and
  configuration docs include a two-repo example showing that the agent's current
  working directory determines the default project, while `--project` and
  `--all-projects` are explicit cross-project scope wideners.

### Added (Plan 227 - semantic search quality, Tiers 2-3)
- **Embedding model is configurable and its weights cache is workspace-pinned.**
  New `search:` config block (`search.embedding_model`, default `all-MiniLM-L6-v2`;
  `search.cache_dir`, default `.scaffold/models`). Indexing and querying now load
  the model from the same pinned cache so they always agree.
- **`scaffold graph warm`** provisions (downloads + caches) the embedding model
  once, deliberately. This fixes a real fragility: installing the `[search]` extra
  gets the *library* but not the model *weights*, which sentence-transformers
  otherwise downloads lazily on first index/search -- a runtime failure when
  offline/air-gapped/CI/sandboxed. `scaffold graph warm` makes that step explicit.
- **`scaffold graph model-status`** reports readiness: package installed? weights
  cached (offline-ready)? cache dir? and tells you exactly what to run.
- **Offline-graceful degrade.** When the package + embeddings are present but the
  model weights are not cached (and there is no network), semantic/hybrid search
  now degrades to keyword-only with an actionable message ("run `scaffold graph
  warm`") instead of failing mid-query. `scaffold graph search`/MCP `scaffold_search`
  surface this via the existing `retrieval_status`/`retrieval_reason`.
- **Model provenance and mismatch safety.** `EmbeddingStore` now records the
  embedding model and input-text hash for each row (schema v9). Search filters to
  the active configured model and reports a re-index instruction rather than
  comparing incompatible vectors after a model swap.
- **Governance recall.** Plans, learnings, review findings, studies, ADRs, spikes,
  and backlog items now have embedding text builders and can be searched with
  `scaffold graph search --kind governance` (or `--kind all`). MCP clients get a
  dedicated `scaffold_recall_governance` tool plus `kind` support on
  `scaffold_search`.
- **Incremental embedding skip.** Embedding input text is SHA-256 hashed; rows
  whose `(node_id, node_type, model, text_hash)` already exists are skipped during
  embedding generation, avoiding unnecessary re-encoding.
- **Optional precision/performance paths.** DuckDB `vss`/HNSW index creation is
  attempted best-effort when the extension is available, with exact cosine as the
  correctness fallback. CrossEncoder reranking is implemented behind `--rerank`
  / `search.rerank` and remains off by default.
- Note: forcing the `[search]`/torch dependency at install time would NOT solve
  the weight issue (weights are not bundled in the wheel) and would bloat every
  install; the `[search]` extra stays optional, and provisioning is the explicit,
  offline-safe fix. Documented in `docs/configuration.md` and
  `docs/platform-integration.md`.

### Added (Plan 228 - eval harness coverage and rigor cost-benefit)
- **Multi-project eval scenarios** for scoped/federated search, duplicate
  detection, and single->multi migration integrity.
- **Search-quality eval scenarios** for keyword vs hybrid retrieval, embedding
  normalization, and model-readiness reporting.
- **Rigor cost-benefit proxy scenarios** comparing minimal/standard/strict
  governance settings.
- **Thread-safe governance writes** via a shared DuckDB write lock, fixing a
  pre-existing concurrent-write crash in the eval harness.

### Added (Plan 229 - AgentScaffold Benchmark foundation)
- **`scaffold benchmark` preflight and dry-run commands.** The new benchmark CLI
  group includes `models`, `doctor`, and `run --dry-run` so users can inspect
  selectable model configs, verify Docker/dependency/API-key/pricing readiness,
  and preview a two-arm benchmark plan without starting containers or live model
  calls.
- **Optional benchmark dependency extra.** Live-run dependencies
  (`mini-swe-agent`, `litellm`, `datasets`) are behind
  `agentscaffold[benchmark]`, keeping the base install light while making live
  benchmark setup explicit.
- **Cost-source transparency.** Built-in benchmark model metadata records provider,
  API-key env var, and pricing source (`litellm`). The docs distinguish provider
  API pricing from Cursor subscription/usage pricing, which requires a separate
  adapter before any Cursor-specific savings claims.
- **Benchmark task and report contracts.** Added deterministic task graders for
  tests-go-green and planted-defect review tasks, a serializable `summary.json`
  result schema, per-arm metric aggregation, and `scaffold benchmark compare` /
  `report` commands for saved results. Live execution will write into these
  contracts in the next Plan 229 slice.
- **Guarded live-runner adapter boundary.** Added baseline/equipped arm
  definitions, isolated task workspace setup, container-local `scaffold-*`
  wrapper scripts, trajectory metric extraction, and a guarded mini-swe-agent
  adapter that fails closed with actionable dependency/setup messages until the
  concrete Docker run loop is completed.
- **Concrete mini-swe-agent Docker adapter.** The guarded adapter now builds the
  selected model config, starts a mini-swe-agent Docker environment, copies the
  isolated task workspace into `/testbed`, installs equipped-arm wrappers, runs
  the agent, executes task validation, extracts trajectory metrics, and writes
  benchmark summaries. Reports now include seed pass-rate ranges when multiple
  seeds are present.

### Changed (Plan 227 - semantic search quality, Tier 1)
- **Richer embedding text**: code embeddings now include each definition's
  docstring or leading comment (read from its source slice at index time), not
  just `name + signature + module`, so semantic search matches on intent rather
  than identifiers alone. Best-effort and additive -- when source is unavailable
  the text falls back to the previous representation.
- **Store-time vector normalization**: embeddings are L2-normalized before
  storage, so cosine similarity equals the dot product and a future L2 ANN index
  ranks identically. Re-index to regenerate vectors in the new representation.
- Hybrid retrieval (lexical/symbol + vector via reciprocal-rank fusion) remains
  the default search mode; `--mode keyword|semantic` are the escape hatches.

### Added (Plan 225 - namespaced multi-project workspace)
- **Multi-project workspaces**: several projects can share one knowledge-graph
  cache. A `workspace.yaml` at the workspace root lists member projects; every
  node is then namespaced by project (`{project}::{raw_id}`) and stamped with a
  `project` column. A lone repo with no `workspace.yaml` is byte-for-byte
  unchanged (single synthesized project, no ID prefixing, every scope predicate a
  no-op).
- **`scaffold workspace` commands**: `workspace list` shows the workspace mode
  and member projects; `workspace onboard <dir> [--name]` registers a project
  (creating the manifest on first use) and reports the single->multi transition.
- **Project-scoped reads by default**: in a multi-project workspace, search
  (`scaffold graph search`, MCP `scaffold_search`) and governance reads
  (plans/studies/ADRs/spikes/findings/learnings, including file-path-keyed
  lookups) default to the current project so an agent never misreads a sibling
  project's knowledge. `--project NAME` retargets and `--all-projects` federates
  (federated hits carry per-row project provenance).
- **`scaffold graph duplicates`**: surfaces cross-project near-duplicate
  definitions (federated pairwise cosine over embeddings) to drive shared-library
  reuse. Single-project repos report nothing.
- **Atomic single->multi mode flip**: `workspace onboard --migrate-existing NAME`
  re-keys an existing single-project cache in place (nodes + edges + embeddings
  in one transaction, idempotent, rollback-safe), and `verify_integrity` asserts
  every project-stamped row carries its matching id prefix.

### Changed / Breaking (Plan 225)
- **Schema `SCHEMA_VERSION` 7 -> 8**: additive `Project` node + `project` column
  on node tables and `EmbeddingStore`. The bump triggers the existing fail-closed
  export -> rebuild -> import on the next `scaffold index`; governance is
  preserved. Single-project IDs stay unprefixed.
- **Shared cache location**: a relative `graph.db_path` now resolves under the
  workspace root (the nearest `workspace.yaml`), not each project root, so
  workspace members share one cache. For a lone repo the workspace root is the
  project root, so the resolved path is unchanged.
- **Project names** are restricted to `[A-Za-z0-9._-]+` (no whitespace, quotes,
  or `::`) so they are unambiguous as an ID prefix and safe to inline in scope
  predicates.

### Added (Plan 226 - collaboration ergonomics)
- **Opt-in governance-file sharding**: with `collab.sharded: true`, the
  high-contention `workflow_state.md` / `backlog.md` can be stored as per-entry
  fragments so concurrent writers touch different files. `scaffold state split`
  shards an existing file (reversible) and `scaffold state render` reassembles
  the canonical file deterministically (stable order; rendering twice is
  byte-identical). Defaults to `false`, so existing repos are unaffected.
- **Advisory plan claims**: `scaffold plan claim <number> --owner <who>` records
  git-backed, advisory ownership of an in-flight plan; `scaffold plan release`
  clears it. `scaffold plan status` shows an Owner column when claims exist.
  Claims are visibility, not enforced locks (git still resolves concurrent edits).

### Added (Plan 224 - config inheritance)
- **`extends:` in `scaffold.yaml`**: a project can inherit shared policy (rigor,
  gates, standards, reviewers, prohibitions, approval rules) from a base config
  instead of copying it into every repo. The base is a filesystem path
  (absolute, or relative to the file that declares `extends`; a directory
  resolves to its `scaffold.yaml`) or the literal `home`.
- **Org/user home**: `extends: home` resolves to `$AGENTSCAFFOLD_HOME` (else
  `~/.agentscaffold/scaffold.yaml`). An absent home config is a no-op, so a repo
  with `extends: home` still works on a machine without shared config.
- **Deterministic precedence** (low -> high): built-in defaults, then the
  `extends` base chain (recursively), then the project `scaffold.yaml`, then
  environment overrides (e.g. `AGENTSCAFFOLD_DB_PATH`). Deep-merge per field;
  lists are replaced wholesale, not concatenated. Cycles and missing explicit
  bases raise a clear error; an absent `home` base is silent.
- **`scaffold config show`**: prints the inheritance chain (base-first) and the
  effective merged configuration, so precedence is debuggable.
- Repos without `extends:` are unaffected (resolution is byte-for-byte today's).

### Changed
- **Path/root unification** (Plan 221): all CLI commands now resolve governance
  paths through one project-root rule (nearest `scaffold.yaml`, then nearest
  `.git`, then the working directory) and one `ResolvedPaths` accessor derived
  from `GraphConfig`. Commands that previously hardcoded `docs/ai/*` literals
  (`plan create/lint/status`, `spike create`, `study create/list/lint`,
  `retro check`, `metrics`, `validate`, `domain add`) now honor customized
  `graph.*` paths. Defaults equal the previous literals, so an uncustomized repo
  is unaffected.
- **`db_path` resolves from the project root** (Plan 221): `open_graph` and the
  index pipeline now resolve a relative `graph.db_path` against the project root
  instead of the bare working directory, so querying the graph works from any
  subdirectory and matches where `scaffold index` writes it. Repos that relied on
  a relative `db_path` resolving against a subdirectory should set an absolute
  `db_path` or run from the project root. Absolute `db_path` values are unchanged.

### Added
- New `graph.*` config fields (additive, defaults = previous literals):
  `backlog_file`, `backlog_archive_file`, `standards_dir`, `prompts_dir`,
  `templates_dir`, `plan_completion_log_file`, `security_dir`.
- **Git-backed governance serialization** (Plan 222): review findings, sessions,
  and backlog items recorded at runtime are now serialized to a versioned,
  git-committed JSON artifact (`graph.governance_artifact`, default
  `docs/ai/state/governance.json`). This makes agent-generated knowledge the
  durable *system of record*; the DuckDB graph becomes a derived index that
  `scaffold index` rebuilds from the artifact plus code. Commit the artifact to
  share findings/sessions/backlog with teammates and to survive cache loss.
  Writes are atomic and emitted in a stable order to minimize git churn.
- New `graph.governance_artifact` config field.
- **Durable/ephemeral storage** (Plan 223): `graph.db_path` now supports
  `${ENV}`/`$VAR` and `~` expansion, and an `AGENTSCAFFOLD_DB_PATH` environment
  variable overrides it entirely -- so one committed `scaffold.yaml` can point
  the cache at a mounted volume on a persistent box and a scratch path on an
  ephemeral devbox. On a fresh/empty cache, `scaffold index` reports when it
  rebuilds governance from the committed artifact (`restored_from_artifact`),
  so an ephemeral devbox reconstructs the full graph from git alone.

## [0.6.0] - 2026-06-14

Trust & Safety Hardening batch (Plans 217-220).

### Added
- **Schema-migration export safety** (Plan 219): when the graph schema version
  changes, `scaffold index` now preserves governance (review findings, backlog
  items, sessions, and their edges) instead of silently wiping it. It exports to
  `.scaffold/graph_export_v{old}.json` before the rebuild and re-imports the
  schema-compatible data afterward (per-table column-intersection check;
  incompatible data is kept in the export file and reported rather than dropped).
  The migration is **fail-closed**: if the export step fails, the rebuild is
  aborted and the existing graph is left intact, so knowledge is never lost.
- **`scaffold index --force-rebuild`**: opt-in escape hatch that rebuilds anyway
  when an export error is unrecoverable. This permanently discards the preserved
  governance and is never the default.
- **`scaffold graph prune`** (Plan 219): selectively prune old governance
  (resolved findings, archived backlog items, and sessions past an age cutoff).
  Status-aware and **dry-run by default**; requires `--apply` to delete.
- **Retrieval degradation contract** (Plan 220): a capability oracle reports
  retrieval status (`available` / `degraded` / `unavailable`) plus the effective
  vs requested search mode. MCP tool `meta` and `scaffold graph search` now
  surface when semantic search has degraded to keyword (e.g. embeddings missing
  or `sentence-transformers` not installed) instead of failing silently.
- **Backend connection diagnostics** (Plan 218): a clearer `GraphLockError` with
  bounded retry/backoff on DuckDB lock contention, and explicit logging when the
  `duckpgq` / `vss` extensions fail to install or load. The MCP server now
  returns a clean `graph_locked` error instead of crashing when the graph file
  is held by another process. README and user guide document the single-writer
  model for teams.

### Changed
- **Single source of truth for the graph schema** (Plan 217): edges are defined
  once in `EDGE_DEFS`; the property-graph DDL, edge/node table-name lists, and
  the clear/governance helpers are all derived from it, eliminating schema drift
  between definitions. No on-disk schema change -- `SCHEMA_VERSION` remains 7.
- Removed the unused `rank-bm25` dependency from the `[search]` extra.

## [0.5.0] - 2026-06-12

### Added
- `scaffold init` now generates the complete platform rule set on a fresh init
  (previously it only wrote the static `AGENTS.md` and `.cursor/rules.md`).
  A fresh init now also emits `.cursor/rules/agentscaffold.md` (the MCP routing +
  graph trust-discipline policy, including the Plan 214 context-blindness
  mitigations), `.cursor/mcp.json`, `CLAUDE.md`, per-reviewer subagent files,
  `.windsurfrules`, and lifecycle hooks. Generation is gated on a fresh init
  (when `scaffold.yaml` is first created) so re-running `scaffold init` stays
  idempotent and never clobbers hand-edited rules.
- Generated `AGENTS.md` template gains three generalizable governance rules:
  a worked "When NOT to fix F841" linter example, a "verify integration points
  early" execution rule, and a smoke-test "Plan Template Addition" checklist for
  plans that cross integration boundaries.

### Fixed
- `scaffold agents generate-all` now writes `.cursor/rules/agentscaffold.md` in
  parity with `scaffold agents cursor`. Previously the MCP routing / graph
  trust-discipline doc was only produced by `scaffold agents cursor`, so
  `generate-all` left Cursor without the routing policy.
- `scaffold agents generate-all` now writes `.windsurfrules` (previously it only
  wrote Windsurf agent stubs and hooks, never the main rules file).
- `generate-all` no longer depends on the current working directory: `CLAUDE.md`
  and `.windsurfrules` generation now use the project config passed to
  `run_agents_generate_all_platforms` instead of re-discovering `scaffold.yaml`
  via `find_config()`. This previously caused `scaffold init <dir>` (run from a
  different cwd) to abort rule generation after `AGENTS.md`.
- README "what init creates" list corrected to match actual output.

## [0.4.1] - 2026-06-12

### Fixed
- README documentation links now use absolute GitHub URLs instead of relative paths,
  so they resolve correctly on the PyPI project page (relative links rendered dead on
  PyPI because they resolved against pypi.org rather than the repository).

## [0.4.0] - 2026-06-12

### Added
- **Cursor native hooks** (`scaffold agents hooks --platform cursor`): generates
  `.cursor/hooks.json` plus an `afterFileEdit` wrapper that keeps the knowledge graph
  fresh by running `scaffold index --incremental`. The wrapper is non-blocking and
  single-flight with a coalescing debounce, so rapid multi-file edits never stack and
  Cursor is never blocked.
- **Config-reference indexing** (Plan 216): a new `CONFIG_REFERENCES` graph edge links
  config files (YAML/JSON/TOML) to the code they wire dynamically. References are
  extracted only under an allowlist of keys (`class`, `_target_`, `type`, ...) and
  resolved to files/classes (confidence 0.9 for file+symbol, 0.7 for file-only). Config
  consumers now appear in `scaffold_impact` and `scaffold_context`, closing part of the
  config-driven-dispatch blind spot (e.g. editing a strategy class now shows
  `strategy_registry.yaml` as a dependent).
- **Graph coverage signaling** (Plan 214): `scaffold_orient` reports repository parse
  coverage; `scaffold_impact` / `scaffold_context` attach a coverage caveat when a target
  is in an unparsed language or returns no results, so absence of edges is not mistaken
  for absence of relationships. Generated agent rules include a "graph trust discipline"
  section.
- **Edge-confidence surfacing** (Plan 215): heuristic (low-confidence) call edges are
  annotated in tool markdown and counted (`heuristic_caller_count`), distinguishing
  guessed dispatch edges from resolved ones. `scaffold validate --check coverage` returns
  an on-demand coverage audit.
- **ReviewFinding ingestion** (Plans 212/213): `[CATEGORY]` markers in plan text are
  parsed into `ReviewFinding` nodes during governance indexing (widened matcher, severity
  support), with findings linked to the files they reference.
- **Incremental governance freshness gate** (Plan 213): governance documents are
  fingerprinted so a code-only edit skips the governance reingest while a doc edit forces
  a refresh.

### Changed
- **Default graph path is now `.scaffold/graph.duckdb`** (was `.scaffold/graph.db`) to
  reflect the DuckDB + DuckPGQ backend. Existing `.scaffold/graph.db` files can be deleted;
  `scaffold index` rebuilds the graph (it is a derived cache).
- **KuzuDB backend fully removed.** DuckDB + DuckPGQ is the only supported backend;
  `open_graph()` rejects any other `graph.backend` value. (See ADR-023 update.)
- Graph schema bumped to version 7 (new `CONFIG_REFERENCES` edge). The graph rebuilds
  automatically on first run after upgrade.
- `scaffold import --format claude` now reports clearly that Claude import is not yet
  supported instead of writing a placeholder file that looked like a successful import.

### Fixed
- Graph integrity and agent-facing rendering (Plan 212): query alias prefixes are stripped
  from tool output and relationships render as readable markdown.
- `__version__` was stale (`0.2.4`) and out of sync with the packaged version; both are now
  `0.4.0`.
- Documentation corrected across README, getting-started, user-guide, platform-integration,
  and ci-integration to reference the DuckPGQ graph at `.scaffold/graph.duckdb`.

## [0.3.1] - prior

Baseline prior to this changelog. See git history for details.
