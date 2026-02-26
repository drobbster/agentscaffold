"""ChatGPT export parsing."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def _extract_messages(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract messages from a ChatGPT conversation mapping in chronological order."""
    children_map: dict[str, list[str]] = {}
    root_id: str | None = None

    for node_id, node in mapping.items():
        if node.get("parent") is None:
            root_id = node_id
        children_map[node_id] = node.get("children", [])

    messages: list[dict[str, Any]] = []

    def traverse(node_id: str) -> None:
        node = mapping.get(node_id, {})
        msg = node.get("message")

        if msg:
            author = msg.get("author", {}).get("role", "unknown")
            content_obj = msg.get("content", {})
            create_time = msg.get("create_time", 0) or 0

            text = ""
            content_type = content_obj.get("content_type", "")

            if content_type == "text" or "parts" in content_obj:
                parts = content_obj.get("parts", [])
                text = "\n".join(str(p) for p in parts if p)

            if text.strip() and author != "system":
                messages.append({"role": author, "text": text.strip(), "time": create_time})

        for child_id in children_map.get(node_id, []):
            traverse(child_id)

    if root_id:
        traverse(root_id)

    messages.sort(key=lambda x: x["time"])
    return messages


def _format_timestamp(ts: float) -> str:
    """Format a Unix timestamp as a readable date string."""
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OSError):
        return ""


def _format_conversation(conversation: dict[str, Any]) -> str:
    """Format a single conversation as markdown."""
    title = conversation.get("title", "Untitled Conversation")
    mapping = conversation.get("mapping", {})
    messages = _extract_messages(mapping)

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Messages:** {len(messages)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in messages:
        role = msg["role"].capitalize()
        ts = _format_timestamp(msg["time"])
        header = f"## {role}"
        if ts:
            header += f" ({ts})"
        lines.append(header)
        lines.append("")
        lines.append(msg["text"])
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _slugify(text: str) -> str:
    """Convert a title string to a filesystem-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:80] if text else "untitled"


def _load_conversations(file: Path) -> list[dict[str, Any]]:
    """Load and return the list of conversations from a ChatGPT export file."""
    try:
        raw = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        console.print(f"[red]File not found: {file}[/red]")
        return []
    except UnicodeDecodeError:
        console.print(f"[red]Cannot read file (encoding error): {file}[/red]")
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON in {file}: {exc}[/red]")
        return []

    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict) and "mapping" in c]
    elif isinstance(data, dict) and "mapping" in data:
        return [data]

    console.print(
        "[yellow]Unrecognized ChatGPT export format. "
        "Expected a JSON object with 'mapping' key or a list of conversations.[/yellow]"
    )
    return []


def list_conversations(file: Path) -> list[dict[str, str]]:
    """Return a list of conversation summaries (title, message count, date)."""
    conversations = _load_conversations(file)
    summaries: list[dict[str, str]] = []

    for i, conv in enumerate(conversations):
        title = conv.get("title", "Untitled Conversation")
        mapping = conv.get("mapping", {})
        messages = _extract_messages(mapping)
        msg_count = str(len(messages))
        date = ""
        if messages:
            date = _format_timestamp(messages[0]["time"])
        summaries.append(
            {
                "index": str(i + 1),
                "title": title,
                "messages": msg_count,
                "date": date,
            }
        )

    return summaries


def print_conversation_list(file: Path) -> list[dict[str, str]]:
    """Print a formatted table of conversations and return the summaries."""
    summaries = list_conversations(file)
    if not summaries:
        console.print("[yellow]No conversations found in export.[/yellow]")
        return summaries

    table = Table(title=f"Conversations in {file.name}")
    table.add_column("#", style="cyan", width=5)
    table.add_column("Title", style="white")
    table.add_column("Messages", style="green", width=10)
    table.add_column("Date", style="dim", width=20)

    for s in summaries:
        table.add_row(s["index"], s["title"], s["messages"], s["date"])

    console.print(table)
    console.print(f"\n[dim]{len(summaries)} conversations found.[/dim]")
    return summaries


def filter_by_title(file: Path, title_pattern: str) -> str:
    """Parse only conversations whose title matches the pattern (case-insensitive)."""
    conversations = _load_conversations(file)
    if not conversations:
        return ""

    pattern = re.compile(re.escape(title_pattern), re.IGNORECASE)
    matched = [c for c in conversations if pattern.search(c.get("title", ""))]

    if not matched:
        console.print(f"[yellow]No conversations matching '{title_pattern}'[/yellow]")
        available = [c.get("title", "Untitled") for c in conversations[:10]]
        if available:
            console.print("[dim]Available titles:[/dim]")
            for t in available:
                console.print(f"  [dim]- {t}[/dim]")
            if len(conversations) > 10:
                console.print(f"  [dim]... and {len(conversations) - 10} more[/dim]")
        return ""

    console.print(f"[green]Matched {len(matched)} conversation(s):[/green]")
    for c in matched:
        console.print(f"  - {c.get('title', 'Untitled')}")

    parts = [_format_conversation(c) for c in matched]
    return "\n\n".join(parts)


def filter_by_indices(file: Path, indices: list[int]) -> str:
    """Parse only conversations at the given 1-based indices."""
    conversations = _load_conversations(file)
    if not conversations:
        return ""

    parts: list[str] = []
    for idx in indices:
        if 1 <= idx <= len(conversations):
            parts.append(_format_conversation(conversations[idx - 1]))
        else:
            console.print(f"[yellow]Index {idx} out of range (1-{len(conversations)})[/yellow]")

    if not parts:
        return ""

    return "\n\n".join(parts)


def split_conversations(file: Path, output_dir: Path) -> list[Path]:
    """Write each conversation to its own file. Returns list of created paths."""
    conversations = _load_conversations(file)
    if not conversations:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    for i, conv in enumerate(conversations):
        title = conv.get("title", "Untitled Conversation")
        slug = _slugify(title)
        filename = f"{i + 1:03d}-{slug}.md"
        out_path = output_dir / filename
        content = _format_conversation(conv)
        out_path.write_text(content, encoding="utf-8")
        created.append(out_path)

    return created


def parse_chatgpt(file: Path) -> str:
    """Parse a ChatGPT export file and return extracted content as markdown."""
    conversations = _load_conversations(file)
    if not conversations:
        return ""

    parts = [_format_conversation(c) for c in conversations]
    return "\n\n".join(parts)
