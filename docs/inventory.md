# System inventory

The system inventory lists what a project runs: scheduled and manual jobs,
services, workflows and scripts. Each component has an owner plan, an
architecture layer, a roadmap stage and a lifecycle (experimental, active,
shadow, paused, deprecated). Checks keep the list honest, orientation surfaces
lifecycle debt, and a monthly review keeps it current.

The inventory is off until `scaffold.yaml` enables it. New projects from
`scaffold init` have it on in warn mode.

## Turn it on

```bash
scaffold inventory enable --dry-run   # report each step, write nothing
scaffold inventory enable
```

`enable` writes only what is missing, so running it again changes nothing:

1. `scaffold.yaml`: adds the `inventory:` block, or sets `enabled: true` in the
   one you have. It adds `enforcement: warn`, `review_overdue: error`,
   `plan_adoption_date` (today) and `roadmap.path` when it finds a roadmap with
   a stage table. When it detects files for a collector you have not
   configured (for example a `prefect.yaml`), it lists that collector too.
   Keys you already set are left alone.
2. `.github/workflows/inventory-review.yml`, when `.github/workflows/` exists.
3. The inventory (`init`) or an update of it (`refresh`), plus the derived file.
4. `docs/ai/prompts/architecture_review.md`.
5. The Component Lifecycle section of `AGENTS.md`, inserted before
   `## Runbook Rules`. No existing section is changed.
6. The graph's component nodes, when a graph exists.
7. A summary: components by kind, how many owners and layers resolved, and
   what to do next.

Commit `scaffold.yaml`, `docs/ai/system_inventory.yaml` and
`docs/ai/system_inventory.derived.yaml` together.

## Two files: what people decide, and what is derived

`docs/ai/system_inventory.yaml` is yours. It holds each component's identity
(from the collectors) and the decisions a person makes: lifecycle, reason,
review_by, exit_criteria, replaced_by and reads.

`docs/ai/system_inventory.derived.yaml` is machine-owned and rewritten whole by
`init`, `refresh` and `enable`, like a lock file. It holds each component's
owner plan, layer and roadmap stage with the rule that produced each, and the
current roadmap stage. Do not edit it.

The effective value of a field is the pin in your file if there is one, else
the derived value, else unresolved. To override a derivation, set the field in
your file:

```yaml
components:
  - id: compose:api
    kind: service
    name: api
    source: deploy/compose.yaml
    entrypoint: python -m api
    owner_plan: "42"        # a pin: wins over the derived owner
    lifecycle: active
    since: "2026-01-12"
```

Before you downgrade AgentScaffold, run `scaffold inventory refresh
--pin-derived` to copy the derived values into your file, because older
versions do not read the derived file.

## How owners, layers and stages are derived

Owner plan, first match wins:

1. An annotation at the component's source (see below).
2. The plan whose File Impact Map creates the component's entrypoint file.
3. The most recent Complete plan whose File Impact Map lists that file.
4. The most recent commit that touched the source and cites a plan.

Other plans that touched the component are listed in `touched_by`.

Layer: an annotation, else the owner plan's `Architecture Layer` line, else
`inventory.layer_paths`, else `inventory.kind_layers`.

Roadmap stage: an annotation, else the owner plan's `Roadmap Stage` line. The
current stage comes from the roadmap document (below).

`since` is the date of the first commit that added the component, for new
entries.

## Annotations: map a component where it is defined

When no plan names a component (an infrastructure image, for example), write
the owner and layer next to its definition. The mapping then travels with the
change that adds the component.

Compose service labels:

```yaml
services:
  cache:
    image: redis:7
    labels:
      agentscaffold.owner_plan: "42"
      agentscaffold.layer: "2"
```

Prefect deployment tags:

```yaml
deployments:
  - name: nightly-load
    entrypoint: flows/load.py:run
    tags: ["plan:42", "layer:3", "stage:2"]
```

A GitHub workflow comment line:

```yaml
# agentscaffold: owner_plan=42 layer=6
name: Release
```

## Roadmap stage

Point `inventory.roadmap.path` at a markdown document with a table that has a
`Stage` column and a `Gate met` column. The current stage is the stage after
the highest stage whose Gate met cell starts with "Yes".

```markdown
| Stage | Goal | Gate | Gate met |
|-------|------|------|----------|
| 1 | Prototype | Runs end to end | Yes, 2026-02-01 |
| 2 | Pilot | Two weeks without incident | No |
| 3 | Production | Pilot review passed | No |
```

