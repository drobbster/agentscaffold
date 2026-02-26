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

The pack directory name (e.g. `my_domain`) is the pack identifier used with `scaffold domain add my_domain`.

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
   scaffold domain add my_domain
   ```

3. **Verify installation**: Check that files appear in `docs/ai/prompts/`, `docs/ai/standards/`, and `scaffold.yaml` was updated.

4. **Regenerate AGENTS.md**:

   ```bash
   scaffold agents generate
   ```

   Confirm your reviews and standards are referenced.

5. **Run a plan through the review**: Create a plan that touches your domain and ask the agent to run your review prompt.

## Contributing Back

To contribute a domain pack to the AgentScaffold project:

1. Fork the repository
2. Add your pack under `src/agentscaffold/domains/<pack_name>/`
3. Follow the structure and naming conventions of existing packs
4. Ensure `manifest.yaml` is valid and complete
5. Submit a pull request with a description of the domain and what the pack adds

Existing packs (trading, webapp, mlops, etc.) serve as reference implementations.
