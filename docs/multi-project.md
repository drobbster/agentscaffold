# Multi-Project Workspaces

Running **one** AgentScaffold MCP server across every project you work on,
where the graph lives, and how to check that a setup is working.

For the individual commands, see the [CLI Reference](cli-reference.md).

---

## One server, several projects

A single MCP entry serves every registered project. You do not add an entry or
a server process per repository.

```bash
scaffold project register /path/to/api --name api
scaffold project register /path/to/web --name web
scaffold mcp install
```

Then restart your editor — MCP servers start with the client.

That is the whole setup. `scaffold project list` shows what is registered.

### Why one entry rather than one per project

An entry per project means editing client config and restarting every time you
add a repository. Worse, those entries usually carry an absolute path to a
virtualenv's `scaffold`, which creates two failure modes:

- **A rebuilt virtualenv breaks the entry**, because the path it names is gone.
- **A stale interpreter is invisible.** The entry keeps pointing at an old
  install and the server keeps starting, just with an outdated AgentScaffold and
  no indication that anything is wrong.

The canonical entry resolves through `PATH` and names no interpreter, so neither
can happen:

```json
"agentscaffold": { "command": "scaffold", "args": ["mcp"] }
```

### Migrating from per-project entries

Existing per-project registrations keep working. The server names them once at
startup along with the command that collapses them.

Entries in your shared config (`~/.cursor/mcp.json`), typically named
`agentscaffold-<project>`:

```bash
scaffold mcp install --migrate
```

This backs the file up, removes AgentScaffold's own per-project entries, and
leaves the single canonical one. Anything you did not register through
AgentScaffold is untouched.

Per-repository configs (`<repo>/.cursor/mcp.json`) must be removed by hand.
These files are frequently committed, so deleting an entry on your behalf could
travel into a colleague's checkout.

---

## How a call finds the right project

With one server serving many projects, every tool call resolves to exactly one:

1. An explicit `project` argument.
2. `working_path`, matched against registered roots — the **longest** matching
   root wins, so an inner project is never answered from its enclosing workspace.
   A relative path is interpreted against those roots, not against the server's
   own launch directory, and is accepted only when exactly one registered root
   explains it.
3. The server's startup anchor, **only when that directory is itself a project**
   (registered, or an unregistered repo that does not contain other registered
   projects). A home directory, a folder that merely contains workspaces, or a
   dotfiles repo wrapping several checkouts is a container, not a project, and
   is declined.
4. A sole registered project, when there is only one.

If none of these resolves, the call is **refused** with `ambiguous_project`
rather than guessed at, because silently answering from the wrong project is a
worse outcome than an error you can act on. The error names the candidates and
the arguments that would make the same call succeed (`retry_with`).

**With several workspaces registered, omit both `working_path` and `project`
and the call will usually refuse.** One MCP process serves every workspace from
a single fixed directory, so the launch directory is not a statement of which
project you meant. Pass `working_path` (the file or directory you are working
on) on project-scoped calls. The generated rule files already tell agents to
do this. If you have no path, pass `project=<name>`, or call `scaffold_projects`
to see what the server can answer for. A successful response's `meta` names the
project that answered and the tier that decided; `working_path_unmatched: true`
means a path was supplied but ignored.

**Do not pin `--workspace` in a shared `mcp.json` on a multi-workspace
machine.** That flag is a launch-time default for the whole process. One
process serves every workspace, so pinning would make every other workspace's
no-argument calls answer from the pinned one. Pinning is a single-workspace
option only (`scaffold mcp --workspace /path/to/that-one-repo`, or the
`AGENTSCAFFOLD_WORKSPACE_ROOT` / `AGENTSCAFFOLD_PROJECT` environment variables).

### Narrowing what one server can reach

```bash
scaffold mcp --restrict-to api,web
```

One server process can read every registered project. `--restrict-to` binds an
instance to an explicit allowlist.

---

## Where the graph lives

| Your project | Graph location |
|---|---|
| Not registered | `<repo>/.scaffold/graph.duckdb` |
| Registered | `~/.local/state/agentscaffold/<workspace-id>/graph.duckdb` |

The state directory honours `$XDG_STATE_HOME`, and on native Windows it is
`%LOCALAPPDATA%\agentscaffold\State`. It is readable and writable by you only,
because it aggregates indexed content from every registered workspace into one
place.

