# Configuration Reference

This document describes every section and field in `scaffold.yaml`. After editing, run `scaffold agents generate` to regenerate AGENTS.md.

## Top-Level Sections

### framework

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| version | string | "1.0" | Framework version (informational) |
| project_name | string | "My Project" | Project name used in templates |
| architecture_layers | int | 6 | Number of layers in system architecture |

### profile

| Value | Description |
|-------|-------------|
| interactive | Human + AI in IDE. Agent asks questions when uncertain. |
| semi_autonomous | Agent invoked from CLI/CI without human. Adds session tracking, safety boundaries, notifications. |

Default: `interactive`

### rigor

| Value | Description |
|-------|-------------|
| minimal | Lightweight gates for prototypes and small projects |
| standard | Full plan lifecycle with reviews, contracts, retrospectives |
| strict | All gates enforced, domain implementation review, approval required |

Default: `standard`

### domains

List of installed domain pack names (e.g. `trading`, `webapp`, `mlops`). Domain packs add review prompts, standards, and approval gates. See [Domain Packs](domain-packs.md).

Default: `[]`

---

## Gates

Gates control transitions between plan lifecycle states: Draft -> Review -> Ready -> In Progress -> Complete.

### gates.draft_to_review

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| plan_lint | bool | true | Require plan lint to pass |
| architecture_layer_check | bool | true | Verify plan maps to a layer in system_architecture.md |

### gates.review_to_ready

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| devils_advocate | bool | true | Require devil's advocate review |
| expansion_review | bool | true | Require expansion/gap analysis review |
| domain_reviews | list[str] | [] | Domain-specific review names (from domain packs) |
| spike_for_high_uncertainty | bool | true | Require spike when plan has high uncertainty |
| interface_contracts | bool | true | Require interface contracts for exports |
| security_review | bool | true | Require security review when applicable |

### gates.ready_to_in_progress

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| review_checklist | bool | true | Require plan review checklist completed |
| approval_gates | bool | true | Require human approval for approval-required changes |
| interactive_gate | bool | true | Require human confirmation when "review it with me" requested |

### gates.in_progress_to_complete

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| all_steps_checked | bool | true | All execution steps must be checked off |
| validation_commands | bool | true | Validation commands must pass |
| tests_pass | bool | true | Tests must pass |
| retrospective | bool | true | Retrospective must be completed |
| domain_implementation_review | bool | false | Domain-specific post-implementation review (e.g. quant_architect_implementation) |

---

## Rigor Presets

Rigor presets override gate defaults. The preset is applied when loading config.

### minimal

- `architecture_layer_check`: false
- `devils_advocate`, `expansion_review`, `spike_for_high_uncertainty`, `interface_contracts`, `security_review`: false
- `review_checklist`, `approval_gates`, `interactive_gate`: false
- `retrospective`: false

### standard

No overrides. Uses default gate values.

### strict

- `security_review`: true
- `approval_gates`: true
- `domain_implementation_review`: true
- `ci.plan_lint`: true

---

## approval_required

Determines which change types require human approval before execution.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| breaking_changes | bool | true | Breaking API/schema changes |
| security_sensitive | bool | true | Auth, crypto, secrets |
| data_migrations | bool | true | Database migrations |
| infrastructure | bool | true | Terraform, Docker, infra |
| external_apis | bool | true | External API integrations |

Domain packs can add approval gates (e.g. `financial_calculations`, `model_deployment`).

---

## standards

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| core | list[str] | ["errors", "logging", "config", "testing"] | Core standards referenced in plans |
| domain | list[str] | [] | Domain-specific standards (from domain packs) |

---

## prohibitions

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| emojis | bool | false | Forbid emojis in code, docs, logs |
| patterns | list[str] | [] | Regex patterns to forbid (e.g. `TODO`, `FIXME`) |

---

## agents

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| agents_md | bool | true | Generate AGENTS.md |
| cursor_rules | bool | true | Generate .cursor/rules.md |

---

## semi_autonomous

Only applies when `profile: semi_autonomous` or `semi_autonomous.enabled: true`.

### semi_autonomous.enabled

| Type | Default | Description |
|------|---------|-------------|
| bool | false | Enable semi-autonomous enhancements |

### semi_autonomous.session_tracking

| Type | Default | Description |
|------|---------|-------------|
| bool | true | Track agent sessions in docs/ai/state/sessions/ |

### semi_autonomous.context_handoff

| Type | Default | Description |
|------|---------|-------------|
| bool | true | Support context handoff between sessions |

### semi_autonomous.safety

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| read_only_paths | list[str] | ["docs/ai/system_architecture.md", "scaffold.yaml", ".github/"] | Paths the agent must not modify |
| require_approval_paths | list[str] | ["infra/", "docs/security/"] | Paths requiring human approval before modification |

### semi_autonomous.notifications

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | true | Enable notification hooks |
| channel | str | "github_issue" | `stdout`, `github_issue`, or `slack` |
| slack_webhook_env | str | "SLACK_WEBHOOK_URL" | Env var for Slack webhook URL |
| notify_on | list[str] | ["plan_complete", "escalation", "validation_failure", "approval_required"] | Events that trigger notifications |

### semi_autonomous.cautious_execution

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| max_fix_attempts | int | 2 | Max auto-fix attempts before escalation |
| max_new_files_before_escalation | int | 5 | Max new files before escalating for review |

---

## import

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| conversation_dir | str | "data/conversations" | Directory for imported conversation files |

---

## task_runner

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| justfile | bool | true | Generate justfile |
| makefile | bool | true | Generate Makefile |

---

## ci

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| provider | str | "github" | CI provider (only `github` supported) |
| security_scanning | bool | true | Generate security workflow (Bandit, TruffleHog) |
| study_lint | bool | true | Run `scaffold study lint` in CI |
| plan_lint | bool | false | Run `scaffold plan lint` in CI (true for strict rigor) |
| semi_autonomous_pr_checks | bool | false | Generate semi-autonomous PR validation workflow |

---

## How Gates Interact with Lifecycle

```
Draft --[draft_to_review]--> Review --[review_to_ready]--> Ready
  |                              |                            |
  | plan_lint                    | devils_advocate            | review_checklist
  | architecture_layer_check     | expansion_review           | approval_gates
                                 | domain_reviews             | interactive_gate
                                 | spike_for_high_uncertainty |
                                 | interface_contracts        |
                                 | security_review            |

Ready --[ready_to_in_progress]--> In Progress --[in_progress_to_complete]--> Complete
                                        |                                    |
                                        |                                    | all_steps_checked
                                        |                                    | validation_commands
                                        |                                    | tests_pass
                                        |                                    | retrospective
                                        |                                    | domain_implementation_review
```

Disabling a gate skips that requirement. For example, `devils_advocate: false` allows a plan to move from Review to Ready without running the devil's advocate prompt.
