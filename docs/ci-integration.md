# CI Integration

AgentScaffold generates GitHub Actions workflows and task runner files to integrate the framework into your CI pipeline.

## scaffold ci setup

From your project root:

```bash
scaffold ci setup
```

This generates files based on your `scaffold.yaml` configuration. Run it after changing CI-related settings (e.g. enabling semi-autonomous, toggling plan lint).

## Generated Workflows

### ci.yml (main CI)

Runs on push and pull request to `main`:

- Checkout and Python setup
- Install dependencies (`pip install -e ".[dev]"`)
- Lint (`ruff check .`)
- Test (`pytest -q`)
- Study lint (`scaffold study lint`) if `ci.study_lint: true`
- Plan lint (`scaffold plan lint`) if `ci.plan_lint: true` (strict rigor)

### security.yml (security scanning)

Runs on push and pull request to `main` when `ci.security_scanning: true`:

- Bandit SAST (`bandit -r src/ -ll`)
- TruffleHog for secret detection (`trufflesecurity/trufflehog` with `--only-verified`)

### semi-autonomous-pr.yml (agent PR validation)

Generated when `semi_autonomous.enabled: true` and `ci.semi_autonomous_pr_checks: true`. Runs on pull requests that:

- Have the `agent-created` label, or
- Have a branch name starting with `agent/`

Steps:

- Checkout and Python setup
- Install dependencies
- `scaffold validate --check-safety-boundaries`
- `scaffold validate --check-session-summary`
- Full test suite
- Lint

When semi-autonomous is enabled, `scaffold ci setup` also generates:

- `.github/pull_request_template.md` (PR template for agent PRs)
- `scripts/notify.py` (notification helper script)

## Customizing Generated Workflows

Generated files are overwritten each time you run `scaffold ci setup`. To customize:

1. **Edit after generation**: Modify the generated YAML files. Re-running `scaffold ci setup` will overwrite them, so document your changes or maintain a patch.

2. **Add separate workflows**: Create additional workflow files (e.g. `.github/workflows/custom.yml`) that run alongside the generated ones. The generator does not touch files it did not create.

3. **Adjust scaffold.yaml**: Toggle `security_scanning`, `study_lint`, `plan_lint`, and `semi_autonomous_pr_checks` to control what gets generated.

## Running scaffold validate in CI

Add a validation step to any workflow:

```yaml
- name: Validate
  run: scaffold validate
```

`scaffold validate` runs all checks: integration (architecture layer violations), prohibitions,
governance format (study frontmatter, learnings table structure), plan lint (active plans only),
secrets scanning, and retrospective completeness.

For agent-created PRs, use the optional flags:

```yaml
- name: Validate safety boundaries
  run: scaffold validate --check-safety-boundaries
- name: Validate session summary
  run: scaffold validate --check-session-summary
```

### Pre-edit validation (hooks)

The `--pre-edit` flag runs a fast subset (integration + prohibitions + active plan lint) suitable
for PreToolUse hooks that must return quickly:

```yaml
enforcement:
  rules:
    - event: PreToolUse
      matcher: "Edit|Write|NotebookEdit"
      command: scaffold validate --pre-edit
```

This blocks edits that violate architecture constraints or have malformed active plans, without
running slower checks like governance format or secrets scanning.

### Parallel test and validate jobs

For larger projects, run tests and validation in parallel:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - run: pip install uv && uv venv && uv sync --locked --extra dev
      - run: uv run pytest -q

  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - run: pip install uv && uv venv && uv sync --locked --extra dev
      - run: uv run scaffold validate
```

Ensure `agentscaffold` is installed (e.g. `pip install agentscaffold` or `pip install -e ".[dev]"` if it is a project dependency).

## Task Runner Integration

Generate task runner files:

```bash
scaffold taskrunner setup
```

Options:

```bash
scaffold taskrunner setup --format both    # justfile + Makefile (default)
scaffold taskrunner setup --format justfile
scaffold taskrunner setup --format makefile
```

### justfile

Provides targets such as:

- `lint-plans`, `plan-status`, `check-retros`, `validate`, `study-lint`, `metrics`
- `agents-generate`, `cursor-setup`
- `lint`, `format`, `test`, `test-cov`
- `ci-setup`
- `validate-safety`, `validate-session` (when semi-autonomous enabled)

### Makefile

Similar targets for environments where `make` is preferred over `just`.

### Usage

```bash
just validate
just lint-plans
just test
```

Or with Make:

```bash
make validate
make lint-plans
make test
```

---

## Troubleshooting

### `scaffold validate` fails because the graph is missing

`scaffold validate` does not require the graph. If a step that uses the graph fails with a missing `.scaffold/graph.duckdb`, run `scaffold index` first or remove the graph-dependent step from CI.

### Graph freshness gate blocks the CI run

If `scaffold validate` fails with a staleness error, add a graph indexing step before validation:

```yaml
- name: Build graph
  run: scaffold index
- name: Validate
  run: scaffold validate
```

For faster CI, use `--incremental` after a full index is cached:

```yaml
- name: Refresh graph
  run: scaffold index --incremental
```

### `scaffold validate --check-session-summary` fails

This check expects a session summary file in `.scaffold/sessions/`. It only makes sense for agent-created PRs. If the check fires on a human PR, ensure the workflow condition is correct:

```yaml
if: contains(github.event.pull_request.labels.*.name, 'agent-created') ||
    startsWith(github.head_ref, 'agent/')
```

### `scaffold validate --check-safety-boundaries` fails intermittently

This check reads `.scaffold/safety_boundaries.yaml`. If the file was not committed or is missing on the CI runner, the check fails. Ensure `.scaffold/safety_boundaries.yaml` is tracked in git.
