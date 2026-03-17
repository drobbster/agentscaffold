# Platform Integration Guide

AgentScaffold works with any AI coding agent that reads project files. The framework has two integration surfaces:

1. **AGENTS.md** -- A rules file at the project root. Any agent that reads project context will pick this up automatically.
2. **MCP server** -- A stdio-based server exposing the knowledge graph as tools. Any MCP-compatible client can connect.

This guide covers setup for specific platforms.

---

## Universal Setup (All Platforms)

Every platform starts with the same steps:

```bash
pip install agentscaffold[all]   # or agentscaffold[graph] for lighter install
cd my-project
scaffold init
scaffold index                    # Build knowledge graph
```

After this, your project has `AGENTS.md` at the root and `.scaffold/graph.db` with the indexed knowledge graph. The agent rules in `AGENTS.md` work immediately with any agent that reads project files.

## Verify NL Intent Routing

Before long sessions, run a quick smoke check in chat to confirm the agent is interpreting
intent and routing to MCP workflows (or falling back cleanly when needed):

1. "Let's prepare to review plan 042 with evidence."
   - Expected behavior: review-prep/composite context workflow.
2. "Where did we leave off and what are blockers?"
   - Expected behavior: orientation/status workflow.
3. "Show me the decision chain behind plan 042."
   - Expected behavior: ADR/spike/study decision-context workflow.

If routing is weak or MCP tools are unavailable:

- Rebuild freshness: `scaffold index --incremental`
- Regenerate rules: `scaffold agents generate` and platform-specific rules command
- Continue in hybrid mode: explicit CLI commands for critical checks + NL orchestration

This verification should take under two minutes and catches setup drift early.

### Async Freshness (Recommended for Large Repos)

If incremental indexing is heavy in your codebase, enable async freshness in `scaffold.yaml`.
This keeps MCP request-path latency low by scheduling refresh in the background instead of
blocking tool calls.

```yaml
freshness:
  async_enabled: true
  debounce_seconds: 120
  gate_strict: false
  background_queue_enabled: true
```

Operational notes:

- Composite tools are eligible refresh triggers; refresh scheduling is debounced.
- Single-flight locking prevents duplicate refresh jobs during parallel tool usage.
- Tool responses include freshness metadata so the agent can disclose confidence.
- For stricter governance, set `gate_strict: true` to defer gate transitions when freshness
  is stale/unknown.

---

## Skills

Skills are narrowly-scoped best-practice guides (testing, logging, config patterns, etc.) generated from your project's standards files. Each skill becomes a SKILL.md file that AI agents can discover and load on demand.

### How Skills Work

1. You write standards as markdown files in `docs/ai/standards/` (e.g., `testing.md`, `concurrency_patterns.md`).
2. Run `scaffold agents skills` to convert them into SKILL.md files.
3. Output goes to `.claude/skills/` and `.cursor/skills/` with a `SKILLS_CATALOG.md` index.

Agents discover skills via the catalog (progressive disclosure) and load the full skill file when they need detailed guidance for a specific domain.

### Generating Skills

```bash
# Generate skills from all standards
scaffold agents skills

# Preview without writing
scaffold agents skills --dry-run
```

### Auto-Regeneration

If configured in `scaffold.yaml`, skills regenerate automatically when standards files change:

```yaml
enforcement:
  rules:
    - event: PostToolUse
      matcher: "Edit|Write|NotebookEdit"
      command: scaffold agents skills --if-standards-changed
      description: Regenerate skills when standards files are updated
```

The `--if-standards-changed` flag uses a timestamp marker (`.scaffold/.skills_generated`) to skip regeneration when no standards have been modified, keeping the hook fast (~100ms no-op).

### Adding a New Skill

1. Create a markdown file in `docs/ai/standards/` (e.g., `security.md`).
2. Run `scaffold agents skills` (or let the PostToolUse hook pick it up automatically).
3. The new skill appears in `.claude/skills/security.md` and `.cursor/skills/security.md`.

Skills are distinct from AGENTS.md rules: AGENTS.md provides broad governance (plan lifecycle, architecture constraints), while skills provide specific best practices for a domain.

---

## Cursor

Cursor has first-class support. AgentScaffold generates:
- `AGENTS.md` (full governance rules),
- `.cursor/rules.md` (Cursor governance summary),
- `.cursor/rules/agentscaffold.md` (MCP-first tool routing policy + intent map).

### Rules Setup

```bash
scaffold agents generate    # Generate AGENTS.md
scaffold agents cursor      # Generate .cursor/rules.md and .cursor/rules/agentscaffold.md
```

Cursor reads `.cursor/rules.md` and `.cursor/rules/` files automatically when you open the project. The agent also reads `AGENTS.md` when working in agent mode.

### MCP Setup

Add to your Cursor MCP settings (`.cursor/mcp.json` in your project, or global settings):

```json
{
  "mcpServers": {
    "agentscaffold": {
      "command": "scaffold",
      "args": ["mcp"]
    }
  }
}
```

If you installed `agentscaffold` in a virtualenv, use the full path:

```json
{
  "mcpServers": {
    "agentscaffold": {
      "command": "/path/to/venv/bin/scaffold",
      "args": ["mcp"]
    }
  }
}
```

After adding the config, restart Cursor. The MCP tools (`scaffold_context`, `scaffold_search`, `scaffold_impact`, etc.) appear in the agent's tool palette.

