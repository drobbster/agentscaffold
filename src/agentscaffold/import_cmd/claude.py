"""Claude export parsing."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()


def parse_claude(file: Path) -> str:
    """Parse a Claude export file and return extracted content.

    Claude conversation export parsing is not yet supported. This function
    returns a placeholder message with instructions for contributing.
    """
    _ = file  # acknowledge the argument
    return (
        "# Claude Conversation Import\n"
        "\n"
        "Claude conversation export parsing is not yet supported.\n"
        "\n"
        "## Contributing\n"
        "\n"
        "To add Claude export parsing, implement the parser in:\n"
        "`agentscaffold/import_cmd/claude.py`\n"
        "\n"
        "The parser should:\n"
        "1. Accept a Path to the exported file\n"
        "2. Extract messages with role and content\n"
        "3. Return a formatted markdown string\n"
        "\n"
        "See `chatgpt.py` for a reference implementation.\n"
    )
