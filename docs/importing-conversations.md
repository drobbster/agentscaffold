# Importing AI Conversations

AgentScaffold can import AI conversation exports into your project. Use this to seed architectural vision, preserve brainstorming, or bring design decisions from external chats into your docs.

## Why Import Conversations

- **Seed architectural vision**: Import a ChatGPT or Claude conversation where you designed the system and save it as a reference in `docs/ai/` or `data/conversations/`
- **Preserve brainstorming**: Keep design discussions, trade-off analysis, or prompt iterations as project artifacts
- **Onboard the agent**: Give your agent context from prior conversations by placing imported content where it will be read (e.g. product vision, architecture notes)

## Supported Formats

| Format | Extension | Detection |
|--------|-----------|-----------|
| ChatGPT | .json | Auto-detected from structure (mapping, message) |
| Claude | (stub) | Use `--format claude` |
| Markdown | .md | Auto-detected for .md files |

ChatGPT exports are JSON files with a `mapping` or `message` structure. Markdown files are treated as plain text and copied through.

## Exporting from ChatGPT

1. Open ChatGPT in a browser
2. Go to **Settings** (profile menu) -> **Data Controls** -> **Export Data**
3. Request an export; you will receive an email with a download link
4. Download and extract the archive
5. Locate the conversation file (JSON) -- this typically contains all your conversations

## Browsing Your Export

A ChatGPT export usually contains many conversations. Before importing, list what's in the file:

```bash
scaffold import conversations.json --list
```

This prints a table of all conversations with their title, message count, and date:

```
              Conversations in conversations.json
 #   | Title                          | Messages | Date
-----|--------------------------------|----------|-------------------
 1   | Architecture brainstorm        | 42       | 2026-01-15 10:30 UTC
 2   | Debug auth flow                | 18       | 2026-01-20 14:15 UTC
 3   | ML pipeline design             | 67       | 2026-02-01 09:00 UTC
 ...
```

## Importing Specific Conversations

### By Title

Filter by a substring of the conversation title (case-insensitive):

```bash
scaffold import conversations.json --title "architecture"
```

This imports only conversations whose title contains "architecture". If multiple match, they are all included.

### By Interactive Selection

Browse the list and pick which conversations to import:

```bash
scaffold import conversations.json --select
```

This shows the conversation table, then prompts you to enter numbers:

```
Enter conversation numbers to import (comma-separated, e.g. 1,3,5):
> 1,3
```

### Importing Everything

Without any filter flags, all conversations are concatenated into a single file:

```bash
scaffold import conversations.json
```

## Splitting Conversations into Separate Files

Instead of one large file, write each conversation to its own markdown file:

```bash
scaffold import conversations.json --split
```

This creates numbered, slugified files in the output directory:

```
data/conversations/
  001-architecture-brainstorm.md
  002-debug-auth-flow.md
  003-ml-pipeline-design.md
  ...
```

Combine with `--title` to split only matching conversations:

```bash
scaffold import conversations.json --title "architecture" --split
```

## Output Control

### Default Location

By default, imported conversations are written to:

```
data/conversations/{filename}_parsed.md
```

Configure the directory in `scaffold.yaml`:

```yaml
import:
  conversation_dir: "data/conversations"
```

### Custom Output Path

Write to a specific file:

```bash
scaffold import conversations.json --title "architecture" --output docs/ai/vision/architecture-brainstorm.md
```

For `--split`, the `--output` path is treated as the target directory:

```bash
scaffold import conversations.json --split --output docs/ai/imported/
```

## Command Reference

```bash
scaffold import FILE [OPTIONS]

Options:
  --format, -f     Format: auto, chatgpt, claude, markdown (default: auto)
  --output, -o     Output file path (or directory for --split)
  --list, -l       List conversation titles and exit
  --title, -t      Filter by title (case-insensitive substring match)
  --select, -s     Interactively select conversations to import
  --split          Write each conversation to its own file
```

## Tips for Using Imported Conversations

1. **Place for agent visibility**: Move or copy the imported file to a path the agent reads (e.g. `docs/ai/product_vision.md`, `docs/ai/architecture_notes.md`) if you want it to inform plan review and execution.

2. **Trim before import**: Large exports can be verbose. Use `--title` or `--select` to extract only the relevant exchanges instead of importing everything.

3. **Add a header**: After import, add a short header describing the context (date, participants, purpose) so future readers understand the artifact.

4. **Link from plans**: Reference imported conversations in plan files when they contain decisions or constraints: "See docs/ai/vision/architecture-brainstorm.md for design rationale."

5. **Split for organization**: Use `--split` when your export has many conversations. Individual files are easier to reference and manage than one large concatenated document.