---

## Claude Code (Claude CLI)

Claude Code reads `AGENTS.md` automatically when you open a project directory.

### MCP Setup

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "agentscaffold": {
      "command": "scaffold",
      "args": ["mcp"]
    }
  }
}
```

Or configure globally via `claude mcp add`:

```bash
claude mcp add agentscaffold -- scaffold mcp
```

### CLAUDE.md

Generate a Claude-specific routing file from AgentScaffold:

```bash
scaffold agents claude
```

If your project already has `CLAUDE.md` content, merge or append this generated policy and keep a reference to AGENTS.md:

```markdown
Read and follow AGENTS.md at the project root before every task.
```

This keeps a single source of truth while giving Claude its expected entry point.

---

## Windsurf

Windsurf reads `.windsurfrules` at the project root for agent instructions.

### Rules Setup

```bash
scaffold agents windsurf    # Generate .windsurfrules
```

### MCP Setup

Windsurf supports MCP servers. Add to your Windsurf MCP configuration:

```json
{
  "mcpServers": {
    "agentscaffold": {
      "command": "scaffold",
      "args": ["mcp"]
    }
  }
}
```

Consult the Windsurf documentation for the exact config file location (typically in Windsurf's settings UI under MCP).

---

## VS Code + Cline

Cline is a VS Code extension that provides an AI agent with MCP tool support. It reads custom instructions from its settings.

### Rules Setup

In Cline's settings, set the custom instructions to:

```
Read and follow AGENTS.md at the project root before every task.
```

Or paste the full content of AGENTS.md into Cline's custom instructions field if your version doesn't support file references.

### MCP Setup

Cline supports MCP servers natively. In your VS Code settings or Cline configuration:

```json
{
  "cline.mcpServers": {
    "agentscaffold": {
      "command": "scaffold",
      "args": ["mcp"]
    }
  }
}
```

The exact configuration path depends on your Cline version. Check the Cline documentation for current MCP setup instructions.

---

## VS Code + Continue

Continue is another VS Code AI extension with MCP support.

### Rules Setup

Continue reads `.continuerules` or rules from its configuration. Reference AGENTS.md:

```
Read and follow AGENTS.md at the project root before every task.
```

### MCP Setup

In your Continue configuration (`.continue/config.yaml` or the UI):

```yaml
mcpServers:
  - name: agentscaffold
    command: scaffold
    args: ["mcp"]
```

---

## aider

aider reads convention files and can be configured with project-level instructions.

### Rules Setup

Create or add to `.aider.conf.yml`:

```yaml
read: AGENTS.md
```

Or pass it on every invocation:

```bash
aider --read AGENTS.md
```

### MCP

aider does not currently support MCP. The knowledge graph is still useful via the CLI:

```bash
scaffold graph search "data routing"
scaffold review brief 42
scaffold graph stats
```

You can pipe CLI output into aider's context or use it to inform your prompts.

For aider, the practical target mode is **hybrid**: conversational planning and governance
prompts, with explicit CLI graph/review commands for context retrieval.

---

## Codex (OpenAI)

Codex reads `AGENTS.md` at the project root automatically.

### MCP Setup

Codex supports MCP servers. Add to your project configuration:

```json
{
  "mcpServers": {
    "agentscaffold": {
      "command": "scaffold",
      "args": ["mcp"]
    }
  }
}
```

---

## Generic MCP Integration

Any MCP-compatible client can connect to AgentScaffold's knowledge graph. The server uses **stdio transport** (stdin/stdout JSON-RPC).

### Starting the Server

```bash
scaffold mcp
```

This blocks and communicates over stdin/stdout. The client launches this as a subprocess and sends/receives JSON-RPC messages.

### Available Tools

| Tool | Description |
|------|-------------|
| `scaffold_stats` | Codebase health dashboard |
| `scaffold_query` | Execute Cypher queries against the graph |
| `scaffold_search` | Hybrid search (cypher, semantic, or both) |
| `scaffold_context` | Full context for a symbol (definition, callers, layer, plan history) |
| `scaffold_impact` | Blast radius analysis for a file or symbol |
| `scaffold_validate` | Validation checks (staleness, contracts) |
| `scaffold_review_context` | Review context for a plan (brief, challenges, gaps, verification, retrospective) |

### Testing the Connection

To verify the MCP server is working:

```bash
echo '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}' | scaffold mcp
```

This should return a JSON response listing all available tools.

---

## Platform Support Matrix

| Platform | Reads AGENTS.md | MCP Support | Rules File | Status |
|----------|----------------|-------------|------------|--------|
| Cursor | Yes (automatic) | Yes | `.cursor/rules.md` (generated) | Full support |
| Claude Code | Yes (automatic) | Yes | `CLAUDE.md` (optional) | Full support |
| Codex | Yes (automatic) | Yes | `AGENTS.md` (direct) | Full support |
| Windsurf | Via `.windsurfrules` | Yes | `.windsurfrules` (manual) | Full support |
| Cline (VS Code) | Via custom instructions | Yes | Settings UI | Full support |
| Continue (VS Code) | Via config | Yes | `.continuerules` | Full support |
| aider | Via `--read` flag | No | `.aider.conf.yml` | CLI only |

**Full support** means both AGENTS.md rules and MCP knowledge graph tools are available. **CLI only** means the agent follows AGENTS.md rules but uses the CLI instead of MCP for graph queries.