Ask rather than infer:

```bash
scaffold doctor
```

```
ok Graph state location — Graph resolves as expected.
      graph: /home/you/.local/state/agentscaffold/ws-eab285242ff8/graph.duckdb
      workspace id: ws-eab285242ff8
```

`AGENTSCAFFOLD_DB_PATH` beats an explicit `graph.db_path` in `scaffold.yaml`,
which beats the default above. If you pin a path, it is honoured exactly.

### Moving an existing graph

**Upgrading does not move your graph.** An existing in-tree database keeps
winning over an empty state directory — otherwise resolution would point at
nothing, re-index from scratch, and leave your populated database orphaned in
the tree.

Dry run is the default:

```bash
scaffold workspace migrate-state
scaffold workspace migrate-state --apply
```

```
Moved /home/you/repo/.scaffold/graph.duckdb
     to /home/you/.local/state/agentscaffold/ws-eab285242ff8/graph.duckdb
  also moved governance.fingerprint
```

Every file is copied and verified by content hash before anything is removed,
and the freshness watermark travels with the database so a migrated graph does
not look stale and re-index on first use.

It refuses while any process holds the database, so a live MCP server cannot
have a file moved out from under it. Quit your editor and retry.

To go back:

```bash
scaffold workspace migrate-state --restore --apply
```

### CI and containers

`AGENTSCAFFOLD_DB_PATH` still overrides everything. If your CI caches
`.scaffold/` and the job registers the project, either point the cache at the
state directory or — usually less work — set `AGENTSCAFFOLD_DB_PATH` and keep
the cache path you already have.

---

## Shared asset layout

A `workspace.yaml` at the workspace root lets several projects share one graph
and, optionally, one copy of reusable process assets.

By default each project keeps a full `docs/ai` tree. Opting into
`asset_layout.layout: shared_workspace` puts reusable process assets (prompts,
standards, templates, collaboration protocol, commands, shared security
templates) once at the workspace root, while each project keeps its own plans,
ADRs, contracts, backlog, architecture, and vision.

```bash
scaffold workspace onboard services/api --shared-layout
scaffold workspace onboard apps/web
```

`scaffold init` run inside an existing workspace joins it rather than copying
the shared assets into the new project.

