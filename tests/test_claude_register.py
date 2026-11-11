"""Claude Code registration. No test invokes a real claude binary."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.mcp.claude_register import (
    ClientAction,
    add_argv,
    parse_probe,
    register_claude,
    selected_clients,
)

MISSING = 'No MCP server named "agentscaffold".\n'
CONNECTED = """\
agentscaffold:
  Scope: User config (available in all your projects)
  Status: Connected
  Type: stdio
  Command: scaffold
  Args: mcp
"""
FAILED = """\
agentscaffold:
  Scope: User config (available in all your projects)
  Status: Failed to connect
  Issue: ENOENT: Executable not found in $PATH
  Command: scaffold
  Args: mcp
"""
FOREIGN = """\
agentscaffold:
  Scope: User config (available in all your projects)
  Status: Connected
  Command: node
  Args: server.js
"""


def test_parse_missing_connected_failed_and_foreign() -> None:
    assert parse_probe(MISSING).kind == "missing"
    connected = parse_probe(CONNECTED)
    assert connected.kind == "canonical" and connected.scope == "user" and connected.connected
    failed = parse_probe(FAILED)
    assert failed.kind == "canonical" and not failed.connected
    assert "ENOENT" in failed.issue
    foreign = parse_probe(FOREIGN)
    assert foreign.kind == "foreign" and foreign.scope == "user"


def test_unrecognized_output_is_not_ok() -> None:
    probe = parse_probe("something else entirely")
    assert probe.kind == "unrecognized"


def test_selected_clients_follow_the_claude_directory(tmp_path: Path) -> None:
    assert selected_clients(None, claude_home=tmp_path / "missing") == ["cursor"]
    home = tmp_path / ".claude"
    home.mkdir()
    assert selected_clients(None, claude_home=home) == ["cursor", "claude"]
    assert selected_clients(["cursor"], claude_home=home) == ["cursor"]
    with pytest.raises(Exception, match="Unknown client"):
        selected_clients(["windsurf"], claude_home=home)


def test_register_adds_only_when_missing(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv, cwd):
        calls.append((tuple(argv), cwd))
        if argv[2] == "get" and len(calls) == 1:
            return 0, MISSING
        if argv[2] == "add":
            return 0, "Added"
        return 0, CONNECTED

    binary = tmp_path / "claude"
    action = register_claude(runner=runner, binary=binary)
    assert action.ok
    assert calls[0][0][:3] == (str(binary), "mcp", "get")
    assert calls[1][0] == add_argv(str(binary))
    assert calls[2][0][:3] == (str(binary), "mcp", "get")
    assert calls[0][1] != Path.home()
    assert calls[0][1].name.startswith("agentscaffold-claude-")


def test_dry_run_does_not_add(tmp_path: Path) -> None:
    def runner(argv, cwd):
        assert argv[2] == "get"
        return 0, MISSING

    action = register_claude(dry_run=True, runner=runner, binary=tmp_path / "claude")
    assert action.ok and action.argv[1:3] == ("mcp", "add")


def test_canonical_user_entry_is_a_noop(tmp_path: Path) -> None:
    def runner(argv, cwd):
        return 0, CONNECTED

    action = register_claude(runner=runner, binary=tmp_path / "claude")
    assert action.ok and action.argv == ()


def test_unhealthy_canonical_entry_is_not_replaced(tmp_path: Path) -> None:
    def runner(argv, cwd):
        return 0, FAILED

    action = register_claude(runner=runner, binary=tmp_path / "claude")
    assert not action.ok
    assert "ENOENT" in action.message
    assert action.argv == ()


def test_foreign_user_entry_is_left_in_place(tmp_path: Path) -> None:
    def runner(argv, cwd):
        return 0, FOREIGN

    action = register_claude(runner=runner, binary=tmp_path / "claude")
    assert not action.ok
    assert "node" in action.message
    assert action.argv == ()


def test_missing_binary_names_the_command() -> None:
    action = register_claude(binary=None, binary_reason="missing")
    assert not action.ok
    assert "claude mcp add --scope user" in action.message


def test_probe_cwd_is_an_empty_temp_directory(tmp_path: Path) -> None:
    seen: list[Path] = []

    def runner(argv, cwd):
        seen.append(cwd)
        assert list(cwd.iterdir()) == []
        return 0, CONNECTED

    register_claude(runner=runner, binary=tmp_path / "claude")
    assert seen and seen[0] != Path.home()


def test_client_action_shape() -> None:
    action = ClientAction("claude", True, "ok")
    assert action.client == "claude"
