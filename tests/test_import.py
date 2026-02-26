"""Tests for conversation import commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from agentscaffold.cli import app
from agentscaffold.import_cmd.chatgpt import (
    filter_by_indices,
    filter_by_title,
    list_conversations,
    parse_chatgpt,
    split_conversations,
)
from agentscaffold.import_cmd.markdown import parse_markdown
from agentscaffold.import_cmd.router import _detect_format


def _make_conversation(
    title: str, user_msg: str, assistant_msg: str, time_base: int = 1700000000
) -> dict:
    """Build a single ChatGPT conversation dict."""
    return {
        "title": title,
        "mapping": {
            "root": {
                "id": "root",
                "parent": None,
                "children": ["msg1"],
                "message": None,
            },
            "msg1": {
                "id": "msg1",
                "parent": "root",
                "children": ["msg2"],
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [user_msg]},
                    "create_time": time_base,
                },
            },
            "msg2": {
                "id": "msg2",
                "parent": "msg1",
                "children": [],
                "message": {
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": [assistant_msg]},
                    "create_time": time_base + 60,
                },
            },
        },
    }


def _make_chatgpt_json(path: Path) -> Path:
    """Write a minimal ChatGPT export JSON with a single conversation."""
    data = [_make_conversation("Test Conversation", "Hello AI", "Hello human!")]
    json_path = path / "chatgpt_export.json"
    json_path.write_text(json.dumps(data))
    return json_path


def _make_multi_conversation_json(path: Path) -> Path:
    """Write a ChatGPT export with multiple conversations."""
    data = [
        _make_conversation(
            "Architecture Brainstorm", "Design the system", "Here is the architecture", 1700000000
        ),
        _make_conversation(
            "Debug Auth Flow", "Auth is broken", "Check the token expiry", 1700100000
        ),
        _make_conversation(
            "ML Pipeline Design", "How should we train?", "Use a feature store", 1700200000
        ),
        _make_conversation(
            "Architecture Review", "Review the layers", "Looks good overall", 1700300000
        ),
    ]
    json_path = path / "multi_export.json"
    json_path.write_text(json.dumps(data))
    return json_path


# ---------------------------------------------------------------------------
# Basic parsing tests (existing)
# ---------------------------------------------------------------------------


def test_import_chatgpt(tmp_path: Path) -> None:
    """Parse a minimal ChatGPT JSON and verify extracted content."""
    json_file = _make_chatgpt_json(tmp_path)
    content = parse_chatgpt(json_file)
    assert "Test Conversation" in content
    assert "Hello AI" in content
    assert "Hello human!" in content
    assert "User" in content
    assert "Assistant" in content


def test_import_markdown(tmp_path: Path) -> None:
    """Import a .md file and verify the header is prepended."""
    md_file = tmp_path / "notes.md"
    md_file.write_text("# My Notes\n\nSome content here.\n")
    content = parse_markdown(md_file)
    assert "Imported from: notes.md" in content
    assert "Import date:" in content
    assert "# My Notes" in content
    assert "Some content here." in content


def test_import_auto_detect_json(tmp_path: Path) -> None:
    """Auto-detect a .json file as chatgpt format."""
    json_file = _make_chatgpt_json(tmp_path)
    fmt = _detect_format(json_file)
    assert fmt == "chatgpt"


def test_import_auto_detect_markdown(tmp_path: Path) -> None:
    """Auto-detect a .md file as markdown format."""
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Just markdown\n")
    fmt = _detect_format(md_file)
    assert fmt == "markdown"


def test_import_cli_chatgpt(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CLI import command produces output file from ChatGPT JSON."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        json_file = _make_chatgpt_json(tmp_project)
        output_file = tmp_project / "output.md"
        result = cli_runner.invoke(
            app, ["import", str(json_file), "-f", "chatgpt", "-o", str(output_file)]
        )
        assert result.exit_code == 0
        assert output_file.is_file()
        content = output_file.read_text()
        assert "Hello AI" in content
    finally:
        os.chdir(orig_cwd)


def test_import_cli_markdown(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CLI import command handles markdown files."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        md_file = tmp_project / "conv.md"
        md_file.write_text("# Chat Log\n\nSome conversation.\n")
        output_file = tmp_project / "imported.md"
        result = cli_runner.invoke(
            app, ["import", str(md_file), "-f", "markdown", "-o", str(output_file)]
        )
        assert result.exit_code == 0
        assert output_file.is_file()
        content = output_file.read_text()
        assert "Chat Log" in content
    finally:
        os.chdir(orig_cwd)


def test_import_nonexistent_file(cli_runner: CliRunner) -> None:
    """CLI import with a missing file prints an error."""
    result = cli_runner.invoke(app, ["import", "/nonexistent/file.json"])
    assert result.exit_code == 0
    assert "not found" in result.output.lower() or "File not found" in result.output


# ---------------------------------------------------------------------------
# List conversations
# ---------------------------------------------------------------------------


def test_list_conversations(tmp_path: Path) -> None:
    """list_conversations returns summaries for all conversations."""
    json_file = _make_multi_conversation_json(tmp_path)
    summaries = list_conversations(json_file)
    assert len(summaries) == 4
    assert summaries[0]["title"] == "Architecture Brainstorm"
    assert summaries[1]["title"] == "Debug Auth Flow"
    assert summaries[2]["title"] == "ML Pipeline Design"
    assert summaries[3]["title"] == "Architecture Review"
    assert summaries[0]["index"] == "1"
    assert summaries[3]["index"] == "4"
    assert int(summaries[0]["messages"]) == 2


def test_list_conversations_cli(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CLI --list flag shows conversation table without writing files."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        json_file = _make_multi_conversation_json(tmp_project)
        result = cli_runner.invoke(app, ["import", str(json_file), "--list"])
        assert result.exit_code == 0
        assert "Architecture Brainstorm" in result.output
        assert "Debug Auth Flow" in result.output
        assert "4 conversations found" in result.output
    finally:
        os.chdir(orig_cwd)


# ---------------------------------------------------------------------------
# Filter by title
# ---------------------------------------------------------------------------


def test_filter_by_title_single_match(tmp_path: Path) -> None:
    """filter_by_title returns only matching conversations."""
    json_file = _make_multi_conversation_json(tmp_path)
    content = filter_by_title(json_file, "Debug Auth")
    assert "Debug Auth Flow" in content
    assert "Auth is broken" in content
    assert "Architecture Brainstorm" not in content
    assert "ML Pipeline" not in content


def test_filter_by_title_multiple_matches(tmp_path: Path) -> None:
    """filter_by_title matches multiple conversations with shared substring."""
    json_file = _make_multi_conversation_json(tmp_path)
    content = filter_by_title(json_file, "architecture")
    assert "Architecture Brainstorm" in content
    assert "Architecture Review" in content
    assert "Debug Auth Flow" not in content


def test_filter_by_title_case_insensitive(tmp_path: Path) -> None:
    """filter_by_title is case-insensitive."""
    json_file = _make_multi_conversation_json(tmp_path)
    content = filter_by_title(json_file, "ml pipeline")
    assert "ML Pipeline Design" in content


def test_filter_by_title_no_match(tmp_path: Path) -> None:
    """filter_by_title returns empty string when nothing matches."""
    json_file = _make_multi_conversation_json(tmp_path)
    content = filter_by_title(json_file, "nonexistent topic")
    assert content == ""


def test_filter_by_title_cli(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CLI --title flag filters and writes matching conversations."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        json_file = _make_multi_conversation_json(tmp_project)
        output_file = tmp_project / "filtered.md"
        result = cli_runner.invoke(
            app, ["import", str(json_file), "--title", "Debug Auth", "-o", str(output_file)]
        )
        assert result.exit_code == 0
        assert output_file.is_file()
        content = output_file.read_text()
        assert "Debug Auth Flow" in content
        assert "Architecture Brainstorm" not in content
    finally:
        os.chdir(orig_cwd)


# ---------------------------------------------------------------------------
# Filter by indices
# ---------------------------------------------------------------------------


def test_filter_by_indices(tmp_path: Path) -> None:
    """filter_by_indices returns conversations at specified 1-based positions."""
    json_file = _make_multi_conversation_json(tmp_path)
    content = filter_by_indices(json_file, [1, 3])
    assert "Architecture Brainstorm" in content
    assert "ML Pipeline Design" in content
    assert "Debug Auth Flow" not in content
    assert "Architecture Review" not in content


def test_filter_by_indices_out_of_range(tmp_path: Path) -> None:
    """filter_by_indices skips out-of-range indices gracefully."""
    json_file = _make_multi_conversation_json(tmp_path)
    content = filter_by_indices(json_file, [1, 99])
    assert "Architecture Brainstorm" in content


def test_filter_by_indices_all_invalid(tmp_path: Path) -> None:
    """filter_by_indices returns empty string when all indices are invalid."""
    json_file = _make_multi_conversation_json(tmp_path)
    content = filter_by_indices(json_file, [99, 100])
    assert content == ""


# ---------------------------------------------------------------------------
# Split conversations
# ---------------------------------------------------------------------------


def test_split_conversations(tmp_path: Path) -> None:
    """split_conversations writes each conversation to its own file."""
    json_file = _make_multi_conversation_json(tmp_path)
    output_dir = tmp_path / "split_output"
    created = split_conversations(json_file, output_dir)
    assert len(created) == 4
    assert output_dir.is_dir()

    filenames = [p.name for p in created]
    assert "001-architecture-brainstorm.md" in filenames
    assert "002-debug-auth-flow.md" in filenames
    assert "003-ml-pipeline-design.md" in filenames
    assert "004-architecture-review.md" in filenames

    content_1 = created[0].read_text()
    assert "Architecture Brainstorm" in content_1
    assert "Design the system" in content_1

    content_3 = created[2].read_text()
    assert "ML Pipeline Design" in content_3
    assert "feature store" in content_3


def test_split_cli(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CLI --split flag creates individual files for each conversation."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        json_file = _make_multi_conversation_json(tmp_project)
        split_dir = tmp_project / "split_out"
        result = cli_runner.invoke(app, ["import", str(json_file), "--split", "-o", str(split_dir)])
        assert result.exit_code == 0
        assert split_dir.is_dir()
        files = list(split_dir.glob("*.md"))
        assert len(files) == 4
        assert "Split 4 conversations" in result.output
    finally:
        os.chdir(orig_cwd)


# ---------------------------------------------------------------------------
# Select (non-interactive path -- we test the underlying filter_by_indices)
# ---------------------------------------------------------------------------


def test_select_cli_shows_list(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CLI --select flag shows the conversation list before prompting."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        json_file = _make_multi_conversation_json(tmp_project)
        result = cli_runner.invoke(app, ["import", str(json_file), "--select"], input="1,3\n")
        assert result.exit_code == 0
        assert "Architecture Brainstorm" in result.output
        assert "ML Pipeline Design" in result.output
    finally:
        os.chdir(orig_cwd)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_list_on_non_chatgpt_format(tmp_project: Path, cli_runner: CliRunner) -> None:
    """--list on a markdown file gives a helpful warning."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        md_file = tmp_project / "notes.md"
        md_file.write_text("# Notes\n")
        result = cli_runner.invoke(app, ["import", str(md_file), "--list"])
        assert result.exit_code == 0
        assert "only supported for chatgpt" in result.output.lower()
    finally:
        os.chdir(orig_cwd)


def test_empty_json_list(tmp_path: Path) -> None:
    """list_conversations handles an empty JSON array gracefully."""
    json_file = tmp_path / "empty.json"
    json_file.write_text("[]")
    summaries = list_conversations(json_file)
    assert summaries == []


def test_single_conversation_object(tmp_path: Path) -> None:
    """A single conversation object (not wrapped in array) is handled."""
    conv = _make_conversation("Solo Chat", "Hi", "Hello")
    json_file = tmp_path / "single.json"
    json_file.write_text(json.dumps(conv))
    summaries = list_conversations(json_file)
    assert len(summaries) == 1
    assert summaries[0]["title"] == "Solo Chat"
