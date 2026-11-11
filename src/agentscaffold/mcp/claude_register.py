"""Register the canonical AgentScaffold server with Claude Code.

Claude Code owns ``~/.claude.json``. This module never opens that file. It
runs ``claude`` with an argument list, from an empty temporary directory so a
local or project entry cannot hide the user-scope entry.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agentscaffold.mcp.install import canonical_entry

MISSING_SENTENCE = "No MCP server named"
PROBE_TIMEOUT_SECONDS = 10.0
SERVER_NAME = "agentscaffold"

Runner = Callable[[Sequence[str], Path], tuple[int, str]]


class ClaudeRegisterError(RuntimeError):
    """The Claude client could not be registered. The Cursor client is unaffected."""


@dataclass(frozen=True)
class Probe:
    """One parsed ``claude mcp get`` result."""

    kind: str
    scope: str
    connected: bool
    issue: str
    command: str
    args: tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class ClientAction:
    """What registration did, or would do, for one client."""

    client: str
    ok: bool
    message: str
    argv: tuple[str, ...] = ()


def remove_argv(binary: str) -> tuple[str, ...]:
    """Remove only the user-scope server. Local and project entries stay."""
    return (binary, "mcp", "remove", SERVER_NAME, "--scope", "user")


def add_argv(binary: str) -> tuple[str, ...]:
    """The mutating command. Fixed arguments, no shell."""
    return (binary, "mcp", "add", "--scope", "user", SERVER_NAME, "--", "scaffold", "mcp")


def probe_argv(binary: str) -> tuple[str, ...]:
    return (binary, "mcp", "get", SERVER_NAME)


def is_canonical_command(command: str, args: Sequence[str]) -> bool:
    """True for the entry ``canonical_entry`` writes. A path is not canonical."""
    entry = canonical_entry()
    return command == entry["command"] and list(args) == list(entry["args"])


def parse_probe(text: str) -> Probe:
    """Classify ``claude mcp get`` output. Unrecognized text is not ok."""
    raw = text or ""
    if MISSING_SENTENCE in raw:
        return Probe("missing", "none", False, "", "", (), raw)
    fields = _fields(raw)
    scope = _scope(fields.get("scope", ""))
    status = fields.get("status", "")
    connected = _connected(status)
    command = fields.get("command", "").strip()
    args = tuple(fields.get("args", "").split())
    issue = fields.get("issue", "").strip()
    if not command and not scope:
        return Probe("unrecognized", "unknown", False, issue, command, args, raw)
    if is_canonical_command(command, args):
        kind = "canonical"
    elif command:
        kind = "foreign"
    else:
        kind = "unrecognized"
    return Probe(kind, scope, connected, issue, command, args, raw)


def selected_clients(explicit: Sequence[str] | None, *, claude_home: Path) -> list[str]:
    """Clients ``scaffold mcp install`` registers.

    Omitted means Cursor, plus Claude Code when ``~/.claude`` exists.
    """
    if explicit:
        unknown = [name for name in explicit if name not in {"cursor", "claude"}]
        if unknown:
            raise ClaudeRegisterError(
                f"Unknown client(s): {', '.join(unknown)}. Choose cursor or claude."
            )
        return list(explicit)
    clients = ["cursor"]
    if claude_home.is_dir():
        clients.append("claude")
    return clients


def claude_binary() -> tuple[Path | None, str]:
    """``(path, reason)``. A binary inside a registered project is refused."""
    found = shutil.which("claude")
    if not found:
        return None, "missing"
    path = Path(found).resolve()
    if _inside_registered_project(path):
        return None, "refused"
    return path, ""


def register_claude(
    *,
    dry_run: bool = False,
    runner: Runner | None = None,
    binary: Path | None = None,
    binary_reason: str = "",
) -> ClientAction:
    """Probe, then add the user-scope server. Never removes an existing entry."""
    if binary is None and not binary_reason:
        binary, binary_reason = claude_binary()
    if binary is None:
        command = "claude mcp add --scope user agentscaffold -- scaffold mcp"
        if binary_reason == "refused":
            return ClientAction(
                "claude",
                False,
                "Refusing to run a claude binary that resolves inside a registered project. "
                f"Register by hand with `{command}`.",
            )
        return ClientAction(
            "claude",
            False,
            f"`claude` was not found on PATH. The server was not registered. Run `{command}` "
            "once claude is installed.",
        )

    run = runner or _default_runner
    binary_text = str(binary)
    try:
        with tempfile.TemporaryDirectory(prefix="agentscaffold-claude-") as tmp:
            cwd = Path(tmp)
            code, text = run(probe_argv(binary_text), cwd)
            probe = parse_probe(text)
            if code != 0 and probe.kind == "unrecognized":
                return ClientAction(
                    "claude",
                    False,
                    "claude mcp get returned unrecognized output. Nothing was added.\n"
                    + text.strip(),
                )
            return _act(probe, binary_text, cwd, dry_run, run)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ClientAction("claude", False, f"claude mcp get failed: {exc}. Nothing was added.")


def remove_created_server(
    *,
    dry_run: bool = False,
    runner: Runner | None = None,
    binary: Path | None = None,
) -> ClientAction:
    """Remove the user-scope server only when it is still the canonical command."""
    if binary is None:
        binary, reason = claude_binary()
        if binary is None:
            detail = "refused" if reason == "refused" else "not found"
            return ClientAction(
                "claude",
                True,
                f"`claude` was {detail}. The server entry was left in place.",
            )
    run = runner or _default_runner
    binary_text = str(binary)
    try:
        with tempfile.TemporaryDirectory(prefix="agentscaffold-claude-") as tmp:
            cwd = Path(tmp)
            _code, text = run(probe_argv(binary_text), cwd)
            probe = parse_probe(text)
            if not (probe.kind == "canonical" and probe.scope == "user"):
                return ClientAction(
                    "claude",
                    True,
                    "Left the Claude server in place. It is not the canonical user-scope entry.",
                )
            argv = remove_argv(binary_text)
            if dry_run:
                return ClientAction("claude", True, "Would remove the user-scope server.", argv)
            code, output = run(argv, cwd)
            if code != 0:
                return ClientAction(
                    "claude",
                    False,
                    "claude mcp remove failed. The entry was left in place.\n" + output.strip(),
                    argv,
                )
            return ClientAction("claude", True, "Removed the user-scope server.", argv)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ClientAction(
            "claude",
            False,
            f"claude mcp get failed: {exc}. The entry was left in place.",
        )


def _act(probe: Probe, binary: str, cwd: Path, dry_run: bool, run: Runner) -> ClientAction:
    argv = add_argv(binary)
    if probe.kind == "missing":
        if dry_run:
            return ClientAction("claude", True, "Would register the user-scope server.", argv)
        code, text = run(argv, cwd)
        if code != 0:
            return ClientAction(
                "claude",
                False,
                "claude mcp add failed. The entry was not changed.\n" + text.strip(),
                argv,
            )
        code, text = run(probe_argv(binary), cwd)
        follow = parse_probe(text)
        if follow.kind == "canonical" and follow.scope == "user" and follow.connected:
            return ClientAction("claude", True, "Registered the user-scope server.", argv)
        return ClientAction(
            "claude",
            False,
            "claude mcp add ran, but the follow-up get did not show a connected canonical "
            "server.\n" + text.strip(),
            argv,
        )

    if probe.kind == "canonical" and probe.scope == "user" and probe.connected:
        return ClientAction("claude", True, "User-scope server already registered.", ())

    if probe.kind == "canonical" and probe.scope == "user":
        issue = probe.issue or "the server did not connect"
        return ClientAction(
            "claude",
            False,
            f"The user-scope server is registered but Claude Code cannot start it: {issue}. "
            "`scaffold` must be on the PATH Claude Code starts with.",
        )

    if probe.kind == "foreign" and probe.scope == "user":
        return ClientAction(
            "claude",
            False,
            "A user-scope server named agentscaffold already exists with a different command "
            f"({probe.command} {' '.join(probe.args)}). It was left in place.",
        )

    if probe.scope in {"local", "project"} and probe.kind in {"canonical", "foreign"}:
        if dry_run:
            return ClientAction(
                "claude",
                True,
                f"A {probe.scope} entry is visible. Would still add the user-scope server.",
                argv,
            )
        code, text = run(argv, cwd)
        if code != 0:
            return ClientAction("claude", False, "claude mcp add failed.\n" + text.strip(), argv)
        return ClientAction(
            "claude",
            True,
            f"Added the user-scope server. A {probe.scope} entry still outranks it there.",
            argv,
        )

    return ClientAction(
        "claude",
        False,
        "claude mcp get returned unrecognized output. Nothing was added.\n" + probe.raw.strip(),
    )


def _default_runner(argv: Sequence[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _fields(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        for name in ("scope", "status", "issue", "command", "args"):
            prefix = name + ":"
            if stripped.lower().startswith(prefix):
                found[name] = stripped.split(":", 1)[1].strip()
    return found


def _scope(value: str) -> str:
    lowered = value.lower()
    if "user" in lowered:
        return "user"
    if "local" in lowered:
        return "local"
    if "project" in lowered:
        return "project"
    return "unknown" if value else "none"


def _connected(status: str) -> bool:
    lowered = status.lower()
    if "fail" in lowered or "✘" in status or "✗" in status:
        return False
    return "connected" in lowered


def _inside_registered_project(path: Path) -> bool:
    from agentscaffold.mcp.install import registered_roots

    for root in registered_roots():
        try:
            path.relative_to(Path(root).resolve())
        except ValueError:
            continue
        else:
            return True
    return False
