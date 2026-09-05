# Domain Packs

Domain packs add specialized review prompts, standards, and approval gates to your project. They tailor AGENTS.md and the plan lifecycle to your domain (e.g. quantitative trading, web apps, MLOps).

## What Domain Packs Are

A domain pack is a bundle of:

- **Review prompts**: Multi-phase prompts for plan review (e.g. quant architect review, product design review)
- **Standards**: Actionable patterns with examples (e.g. traceability, accessibility)
- **Security templates**: Threat model templates when applicable
- **Approval gates**: Additional change types that require human approval

When you install a domain pack, its files are copied into your project and its settings are merged into `scaffold.yaml`. The agent then references these prompts and standards during plan review and execution.

## Available Packs

| Pack | Description | Adds |
|------|-------------|------|
| trading | Quantitative finance, RL, trading systems | quant_architect, quant_architect_implementation reviews; traceability, rl_patterns, rl_reward_shaping, performance_patterns, concurrency_patterns; financial_calculations approval |
| webapp | Web applications, UX/UI | product_design review; accessibility, frontend_testing, performance_budgets, responsive_design |
| mlops | Model lifecycle, experiment tracking | model_lifecycle, experiment_design, model_governance reviews; experiment_tracking, model_versioning, data_drift, feature_store, model_serving; model_deployment approval |
| data_engineering | Pipelines, schema evolution | data_quality, pipeline_design reviews; backfill_procedures, data_quality, idempotency, schema_evolution, sla_monitoring |
| api_services | API design, backward compatibility | api_design, contract_testing reviews; backward_compatibility, error_response, openapi_validation, rate_limiting, versioning_strategy |
| infrastructure | IaC, deployment safety | iac_review, deployment_safety, cost_analysis reviews; iac_patterns, monitoring_alerting, rollback_procedures, secret_management; infrastructure approval |
| mobile | Platform guidelines, offline-first | app_store_compliance, platform_review reviews; deep_linking, offline_first, performance_profiling, push_notifications |
| game_dev | Game loops, ECS, frame budgets | game_loop, performance_profiling reviews; asset_pipeline, ecs_patterns, frame_budget, state_sync |
| embedded | Memory, real-time, OTA | memory_constraint, realtime_deadline reviews; interrupt_handling, memory_management, ota_update, power_consumption |
| research | Reproducibility, statistical rigor | reproducibility, statistical_rigor reviews; citation_tracking, data_archival, experiment_protocol, random_seed |

## Installing a Domain Pack

From your project root:

```bash
scaffold domains add trading
```

Use `scaffold domains ...` commands for setup and configuration. For day-to-day usage in
chat sessions, use natural-language prompts so the agent applies domain prompts through
its governance/review flow.

This will:

1. Copy prompts to `docs/ai/prompts/`
2. Copy standards to `docs/ai/standards/`
3. Copy security templates to `docs/security/` (if present)
4. Update `scaffold.yaml` with the pack's reviews, standards, and approval gates

List available and installed packs:

```bash
scaffold domains list
```

## What Gets Added to Your Project

| Source | Destination |
|--------|-------------|
| `domains/<pack>/prompts/*.md.j2` | `docs/ai/prompts/<name>.md` |
| `domains/<pack>/standards/*.md.j2` | `docs/ai/standards/<name>.md` |
| `domains/<pack>/security/*.md.j2` | `docs/security/<name>.md` |

Existing files are not overwritten. If a file already exists, the install skips it.

In a workspace with `asset_layout.layout: shared_workspace`, domain
pack prompts, standards, and security templates install to the **workspace-shared**
paths by default (resolved via the same path rules as the rest of the toolchain),
so a pack is installed once for the whole workspace rather than duplicated per
project. A project that has customized the corresponding `graph.*` path keeps its
domain assets project-local (the per-project escape hatch).

## How Domain Packs Affect AGENTS.md

Domain-pack references live in the **scaffolded governance manual** (the unmanaged half of `AGENTS.md`), not in the routing block. A fresh `scaffold init` after the pack is configured writes them once. On an existing project, `scaffold agents generate` will not rewrite that manual.

To pull pack references into a manual you already own:

```bash
scaffold agents diff-manual           # dry run
scaffold agents diff-manual --apply   # unambiguous sections only
```

Those references include domain review prompts in the Review -> Ready gate, domain standards, approval gates, and domain-specific review criteria. The agent still reads `AGENTS.md` and applies them during plan review and execution.

## NL Prompt Patterns After Installation

After installing packs, trigger domain behavior conversationally:

- "Review plan 042 like a quant architect and challenge risk assumptions."
- "Before implementation, run product design and accessibility scrutiny for this plan."
- "Do a full adversarial review with both trading and webapp perspectives."
- "Re-check the plan for domain-specific failure modes before we proceed."

These prompts should route the agent into the same governance gates as explicit command
flows while reducing interaction friction.

## Using Multiple Domain Packs

You can install multiple packs. For example, a trading web app might use:

```bash
scaffold domains add trading
scaffold domains add webapp
```

Both packs' prompts and standards are merged. When a plan touches trading and UI:

- The agent runs quant_architect review (trading) and product_design review (webapp)
- Both domains' standards apply
- Approval gates from both packs are enforced

Prompt example for dual-domain plans:

> "Let's review this plan with quant architect and product design lenses before implementation."

If prompts or standards from different packs conflict, the agent uses the most specific one for the plan's scope. For overlapping concerns, document your preference in the plan or in `docs/ai/standards/`.

## Creating Custom Domain Packs

To create your own domain pack, see [Creating Domain Packs](creating-domain-packs.md).
