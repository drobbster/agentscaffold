# Semi-Autonomous Mode Guide

Semi-autonomous mode enables your AI agent to run from the CLI, a script, or CI without a human in the loop. The agent follows the same plan lifecycle and gates but adds session tracking, safety boundaries, notification hooks, and cautious execution rules.

## What Semi-Autonomous Mode Is

Semi-autonomous mode is for:

- Overnight or batch agent runs (e.g. "implement plan 042")
- CI-triggered agents that create PRs from plan execution
- Scripted workflows where the agent executes plans and opens PRs for human review

The agent still follows AGENTS.md, the plan lifecycle, and all gates. It does not bypass reviews or approvals. Plans that require approval are not executed; the agent creates a PR with the plan review and notifies for human approval.

## What It Is Not

- **Not fully autonomous**: The agent does not merge PRs, deploy, or make irreversible decisions without human review
- **Not a replacement for interactive work**: Complex design decisions and architecture reviews remain human-led
- **Not a different agent**: The same AGENTS.md applies; the agent self-detects execution mode from context

## How It Works

The agent reads AGENTS.md, which contains both interactive and semi-autonomous rules. When invoked from CLI, script, or CI (without an IDE conversation), the agent infers semi-autonomous mode and applies the additional protocol: session tracking, safety boundaries, notifications, and cautious execution.

Both profiles coexist in the same AGENTS.md. No separate config file is needed for the agent to choose the mode.

## Enabling Semi-Autonomous Mode

### During Init

```bash
scaffold init
# When prompted:
# Execution profile (interactive / semi_autonomous) [interactive]: semi_autonomous
```

### After Init

Edit `scaffold.yaml`:

```yaml
profile: semi_autonomous
# or keep profile: interactive and set:
semi_autonomous:
  enabled: true
```

Then regenerate agent files:

```bash
scaffold agents generate
scaffold agents cursor
```

## The Six Enhancements

### 1. Session Tracking

The agent creates a session file at `docs/ai/state/sessions/{date}-{plan}.md` and logs:

- Decisions made and rationale
- Issues encountered
- What was completed and what was deferred
- Context handoff for the next session

Session files use the template at `docs/ai/templates/session_summary.md`. The agent writes a summary at session end covering what was done, what was deferred, and any escalations.

### 2. Safety Boundaries

Paths are restricted in semi-autonomous mode:

**Read-only (agent must not modify):**

- `docs/ai/system_architecture.md`
- `scaffold.yaml`
- `.github/`

**Require approval (agent must not include in automated changes; separate PR):**

- `infra/`
- `docs/security/`

Configure in `scaffold.yaml`:

```yaml
semi_autonomous:
  safety:
    read_only_paths:
      - "docs/ai/system_architecture.md"
      - "scaffold.yaml"
      - ".github/"
    require_approval_paths:
      - "infra/"
      - "docs/security/"
```

### 3. Notification Hooks

Notifications are sent when configured events occur. Default channel: `github_issue` (creates a GitHub issue via `gh` CLI).

Configure in `scaffold.yaml`:

```yaml
semi_autonomous:
  notifications:
    enabled: true
    channel: github_issue   # or stdout, slack
    slack_webhook_env: SLACK_WEBHOOK_URL
    notify_on:
      - plan_complete
      - escalation
      - validation_failure
      - approval_required
```

Channels:

- `stdout`: Print to console
- `github_issue`: `gh issue create` (requires GitHub CLI)
- `slack`: POST to webhook URL from env var

Send a test notification:

```bash
scaffold notify plan_complete "Plan 042 completed successfully"
```

### 4. Structured PR Output

When semi-autonomous is enabled, `scaffold ci setup` generates a PR template at `.github/pull_request_template.md`. Agent-created PRs should include:

- Plan reference
- Session summary link
- Changes description
- Test results
- Deviations from plan
- Review checklist

The semi-autonomous workflow (see CI Integration) can require that PRs from agent branches include a session summary.

### 5. Enhanced CI Gate

When `ci.semi_autonomous_pr_checks: true`, `scaffold ci setup` generates `.github/workflows/semi-autonomous-pr.yml`. This workflow runs on PRs that:

- Have the `agent-created` label, or
- Have a branch name starting with `agent/`

It runs:

- `scaffold validate --check-safety-boundaries`
- `scaffold validate --check-session-summary`
- Full test suite
- Lint

### 6. Cautious Execution Rules

In semi-autonomous mode, the agent:

- Chooses the more conservative option when uncertain and documents the alternative
- Never pushes to main/master; always works on a feature branch and creates a PR
- On validation failure: attempts to fix up to `max_fix_attempts` (default 2) times, then stops and notifies
- If changes exceed the File Impact Map by more than `max_new_files_before_escalation` (default 5) new files, escalates before proceeding
- Runs `scaffold validate` before creating a PR
- Does not execute plans with Approval Required: Yes; creates a PR with the plan review and notifies
- Does not add, remove, or modify dependencies without explicit plan authorization

Configure in `scaffold.yaml`:

```yaml
semi_autonomous:
  cautious_execution:
    max_fix_attempts: 2
    max_new_files_before_escalation: 5
```

## Example Workflow: Overnight CLI Agent

1. **Evening**: Ensure a plan is Ready. Start the agent from CLI:

   ```bash
   # Example (actual command depends on your agent setup)
   cursor agent --plan 042 --mode semi-autonomous
   # or
   python scripts/run_agent.py --plan 042
   ```

2. **Agent runs**: Executes plan steps, creates session file, writes context handoff.

3. **Morning**: Review the agent's PR:
   - Check session summary in `docs/ai/state/sessions/`
   - Review PR description and changes
   - Run `scaffold validate` locally
   - Merge or request changes

## Reviewing Agent PRs

1. **Session summary**: Read `docs/ai/state/sessions/{date}-{plan}.md` for decisions, issues, and handoff.
2. **Plan alignment**: Verify execution steps are checked and changes match the File Impact Map.
3. **Safety**: Confirm no read-only paths were modified (`scaffold validate --check-safety-boundaries`).
4. **Tests and lint**: CI runs these; re-run locally if needed.
5. **Retrospective**: If the plan is complete, ensure a retrospective was done.

## Troubleshooting

**Agent did not create a session file**

- Verify `semi_autonomous.enabled: true` and `session_tracking: true`
- Ensure `docs/ai/state/sessions/` exists (created by `scaffold init` when profile is semi_autonomous)

**Notifications not sent**

- Check `notifications.enabled` and `notify_on` includes the event
- For `github_issue`: ensure `gh` CLI is installed and authenticated
- For `slack`: set `SLACK_WEBHOOK_URL` (or configured env var)

**CI workflow not running on agent PRs**

- Add label `agent-created` to the PR, or use a branch name starting with `agent/`
- Ensure `semi_autonomous_pr_checks: true` in `scaffold.yaml` and re-run `scaffold ci setup`

**Agent modified a read-only path**

- Run `scaffold validate --check-safety-boundaries` in CI to catch this
- Review the safety config and add any paths that must be protected
