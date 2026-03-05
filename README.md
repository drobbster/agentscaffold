# AgentScaffold

Structured AI-assisted development framework with plan lifecycle, review gates, and continuous improvement.

## What Is This?

AgentScaffold gives your AI coding agent (Cursor, Claude Code, Codex, aider, etc.) a structured development workflow. It generates an `AGENTS.md` file that teaches your agent to:

- Follow a **plan lifecycle** (Draft -> Review -> Ready -> In Progress -> Complete) with configurable gates
- Run **devil's advocate** and **expansion reviews** before execution
- Maintain **interface contracts** between modules
- Complete **retrospectives** after every plan, feeding learnings back into the process
- Track state across sessions via **workflow state**, **learnings tracker**, and **plan completion log**

## Quick Start

```bash
pip install agentscaffold
cd my-project
scaffold init
```

The `init` command scaffolds your project with:

- `docs/ai/` -- templates, prompts, standards, state files
- `AGENTS.md` -- rules your AI agent follows automatically
- `.cursor/rules.md` -- Cursor-specific rules
- `scaffold.yaml` -- your project's framework configuration
- `justfile` + `Makefile` -- task runner shortcuts
- `.github/workflows/` -- CI with security scanning

## Execution Profiles

**Interactive** (default): Human + AI agent in an IDE conversation. The agent follows AGENTS.md, asks questions when uncertain.

**Semi-Autonomous** (opt-in): Agent invoked from CLI/CI without a human present. Adds session tracking, safety boundaries, notification hooks, structured PR output, and cautious execution rules.

Both profiles coexist in the same AGENTS.md. The agent self-selects based on invocation context.

## Rigor Levels

- **Minimal**: Lightweight gates for prototypes and small projects
- **Standard**: Full plan lifecycle with reviews, contracts, and retrospectives
- **Strict**: All gates enforced, all plans require approval

## Domain Packs

Domain packs add specialized review prompts, standards, and approval gates:

| Pack | Focus |
|------|-------|
| trading | Quantitative finance, RL, traceability |
| webapp | UX/UI, accessibility, performance budgets |
| mlops | Model lifecycle, experiment tracking, drift detection |
| data-engineering | Pipeline quality, schema evolution, SLAs |
| api-services | API design, backward compatibility, contract testing |
| infrastructure | IaC, deployment safety, cost analysis |
| mobile | Platform guidelines, offline-first, app store compliance |
| game-dev | Game loops, ECS, frame budgets |
| embedded | Memory constraints, real-time deadlines, OTA safety |
| research | Reproducibility, statistical rigor, experiment protocol |

```bash
scaffold domain add trading
scaffold domain add webapp
```

## CLI Commands

```bash
scaffold init                          # Set up framework
scaffold plan create my-feature        # Create a plan
scaffold plan lint --plan 001          # Validate a plan
scaffold plan status                   # Dashboard of all plans
scaffold validate                      # Run all checks
scaffold retro check                   # Find missing retrospectives
scaffold agents generate               # Regenerate AGENTS.md
scaffold agents cursor                 # Regenerate .cursor/rules.md
scaffold import chat.json --format chatgpt  # Import conversation
scaffold ci setup                      # Generate CI workflows
scaffold taskrunner setup              # Generate justfile + Makefile
scaffold metrics                       # Plan analytics
```

## Documentation

Full documentation is in [docs/](docs/):

- [User Guide](docs/user-guide.md) -- interaction patterns and session workflow
- [Getting Started](docs/getting-started.md)
- [Configuration Reference](docs/configuration.md)
- [Domain Packs](docs/domain-packs.md)
- [Semi-Autonomous Guide](docs/semi-autonomous-guide.md)
- [CI Integration](docs/ci-integration.md)

## License

MIT