Here the current stage is 2. A `current_roadmap_stage` in the inventory file
pins it instead.

## Configuration

```yaml
inventory:
  enabled: true
  path: docs/ai/system_inventory.yaml
  enforcement: warn                 # fail: errors exit non-zero
  warn_until: null                  # a date after which warn behaves as fail
  review_overdue: error             # INV-009 severity: warn or error
  mapping_strict_after: null        # a date after which INV-011 is an error
  plan_adoption_date: "2026-01-01"  # plan lint applies the inventory fields from here
  roadmap:
    path: docs/ai/strategy_roadmap.md
  layer_paths:                      # layer id -> globs, for layer derivation
    "2": ["src/storage/**"]
  kind_layers:                      # kind -> layer, the last resort
    workflow: "6"
  collectors:                       # omit to use the defaults plus domain packs
    - compose
    - name: prefect
      sources: ["ops/**/prefect.yaml"]
```

Collectors and the files they read by default:

| Collector | Default sources |
|---|---|
| `compose` | `**/docker-compose*.yml`, `**/compose.yml` (and `.yaml`) |
| `prefect` | `**/prefect.yaml` |
| `github_workflows` | `.github/workflows/*.yml` (and `.yaml`) |
| `pyproject_scripts` | `pyproject.toml` |

`**` searches the whole project and skips what the indexer ignores. Without a
`collectors` list, `compose`, `github_workflows` and `pyproject_scripts` run,
plus any your domain packs enable. A collector that finds nothing is reported as
a notice, not an error.

A compose service with an `image` and no `build:` is recorded with that image;
its entrypoint is its `command`, else its `entrypoint`, else the Dockerfile
when it builds one. Either an entrypoint or an image satisfies INV-003.

## Checks

| Check | Default | Meaning |
|---|---|---|
| INV-001 | error | A collected component is missing from the inventory |
| INV-002 | error | An inventory entry no source declares (a ghost) |
| INV-003 | error | Required fields for the lifecycle, valid dates and paths |
| INV-004 | error | `review_by` has passed |
| INV-005 | error | `owner_plan` names no plan file |
| INV-006 | error | Scheduled jobs share an entrypoint and parameters |
| INV-007 | warning | An active component is needed only from a later roadmap stage |
| INV-008 | warning | A change edits what a paused or deprecated component reads |
| INV-009 | warning | The architecture review is overdue (`review_overdue` sets it) |
| INV-010 | error | Ids are unique and `<prefix>:<name>` |
| INV-011 | warning | An owner plan or layer is unresolved (`mapping_strict_after`) |

INV-007 runs only when both stages are known. In warn mode every finding is
reported and the command exits 0.

## The monthly review

```bash
scaffold inventory review                    # markdown packet
scaffold inventory review --format json
scaffold inventory review --exit-code        # exit 1 when there is debt or an error
scaffold inventory review --record           # stamp last_architecture_review with today
```

The packet has lifecycle debt, health, unresolved owners and layers with the
cheapest fix for each, duplicate candidates, unreferenced entrypoints, and
derivation coverage. Duplicate and unreferenced items are candidates
(`unconfirmed`): confirm before acting. Health reads an optional snapshot file
(`inventory.health_snapshot`); without one it says "not evaluated" rather than
healthy.

The `docs/ai/prompts/architecture_review.md` prompt walks an agent through the
packet. Run `--record` when the review is done.

`.github/workflows/inventory-review.yml` runs on the first of each month and on
demand. It reports derivation drift, builds the packet, and keeps one issue
titled "System inventory review" open while there is debt, closing it when the
review is clean. It needs `issues: write`. Edit it freely; AgentScaffold never
overwrites it.

## Agents and orientation

- `scaffold_orient` recommends the architecture review when it is overdue or
  unrecorded, else the components past `review_by`, as at most one action.
- `scaffold_inventory` (read-only) answers `mode: check`, `mode: review`, or
  `mode: component` with a `component_id`, which shows the effective owner,
  layer and stage and where each came from.
- `scaffold doctor` reports a missing inventory, an overdue review, collector
  globs that match nothing, and a missing review workflow.

## Getting to every component mapped

An unresolved owner or layer is debt. After the first review clears the
backlog, set `mapping_strict_after` to a date so new unresolved components fail
the check from then on. The cheapest fix for each one is in the review packet.
