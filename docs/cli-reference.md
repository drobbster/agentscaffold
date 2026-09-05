# CLI Reference

Every `scaffold` command, what it does, and how to run it.

This is a reference. For the workflows these commands belong to, see the
[User Guide](user-guide.md); for setting up an editor, see
[Platform Integration](platform-integration.md).

```bash
scaffold --help              # all command groups
scaffold <group> --help      # commands in a group
scaffold <command> --help    # full options for one command
scaffold --version
```

Most commands operate on the project in your current directory. Commands that
read or write the knowledge graph need it to exist — run `scaffold index` first.

---

## Contents

- [Setup and project lifecycle](#setup-and-project-lifecycle)
- [Multi-project workspaces](#multi-project-workspaces)
- [Health and maintenance](#health-and-maintenance)
- [Knowledge graph](#knowledge-graph)
- [Plans](#plans)
- [Reviews](#reviews)
- [ADRs, spikes, and studies](#adrs-spikes-and-studies)
- [Agent integration files](#agent-integration-files)
- [Sessions](#sessions)
- [Governance state](#governance-state)
- [Validation and CI](#validation-and-ci)
- [Domain packs](#domain-packs)
- [Benchmarking](#benchmarking)
- [Environment variables](#environment-variables)
- [Troubleshooting](#troubleshooting)

---

## Setup and project lifecycle

| Command | Does |
|---|---|
| `scaffold init [DIRECTORY]` | Scaffold a new project: config, templates, governance tree, agent files |
| `scaffold index` | Build or rebuild the knowledge graph |
| `scaffold config show` | Show the effective merged config and where each value came from |
| `scaffold version` | Show the installed version (same as `scaffold --version`) |
| `scaffold import` | Import an AI conversation into project docs |

### `scaffold init`

```bash
scaffold init                    # scaffold the current directory
scaffold init path/to/project
scaffold init -y                 # accept all defaults, no prompts
scaffold init --dry-run          # report what it would write, write nothing
```

Re-running `init` on a project that already has everything reports "no changes"
and writes nothing, so it is safe to run again after upgrading.

Inside an existing multi-project workspace, `init` **joins** that workspace —
registering the project in the manifest and the registry — rather than copying
the workspace's shared assets into the project.

### `scaffold index`

```bash
scaffold index                   # full build
scaffold index --incremental     # only what changed
```

The graph backs search, impact analysis, and every governance query. Build it
once after `init`, then rebuild after significant changes. See
[Knowledge graph](#knowledge-graph) for what you can ask it.

---

## Multi-project workspaces

One MCP server serves every registered project. Registration is what lets it
find them.

| Command | Does |
|---|---|
| `scaffold project register [ROOT]` | Record a root so one MCP server can resolve it |
| `scaffold project unregister NAME` | Forget a registered project |
| `scaffold project list` | List every registered project and its resolved root |
| `scaffold mcp install` | Install the single MCP server entry in your client config |
| `scaffold workspace onboard PATH` | Add a project to the workspace manifest, creating it if needed |
| `scaffold workspace list` | List the projects in the current workspace |
| `scaffold workspace migrate-layout` | Move a workspace to the shared asset layout |
| `scaffold workspace migrate-state` | Move the graph out of the working tree |

### `scaffold project register`

```bash
scaffold project register                       # register the current directory
scaffold project register /path/to/repo
scaffold project register /path/to/repo --name api
```

The name defaults to the directory name and must be unique across the registry,
because names qualify node IDs in the graph. The registry lives at
`~/.agentscaffold/registry.yaml` (or `$AGENTSCAFFOLD_HOME`).

Registration never edits your MCP config, and never happens as a side effect of
a tool call or an index. Widening what a server can reach is always deliberate.

If you use a workspace manifest, `scaffold workspace onboard` registers projects
for you — you do not need to register them a second time.

### `scaffold mcp install`

```bash
scaffold mcp install                       # writes ~/.cursor/mcp.json
scaffold mcp install --dry-run             # show the change, write nothing
scaffold mcp install --migrate             # also remove legacy per-project entries
scaffold mcp install --config /path/to/mcp.json
```

Writes exactly one entry:

```json
"agentscaffold": { "command": "scaffold", "args": ["mcp"] }
```

No directory binding and no interpreter path, so it survives a virtualenv
rebuild and resolves `scaffold.exe` through `PATH` on Windows. Running it again
when the entry is already correct reports no change.

Your other MCP servers are safe: the installer compares the document it is about
to write against the original and refuses if any entry it does not own would
change. A config it cannot parse is refused outright, with the entry printed for
you to paste in by hand.

`--migrate` backs the file up first, then removes AgentScaffold's own
per-project entries. Per-repository `.cursor/mcp.json` files are reported but
never edited, because they are often committed and a deletion could travel into
someone else's checkout.

### `scaffold mcp`

Runs the server. Your MCP client invokes this; you rarely run it by hand.

```bash
scaffold mcp
scaffold mcp --restrict-to api,web        # limit this server to named projects
scaffold mcp --workspace /root --project api   # pin the resolution anchor (single-workspace only)
```

`--workspace` / `--project` set a process-wide default. Do not put them in a
shared `mcp.json` if several workspaces are registered; pass `working_path` (or
`project`) on each call instead. See [Multi-Project Workspaces](multi-project.md).

### `scaffold workspace migrate-state`

```bash
scaffold workspace migrate-state                    # dry run (default)
scaffold workspace migrate-state --apply
scaffold workspace migrate-state --restore --apply  # move it back in-tree
```

See [Where the graph lives](multi-project.md#where-the-graph-lives) for what
this moves and why.

---

## Health and maintenance

| Command | Does |
|---|---|
| `scaffold doctor` | Diagnose the installation; reads only, changes nothing |
| `scaffold gc` | Reclaim state left behind by workspaces that no longer exist |
| `scaffold graph prune` | Selectively prune old governance knowledge |

### `scaffold doctor`

```bash
scaffold doctor                       # report; always exits 0
scaffold doctor --strict              # exit non-zero if anything is not clean
scaffold doctor --tools               # also call every MCP tool and report each
scaffold doctor --tools --include-writes
scaffold doctor --project-root /path/to/repo
scaffold doctor --mcp-config /path/to/mcp.json
```

Checks the registry, workspace identity, generated rule-file drift, MCP
registration, version skew between the MCP server and your CLI, and where the
graph resolves.

It never repairs anything, so it is safe to run on a setup you already believe
is broken. The default exit code is 0 whatever it finds, which makes it safe in
a shell profile or a git hook; `--strict` is the gate to put in CI.

#### `--tools`

Calls every MCP tool once and reports how each behaved. This answers the
question the configuration checks cannot: whether the tools actually work in
your installation, right now.

Four outcomes:

| Status | Meaning |
|--------|---------|
| `ok` | The tool ran and answered |
| `busy` | Another process holds the graph; retry shortly |
| `skip` | Not exercised (a write tool, or no usable graph) |
| `FAIL` | The tool errored |

`busy` is deliberately distinct from `FAIL`. An indexing run in another terminal
holds the graph briefly, and that is normal rather than broken.

Write tools are skipped by default, so the command cannot leave findings or
backlog items in your governance record. `--include-writes` exercises them
against a temporary throwaway project with its own database, which is discarded
afterwards; it never writes to your project even with the flag set.

If the table shows every tool skipped with "graph schema is out of date", run
`scaffold index` — the database predates the current schema.

### `scaffold gc`

```bash
scaffold gc            # reports only
scaffold gc --apply    # deletes what it reported
```

Removes state directories for workspaces that are gone and registry entries
pointing at missing roots. It deletes only what it can prove is orphaned and
reports anything it cannot. See [Reclaiming space](multi-project.md#reclaiming-space).

### `scaffold graph prune`

```bash
scaffold graph prune                          # dry run
scaffold graph prune --apply
scaffold graph prune --malformed-findings     # dry run: list malformed rows
scaffold graph prune --malformed-findings --apply
```

Drops old governance rows from the graph. Dry run is the default, so the plain
form only reports what it would remove.

`--malformed-findings` targets a specific historical defect rather than age.
Before 0.10.0, finding extraction matched a `[CATEGORY]` token anywhere in a line
instead of only at the start, so ordinary prose that happened to mention one --
including the plan documents describing the bug -- produced garbled findings with
truncated text. The extraction is fixed, but rows already written stay until
removed.

Removal is permanent in both places that matter: the graph and the
`governance.json` artifact re-indexing restores from. Pruning only the graph
would let the next index bring them straight back.

```bash
scaffold graph prune --malformed-findings          # see what would go
scaffold graph prune --malformed-findings --apply  # then remove it
```

Run this once after upgrading if your findings list contains entries with
truncated or nonsensical text. A clean project will report nothing to prune.

---

## Knowledge graph

| Command | Does |
|---|---|
| `scaffold graph search QUERY` | Search the graph in natural language |
| `scaffold graph stats` | Codebase statistics and health dashboard |
| `scaffold graph orient` | Session orientation: stats, workflow state, recent activity |
| `scaffold graph verify` | Spot-check graph accuracy against the filesystem |
| `scaffold graph query SQL` | Run a raw SQL query against the graph |
| `scaffold graph communities` | Show detected module communities |
| `scaffold graph duplicates` | Cross-project near-duplicate definitions |
| `scaffold graph warm` | Download and cache the embedding model for offline search |
| `scaffold graph model-status` | Report whether embedding search is ready |

```bash
scaffold graph search "authentication flow"           # hybrid (default)
scaffold graph search "router" --mode keyword         # name/path matching
scaffold graph search "how is data loaded" --mode semantic
scaffold graph search "risk" --top 5
scaffold graph search "base class" --table Class
scaffold graph search "symbol normalization" --project api
scaffold graph search "symbol normalization" --all-projects
```

Modes are `keyword`, `semantic`, and `hybrid` (the default). `--kind` limits the
corpus to `code`, `governance`, or `all`. In a multi-project workspace,
`--project` targets a sibling and `--all-projects` federates across every
project, tagging each hit with the project it came from.

Semantic search needs the embedding model. `scaffold graph warm` downloads it
once into a user-level cache shared by every project, so it is not re-downloaded
per repository. `scaffold graph model-status` says whether it is ready.

`scaffold graph duplicates` is advisory: it surfaces near-identical definitions
across projects in a workspace as candidates for a shared library.

---

## Plans

| Command | Does |
|---|---|
| `scaffold plan create` | Create a plan from a template |
| `scaffold plan status` | All plans with their lifecycle state |
| `scaffold plan lint` | Validate plan structure and cohesion |
| `scaffold plan claim` | Record advisory, git-backed ownership of an in-flight plan |
| `scaffold plan release` | Clear an advisory claim |
| `scaffold metrics` | Plan metrics and analytics dashboard |
| `scaffold retro` | Find plans missing retrospectives |

```bash
scaffold plan create "Add rate limiting"
scaffold plan create "Fix token refresh" --type bugfix
scaffold plan status
scaffold plan lint
```

Claims are advisory and git-backed: they tell a teammate or another agent that a
plan is in flight. They do not lock anything.

---

## Reviews

Composite commands assemble review context from the graph. Each has an MCP
equivalent your agent calls directly.

| Command | Does |
|---|---|
| `scaffold review prepare` | Full review context: brief, challenges, gaps, ADRs, studies |
| `scaffold review implement` | Implementation context: brief, blast radius, contracts, dependencies |
| `scaffold review brief` | Pre-review brief |
| `scaffold review challenges` | Adversarial challenges for devil's-advocate review |
| `scaffold review gaps` | Gap analysis for expansion review |
| `scaffold review staleness` | Whether a plan has gone out of date |
| `scaffold review rewrite` | Staleness check plus rewrite context |
| `scaffold review compare` | Compare two plans for overlap and conflicts |
| `scaffold review retro` | Retrospective context |
| `scaffold review verify` | Post-implementation compliance against a plan |
| `scaffold review history` | Review findings and plan history for a file or module |

```bash
scaffold review prepare 42
scaffold review compare 42 43
scaffold review history src/api/auth.py
```

---

## ADRs, spikes, and studies

| Command | Does |
|---|---|
| `scaffold adr list` | List all ADRs |
| `scaffold adr search TOPIC` | Search ADRs by keyword |
| `scaffold adr decision PLAN` | Full decision chain for a plan: ADRs, spikes, studies |
| `scaffold spike create` | Create a spike from the template |
| `scaffold study create` | Create a study from the template |
| `scaffold study list` | List and query studies |
| `scaffold study search TOPIC` | Search studies by topic or outcome |
| `scaffold study experiments PLAN` | Prior experiments related to a plan |
| `scaffold study lint` | Validate study files against the template |

```bash
scaffold adr search "storage"
scaffold adr decision 42
scaffold spike create "Validate queue throughput"
scaffold study create "Compare retrieval strategies"
```

---

## Agent integration files

| Command | Does |
|---|---|
| `scaffold agents generate-all` | Generate every platform artifact at once |
| `scaffold agents generate` | Routing block in `AGENTS.md` |
| `scaffold agents repair` | De-duplicate `AGENTS.md` headings (dry run; `--apply` writes) |
| `scaffold agents diff-manual` | Compare the project-owned manual to the template (dry run; `--apply` writes) |
| `scaffold agents cursor` | `.cursor/rules.md` and rule files |
| `scaffold agents claude` | `CLAUDE.md` |
| `scaffold agents windsurf` | `.windsurfrules` |
| `scaffold agents skills` | `SKILL.md` files for Claude and Cursor |
| `scaffold agents hooks` | Platform-native lifecycle hooks |
| `scaffold agents prompt` | A generic system-prompt snippet for any platform |

```bash
scaffold agents generate-all
scaffold agents generate-all --allow-append   # append routing when the overlap guard refuses
scaffold agents repair                        # dry run
scaffold agents repair --apply
scaffold agents diff-manual                   # dry run
scaffold agents diff-manual --apply
```

`--force` rewrites the whole file. `--allow-append` only appends. They are not
the same flag.

Run `generate-all` after changing `scaffold.yaml`, and whenever `scaffold doctor`
reports that generated rule files have drifted. Use `repair` on a duplicated
`AGENTS.md`. Use `diff-manual` to pull template updates into a manual you own.

---

## Sessions

| Command | Does |
|---|---|
| `scaffold session start` | Start a session for cross-session memory |
| `scaffold session end` | Finalize a session |
| `scaffold session list` | Recent sessions |
| `scaffold session context` | Cross-session context: hot files, recent plans |

Agents should prefer the MCP session tools (`scaffold_session_start`,
`scaffold_session_record_decision`, `scaffold_session_end`) described in the
generated routing block. `scaffold_session_record_decision` takes `kind`
(`strategic` / `architectural` / `operational`) and is not for findings or
backlog items. `scaffold review compare` / `scaffold_compare_plans` now also
returns pairwise `dependency_cycle` when plans declare `Step dependencies:`.

```bash
scaffold session start "Add rate limiting"
scaffold session end                 # ends the most recent session
scaffold session list
```

---

## Governance state

| Command | Does |
|---|---|
| `scaffold state split` | Shard a governance file into per-entry fragments |
| `scaffold state render` | Reassemble fragments into the canonical file |

Sharding reduces merge conflicts on `workflow_state.md` and `backlog.md` when
several people or agents write to them. It is reversible.

---

## Validation and CI

| Command | Does |
|---|---|
| `scaffold validate` | All enforcement checks: lint, integration, retros, prohibitions, secrets |
| `scaffold ci` | Generate CI workflow files |
| `scaffold taskrunner` | Generate a justfile and/or Makefile with framework commands |
| `scaffold notify` | Send a notification via the configured channel |

```bash
scaffold validate
scaffold ci --provider github
scaffold taskrunner
```

For CI, the useful gate combination is:

```bash
scaffold validate
scaffold doctor --strict
scaffold graph verify
```

---

## Domain packs

| Command | Does |
|---|---|
| `scaffold domains list` | Available and installed packs |
| `scaffold domains add NAME` | Install a pack's templates and standards |
| `scaffold plugins package` | Package a pack as a pip-installable plugin |

---

## Benchmarking

Requires the `benchmark` extra: `pip install "agentscaffold[benchmark]"`.

| Command | Does |
|---|---|
| `scaffold benchmark doctor` | Check the benchmark environment is ready |
| `scaffold benchmark run` | Run or plan a benchmark |
| `scaffold benchmark models` | List built-in model configs |
| `scaffold benchmark report` | Render a report |
| `scaffold benchmark compare` | Compare result directories |

---

## Environment variables

| Variable | Effect |
|---|---|
| `AGENTSCAFFOLD_DB_PATH` | Absolute path to the graph database. Overrides everything else |
| `AGENTSCAFFOLD_HOME` | Where the user-level registry lives (default `~/.agentscaffold`) |
| `AGENTSCAFFOLD_WORKSPACE_ROOT` | Pin the MCP server's workspace anchor (single-workspace installs only) |
| `AGENTSCAFFOLD_PROJECT` | Pin the MCP server's project anchor (single-workspace installs only) |
| `XDG_STATE_HOME` | Base for graph state (default `~/.local/state`) |
| `XDG_CACHE_HOME` | Base for the embedding model cache (default `~/.cache`) |

`AGENTSCAFFOLD_DB_PATH` is the one to reach for in CI and containers: it pins
the database wherever your cache already lives, and takes precedence over both
`graph.db_path` in `scaffold.yaml` and the platform default.

---

## Troubleshooting

### A command says the graph is missing or empty

Run `scaffold index`. Commands that search, analyse impact, or assemble review
context all read the graph, and it is not built by `init`.

### Semantic search returns nothing, or falls back to keyword matching

The embedding model is not cached. Run `scaffold graph warm` once, then
`scaffold graph model-status` to confirm. The cache is user-level and shared
across projects.

### An MCP tool call fails with `ambiguous_project`

The call could not be narrowed to one project. On a multi-workspace install
that is expected when neither `working_path` nor `project` was passed. Run
`scaffold project list` (or call `scaffold_projects`) to see the candidates,
then pass `working_path` (the file you are working on) or `project` explicitly.
If the path is not under any registered root, register it with
`scaffold project register`. Do not add `--workspace` to the shared MCP entry
unless this machine has only one workspace.

### The MCP tools behave as if they are an old version

The server your editor launches is not the CLI you are running. Run
`scaffold doctor` — its version-skew check compares them and names both
versions. The usual cause is an MCP entry naming an absolute interpreter path
that no longer points where you think; `scaffold mcp install --migrate` replaces
it with an entry that resolves through `PATH`.

### `scaffold mcp install` refuses to write

Either the config cannot be parsed — fix the JSON, or paste the printed entry in
by hand — or an unrelated entry would have changed, in which case the pre-write
check failed closed. Use `--dry-run` to inspect the intended change.

### `scaffold workspace migrate-state` refuses to run

Something holds the graph open, usually the MCP server started by your editor.
Quit the editor and retry. The check is cross-process, so it also catches
another terminal running `scaffold index`.

### `scaffold init` seems to do nothing

That is the expected result on an already-initialized project: it reports "no
changes" and writes nothing. Use `--dry-run` to see what it evaluated.

### Two registrations for what looks like one directory

Roots are compared as paths, not strings, so on Windows `C:\Repo` and `c:\repo`
resolve to one entry. If you genuinely see two, they are different directories —
check `scaffold project list` output, including the path flavour.

---

## Related

- [Getting Started](getting-started.md) — install, init, first plan
- [User Guide](user-guide.md) — the workflows these commands belong to
- [Multi-Project Workspaces](multi-project.md) — one server, several projects
- [Platform Integration](platform-integration.md) — editor and MCP setup
- [Configuration](configuration.md) — full `scaffold.yaml` reference
