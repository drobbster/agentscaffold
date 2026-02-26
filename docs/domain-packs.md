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
scaffold domain add trading
```

This will:

1. Copy prompts to `docs/ai/prompts/`
2. Copy standards to `docs/ai/standards/`
3. Copy security templates to `docs/security/` (if present)
4. Update `scaffold.yaml` with the pack's reviews, standards, and approval gates

List available and installed packs:

```bash
scaffold domain list
```

## What Gets Added to Your Project

| Source | Destination |
|--------|-------------|
| `domains/<pack>/prompts/*.md.j2` | `docs/ai/prompts/<name>.md` |
| `domains/<pack>/standards/*.md.j2` | `docs/ai/standards/<name>.md` |
| `domains/<pack>/security/*.md.j2` | `docs/security/<name>.md` |

Existing files are not overwritten. If a file already exists, the install skips it.

## How Domain Packs Affect AGENTS.md

When you run `scaffold agents generate`, the generated AGENTS.md includes:

- References to domain review prompts in the Review -> Ready gate
- References to domain standards in the Standards Compliance section
- Domain-specific approval gates in the Approval Gates table
- Domain-specific review criteria (e.g. "If trading/risk/backtest plan: Quant architect review")

The agent reads AGENTS.md and applies these rules during plan review and execution.

## Using Multiple Domain Packs

You can install multiple packs. For example, a trading web app might use:

```bash
scaffold domain add trading
scaffold domain add webapp
```

Both packs' prompts and standards are merged. When a plan touches trading and UI:

- The agent runs quant_architect review (trading) and product_design review (webapp)
- Both domains' standards apply
- Approval gates from both packs are enforced

If prompts or standards from different packs conflict, the agent uses the most specific one for the plan's scope. For overlapping concerns, document your preference in the plan or in `docs/ai/standards/`.

## Creating Custom Domain Packs

To create your own domain pack, see [Creating Domain Packs](creating-domain-packs.md).
