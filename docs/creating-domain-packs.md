# Creating Domain Packs

This guide explains how to create custom domain packs for AgentScaffold. Domain packs add review prompts, standards, and approval gates tailored to your domain.

## Domain Pack Structure

A domain pack is a directory with this structure:

```
my_domain/
  manifest.yaml       # Required: pack metadata and config
  prompts/            # Optional: review prompts
    my_review.md.j2
  standards/          # Optional: standards documents
    my_standard.md.j2
  security/           # Optional: threat model templates
    threat_model_my_domain.md.j2
```

The pack directory name (e.g. `my_domain`) is the pack identifier used with `scaffold domains add my_domain`.

## manifest.yaml Format

```yaml
name: my_domain
display_name: "My Domain"
description: "Short description of what this pack adds."

reviews:
  - my_review          # Prompts in prompts/my_review.md.j2 -> docs/ai/prompts/my_review.md

standards:
  - my_standard        # Files in standards/my_standard.md.j2 -> docs/ai/standards/my_standard.md

approval_gates:
  sensitive_operation: true   # Merged into scaffold.yaml approval_required
```

| Field | Required | Description |
|-------|----------|-------------|
| name | Yes | Pack identifier (must match directory name) |
| display_name | No | Human-readable name (default: name) |
| description | No | Shown during install |
| reviews | No | List of prompt names (without .md). Files: `prompts/<name>.md.j2` |
| standards | No | List of standard names. Files: `standards/<name>.md.j2` |
| approval_gates | No | Dict of gate name -> bool. Merged into `approval_required` |

## Configuring Expert Reviewers

Domain packs can declare **expert reviewers** in `scaffold.yaml` (under the project's
`reviews.expert_reviewers` list). Each reviewer becomes a Cursor rule file, a Windsurf
agent stub, and a Claude Code agent file automatically.

```yaml
reviews:
  expert_reviewers:
    - name: quant_architect
      cursor_description: >
        Deep review of trading plans, risk models, and execution logic.
        Focus on correctness of financial calculations and risk bounds.
      file_patterns:
        - "libs/risk/**"
        - "libs/execution/**"
        - "libs/strategy/**"

    - name: devils_advocate
      cursor_description: >
        Adversarial pressure-test of any plan's assumptions and edge cases.
        No file-pattern filter — applies to all plans.
```

### cursor_description

`cursor_description` is displayed as the Cursor agent rule description when an LLM is
asked to pick a reviewer. It appears in the `description:` frontmatter of the generated
`.cursor/rules/<name>.md` file.

- **Write it as a directive to the reviewer**, not a description of them.
- Be specific about what the reviewer focuses on (e.g. "Focus on risk bounds" is better
  than "Reviews risk code").
- If omitted, AgentScaffold generates a fallback description from the reviewer name.

### file_patterns

`file_patterns` is a list of glob patterns. When present:

- The Cursor rule gets `globs: ["libs/risk/**", ...]` in its frontmatter, so Cursor
  activates the reviewer only when those files are in context.
- The `alwaysApply` flag is set to `false` in all cases (reviewers are on-demand, not
  ambient).

When `file_patterns` is absent, the rule still has `alwaysApply: false` but no `globs:`
field — the reviewer is triggered by explicit invocation only.

### Regenerating agent files after changes

After editing `expert_reviewers` in `scaffold.yaml`, regenerate all platform files:

```bash
scaffold agents generate-all
```

This updates `.cursor/rules/`, `.claude/agents/`, and windsurf stub files in one pass.

## Writing Review Prompts

Review prompts follow a multi-phase pattern:

1. **Persona**: Define the reviewer's expertise and mindset
2. **Usage**: When to run this review (plan types, domains)
3. **Output format**: Prose for findings, tables for checklists
4. **Checklist**: Structured questions the agent must answer

Example structure:

```markdown
# My Domain Review

Use this prompt for plans touching [domain scope].

---

## Reviewer Persona

You are a [expert role] with experience in [relevant areas].
Your mindset: [key attitudes]

---

## Usage

Before executing plans involving [X, Y, Z]:
1. Read [relevant docs]
2. Complete this review checklist
3. Document findings

---

## Output Format Guidelines

Use prose for findings and analysis.
Use tables only for pass/fail checklists (short cell values).

---

## Review Checklist

### Section 1: [Topic]
- [ ] Question 1
- [ ] Question 2

### Section 2: [Topic]
...
```

Reference the plan file, system architecture, and interface contracts. The agent will apply this prompt to the current plan.

## Designing Prompts for Natural Invocation

Most users will trigger your pack via conversational prompts, not explicit tool names.
Write prompts so they are easy for an agent to route from natural language:

- Use review titles and phrasing that match how humans ask (e.g., "quant architect review",
  "product design review", "deployment safety review").
- Include a short "When to use" phrase near the top that mirrors likely user requests.
- Keep output instructions deterministic so routing confidence can stay high.

Example natural invocations your prompt should support:

- "Review this plan like a quant architect."
- "Pressure-test this API plan for backward compatibility."
- "Before implementation, run deployment safety checks."

If the naming in `manifest.yaml` and the prompt header diverge too much from user language,
agents are more likely to fall back to generic review behavior.

## Writing Standards

Standards should be actionable with concrete examples:

```markdown
# My Standard

## Purpose

Why this standard exists.

---

## Requirement 1

Description of the requirement.

### Example

```python
# Good
...

# Bad
...
```

### Verification

How to verify compliance (e.g. grep, test, manual check).
```

Include code examples, anti-patterns, and verification steps. The agent references these during implementation.

## Jinja2 Template Variables

Domain pack files use the `.j2` extension. When installed, files are copied into the project and the `.j2` suffix is stripped from the output filename. The content is copied as-is; domain pack files are not rendered at install time.

For static content that works in any project, avoid template variables. If you need project-specific placeholders, document them for the user (e.g. "Replace {{ project_name }} with your project name"). The agent will read the installed markdown files directly.

## Testing Your Domain Pack

1. **Add the pack to the package**: Place your pack under `src/agentscaffold/domains/my_domain/` in the agentscaffold source tree (or use a development install with a symlink).

2. **Install in a test project**:

   ```bash
   cd /path/to/test-project
   scaffold domains add my_domain
   ```

3. **Verify installation**: Check that files appear in `docs/ai/prompts/`, `docs/ai/standards/`, and `scaffold.yaml` was updated.

4. **Update the project-owned manual** (not `scaffold agents generate` -- that
   refreshes routing only):

   ```bash
   scaffold agents diff-manual
   scaffold agents diff-manual --apply
   ```

   Confirm your reviews and standards are referenced in the unmanaged half of
   `AGENTS.md`. On a brand-new project, `scaffold init` writes them once.

5. **Run a plan through the review**: Create a plan that touches your domain and ask the agent to run your review prompt.

## Contributing Back

To contribute a domain pack to the AgentScaffold project:

1. Fork the repository
2. Add your pack under `src/agentscaffold/domains/<pack_name>/`
3. Follow the structure and naming conventions of existing packs
4. Ensure `manifest.yaml` is valid and complete
5. Submit a pull request with a description of the domain and what the pack adds

Existing packs (trading, webapp, mlops, etc.) serve as reference implementations.