See the [Configuration guide](configuration.md) for the full schema and the
escape hatch for per-project customizations, and the
[User Guide](user-guide.md#multi-project-workspaces-and-shared-asset-layout) for
migrating an existing workspace with `scaffold workspace migrate-layout`.

### Generated rule files

In a shared-layout workspace the routing policy has one canonical source at the
workspace root, and each project's rule files carry a copy stamped with its
content hash. `scaffold doctor` reports a mismatch:

```
warn Routing guidance — 2 generated rule file(s) have drifted.
      Run `scaffold agents generate-all` to regenerate them.
```

The policy stays inline in each file rather than being replaced by a pointer,
because an agent has to act on the rules without a tool call to fetch them. The
stamp is what makes the duplication safe: a copy that has fallen behind is
detectable rather than merely different.

A single-project repository has no canonical file and nothing to drift from.

Personalize with `*.local` overlays (`AGENTS.local.md`,
`.cursor/rules/local.*.mdc`) rather than by gitignoring the team `AGENTS.md`.

---

## Checking a setup

```bash
scaffold doctor            # report; always exits 0
scaffold doctor --strict   # exit non-zero if anything is not clean
```

| Check | Tells you |
|---|---|
| Workspace registry | Registered roots that no longer exist, and projects declared in a `workspace.yaml` but never registered |
| Workspace identity | `workspace.yaml` and the registry naming one workspace differently |
| Routing guidance | Generated rule files stale against the canonical source |
| MCP registration | Legacy per-project entries, directory binding, hardcoded interpreters |
| Version skew | Whether the MCP server runs the same AgentScaffold as your CLI |
| Graph state location | Where the graph resolves, and in-tree databases being ignored |

A `skip` means the check did not apply, and is never a fault.

`doctor` only reads. It never repairs, creates, or migrates, so it is safe to
run on a setup you already believe is broken.

### Version skew is the check to run first

```
FAIL Version skew — The MCP server runs a different agentscaffold than this CLI.
      agentscaffold: launches agentscaffold 0.8.1, this CLI is 0.10.0
      Reinstall agentscaffold into the environment the entry launches, or run
      `scaffold mcp install --migrate` to drop the pinned path.
```

An entry naming an absolute interpreter keeps launching whatever is left at that
path after you rebuild the virtualenv or upgrade. The server still starts; it
just answers with an old AgentScaffold, and nothing else will tell you. The fix
is almost always `scaffold mcp install --migrate` and an editor restart.

---

## Reclaiming space

```bash
scaffold gc            # reports only
scaffold gc --apply    # deletes what it reported
```

Removes state directories for workspaces that are gone and registry entries
pointing at roots that no longer exist. A deleted checkout has no way to reach
into your state directory on the way out, so these accumulate.

**It deletes only what it can prove is orphaned.** Each state directory records
the workspace root it was created for; a directory is removed when that root is
gone, or when the root now resolves to a different workspace id.

A workspace missing from the registry is **not** an orphan — the manifest is the
source of truth, so an unregistered workspace's graph is live and in use.

Directories created before that record existed are reported and kept:

```
kept ws-0000000000cc — no record of its workspace, so it is not provably orphaned
```

This is expected on first upgrade and clears itself once each workspace's graph
is opened again.

Model weights are not reclaimed: they are shared across workspaces and
re-downloadable, so removing them trades a large download for space you did not
ask to free.

---

## Troubleshooting

### A tool call fails with `ambiguous_project`

The call could not be narrowed to one project. That is expected on a
multi-workspace install when neither `working_path` nor `project` was passed.
The refusal names `retry_with` (the arguments that would make the same call
succeed) and `candidates`.

Recover by passing `working_path` pointing at the file you are working on, or
`project` with one of the candidate names, or by calling `scaffold_projects`
(agent) / `scaffold project list` (terminal). If the path is not under any
registered root, register it.

Do not try to "fix" this by adding `--workspace` to the shared MCP entry unless
this machine has only one workspace.

### `scaffold doctor` warns that a project is declared but not registered

A `workspace.yaml` lists a project the user-level registry does not.
Registration snapshots the manifest, so a project added afterwards cannot be
named with `project=` and will not appear among the candidates in a refusal.
Register it with `scaffold project register /path/to/the-new-project`.

### The server reports a deprecation notice at startup

You still have per-project registrations. Nothing is broken — they keep
working — but you are running more servers than you need. See
[Migrating from per-project entries](#migrating-from-per-project-entries).

### My graph disappeared after upgrading

It did not move. Run `scaffold doctor` and read the graph state line. If you
registered a project and now see an unexpectedly empty graph, run
`scaffold workspace migrate-state --apply` to bring the existing one across.

### `doctor` reports an in-tree graph is being ignored

You have both a state-directory graph and a leftover `<repo>/.scaffold/`. The
state one is in use. Delete the leftover, or run
`scaffold workspace migrate-state --restore --apply` if it is the one you wanted.

### The workspace is recorded under two different ids

`workspace.yaml` and the registry disagree. Resolution prefers the manifest, so
the graph keeps working, but the registry names an id that keys nothing. Run
`scaffold project register` from that workspace so the registry adopts the
manifest id.

### Windows and WSL

Path handling follows the shape of the recorded path, not the machine reading it.

| Root looks like | Treated as | Case |
|---|---|---|
| `C:\repo`, `C:/repo` | Windows | Insensitive |
| `\\server\share\repo` | Windows UNC | Insensitive |
| `/mnt/c/repo` (WSL) | POSIX | Sensitive |
| `/home/you/repo` | POSIX | Sensitive |

WSL and Windows keep **separate registries** — they have separate home
directories — so register your projects in whichever environment actually runs
the MCP server.

`C:\repo` and `/mnt/c/repo` are not treated as the same project even when they
are the same directory, because how `/mnt` is mounted cannot be known from here
and guessing wrong would resolve calls to the wrong project. Register the form
you actually work in.

Roots are stored resolved, so symlinks are followed and a listed path may differ
from what you typed. What must not change is the path *flavour*: a `/mnt/...`
root coming back as a drive-letter path, or the reverse, is a bug worth
reporting.

---

## Related

- [CLI Reference](cli-reference.md) — every command and its options
- [Platform Integration](platform-integration.md) — editor setup
- [Configuration](configuration.md) — `workspace.yaml` and `asset_layout`
- [User Guide](user-guide.md) — the workflows these fit into
