"""Import router for chat exports."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from agentscaffold.config import load_config

console = Console()


def _detect_format(file: Path) -> str:
    """Auto-detect the conversation export format from file content."""
    suffix = file.suffix.lower()

    if suffix == ".md":
        return "markdown"

    if suffix == ".json":
        try:
            raw = file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "markdown"

        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and "mapping" in first:
                return "chatgpt"
        elif isinstance(data, dict):
            if "mapping" in data or "message" in data:
                return "chatgpt"

        return "chatgpt"

    # Unknown extension -- try JSON first, fall back to markdown
    try:
        raw = file.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict | list):
            return "chatgpt"
    except (json.JSONDecodeError, UnicodeDecodeError, FileNotFoundError):
        pass

    return "markdown"


def run_import(
    file: Path,
    fmt: str,
    output: Path | None,
    *,
    list_only: bool = False,
    title: str | None = None,
    select: bool = False,
    split: bool = False,
) -> None:
    """Import a chat export file with optional filtering, listing, and splitting."""
    if not file.is_file():
        console.print(f"[red]File not found: {file}[/red]")
        return

    resolved_fmt = fmt if fmt != "auto" else _detect_format(file)

    # --list: show conversation titles and exit
    if list_only:
        if resolved_fmt == "chatgpt":
            from agentscaffold.import_cmd.chatgpt import print_conversation_list

            print_conversation_list(file)
        else:
            console.print(
                f"[yellow]--list is only supported for chatgpt format "
                f"(detected: {resolved_fmt})[/yellow]"
            )
        return

    # --select: interactive selection (chatgpt only)
    if select:
        if resolved_fmt != "chatgpt":
            console.print(
                f"[yellow]--select is only supported for chatgpt format "
                f"(detected: {resolved_fmt})[/yellow]"
            )
            return

        from agentscaffold.import_cmd.chatgpt import (
            filter_by_indices,
            print_conversation_list,
        )

        summaries = print_conversation_list(file)
        if not summaries:
            return

        console.print(
            "\n[bold]Enter conversation numbers to import " "(comma-separated, e.g. 1,3,5):[/bold]"
        )
        try:
            selection = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Cancelled.[/dim]")
            return

        if not selection:
            console.print("[dim]No selection made.[/dim]")
            return

        try:
            indices = [int(s.strip()) for s in selection.split(",") if s.strip()]
        except ValueError:
            console.print("[red]Invalid input. Enter numbers separated by commas.[/red]")
            return

        content = filter_by_indices(file, indices)
        if not content:
            return

        _write_output(file, output, content, split=False)
        return

    # --split: write each conversation to its own file (chatgpt only)
    if split:
        if resolved_fmt != "chatgpt":
            console.print(
                f"[yellow]--split is only supported for chatgpt format "
                f"(detected: {resolved_fmt})[/yellow]"
            )
            return

        from agentscaffold.import_cmd.chatgpt import split_conversations

        if output is not None:
            split_dir = output if output.suffix == "" else output.parent
        else:
            config = load_config()
            split_dir = Path(config.import_config.conversation_dir)

        created = split_conversations(file, split_dir)
        if created:
            console.print(f"[green]Split {len(created)} conversations into:[/green]")
            for p in created:
                console.print(f"  {p}")
        return

    # --title: filter by title pattern (chatgpt only)
    if title:
        if resolved_fmt != "chatgpt":
            console.print(
                f"[yellow]--title is only supported for chatgpt format "
                f"(detected: {resolved_fmt})[/yellow]"
            )
            return

        from agentscaffold.import_cmd.chatgpt import filter_by_title

        content = filter_by_title(file, title)
        if not content:
            return

        _write_output(file, output, content, split=False)
        return

    # Default: parse everything
    if resolved_fmt == "chatgpt":
        from agentscaffold.import_cmd.chatgpt import parse_chatgpt

        content = parse_chatgpt(file)
    elif resolved_fmt == "claude":
        from agentscaffold.import_cmd.claude import parse_claude

        content = parse_claude(file)
    elif resolved_fmt == "markdown":
        from agentscaffold.import_cmd.markdown import parse_markdown

        content = parse_markdown(file)
    else:
        console.print(
            f"[red]Unknown format '{resolved_fmt}'. "
            f"Supported formats: chatgpt, claude, markdown, auto[/red]"
        )
        return

    if not content:
        console.print("[yellow]No content extracted from file.[/yellow]")
        return

    _write_output(file, output, content, split=False)


def _write_output(file: Path, output: Path | None, content: str, *, split: bool) -> None:
    """Write parsed content to the output path."""
    if output is None:
        config = load_config()
        conv_dir = Path(config.import_config.conversation_dir)
        output = conv_dir / f"{file.stem}_parsed.md"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    console.print(f"[green]Imported conversation written to:[/green] {output}")
