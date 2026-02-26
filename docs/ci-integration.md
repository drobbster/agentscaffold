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

For agent-created PRs, use the optional flags:

```yaml
- name: Validate safety boundaries
  run: scaffold validate --check-safety-boundaries
- name: Validate session summary
  run: scaffold validate --check-session-summary
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
