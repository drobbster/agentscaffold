# Commands Reference

## Framework Commands

Scaffold CLI commands for plan and project management:

```bash
# Initialize project
scaffold init

# Plan management
scaffold plan create
scaffold plan status
scaffold plan lint

# Retrospective checks
scaffold retro check
scaffold retro check --extract
scaffold retro check --warn

# Study management
scaffold study create
scaffold study list

# Spike creation
scaffold spike create

# Validation
scaffold validate
```

## Quality Commands

```bash
# Format
ruff format .

# Lint
ruff check .

# Test
pytest -q
uv run pytest -q

# Type check (optional)
mypy .
```

## Validation Commands

```bash
# Plan cohesion
python scripts/lint_plan_cohesion.py
python scripts/lint_plan_cohesion.py --plan XXX

# Integration verification
python scripts/verify_integration.py
python scripts/verify_integration.py --plan XXX

# Pre-commit
pre-commit run --all-files
```
