"""Registry-routed editor hooks (Plan 277, ADR-028 Decision 4).

Every generated hook, project-level or user-level, is a one-line shim that runs
this module with an event name. It reads the editor's JSON from stdin, resolves
the owning registered project from the edited path, and either does nothing
(the path is outside every registered project) or hands the work to a detached
``scaffold hook-worker`` process.

Two properties are load-bearing, because a user-level hook runs on every agent
edit in every workspace:

**Fast exit.** Module scope imports only the standard library and two
stdlib-only helpers (``config_home``, ``path_flavour``); ``yaml`` loads lazily.
Configuration, pydantic and the graph are imported only on paths that are
inside a registered project, and indexing itself runs in the worker.

**One JSON object, always.** Cursor treats invalid JSON from a permission hook
(``preToolUse``) as a refusal, so anything stray on stdout would block every
agent edit everywhere. :func:`main` sends stdout to stderr while it works,
catches every exception, and writes exactly one response; on an internal error
that response allows the action.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from agentscaffold.config_home import resolve_home_dir
from agentscaffold.path_flavour import (
    match_depth,
    normalise_for_match,
    parse_recorded_path,
    path_contains,
)

#: Mirrors ``workspace_registry.REGISTRY_FILENAME`` / ``REGISTRY_VERSION``;
#: importing that module would import pydantic (a test pins the values).
REGISTRY_FILENAME = "registry.yaml"
REGISTRY_VERSION = 1

#: The user-scope install manifest, written by ``agents.user_scope``.
MANIFEST_FILENAME = "user-install.json"

#: Editor payloads are small; anything larger is not one we understand.
MAX_STDIN_BYTES = 1_000_000

DISABLE_ENV = "SCAFFOLD_HOOK_DISABLE"

#: Written by the worker in the project's state directory; ``doctor`` reads it.
HOOK_LAST_RUN_FILE = "hook.last_run"

#: Events and the response each returns when there is nothing to say.
_ALLOW_RESPONSES: dict[str, str] = {
    "cursor-after-edit": "{}",
    "cursor-pre-edit": '{"permission": "allow"}',
    "cursor-workspace-open": "{}",
    "claude-post-tool-use": "",
    "claude-pre-edit": "",
    "claude-session-start": "",
    "git-post-commit": "",
}

EVENTS: tuple[str, ...] = tuple(_ALLOW_RESPONSES)

SCOPES = ("user", "project")


@dataclass(frozen=True)
class RoutedProject:
    """A project an event resolved to. ``name`` is None for an unregistered repo."""

    name: str | None
    root: Path


# ---------------------------------------------------------------------------
# Registry (read without importing workspace_registry)
# ---------------------------------------------------------------------------


def load_registered_projects(home: Path | None = None) -> list[tuple[str, PurePath]]:
    """Return ``(name, match_root)`` for every registered project.

    Same matching roots as ``RegisteredWorkspace.project_match_root``. An
    absent, unreadable or newer-version registry yields no projects: a hook
    must not fail the editor because the registry is broken; ``doctor``
    reports that.
    """
    path = (home or resolve_home_dir()) / REGISTRY_FILENAME
    if not path.is_file():
        return []
    import yaml

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        raw: Any = yaml.load(path.read_text(encoding="utf-8"), Loader=loader)  # noqa: S506
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(raw, dict):
        return []
    version = raw.get("version", REGISTRY_VERSION)
    if not isinstance(version, int) or version > REGISTRY_VERSION:
        return []

    projects: list[tuple[str, PurePath]] = []
    for workspace in raw.get("workspaces") or []:
        if not isinstance(workspace, dict) or not isinstance(workspace.get("root"), str):
            continue
        root = parse_recorded_path(workspace["root"])
        for project in workspace.get("projects") or []:
            if not isinstance(project, dict) or not isinstance(project.get("name"), str):
                continue
            rel = project.get("path", ".")
            if not isinstance(rel, str):
                continue
            match_root = normalise_for_match(root if rel in ("", ".") else root / rel)
            projects.append((project["name"], match_root))
    return projects


def resolve_registered(
    target: str | PurePath, projects: Sequence[tuple[str, PurePath]]
) -> RoutedProject | None:
    """The most specific registered project containing *target*, or None."""
    normalised = normalise_for_match(target)
    best: RoutedProject | None = None
    best_depth = -1
    for name, root in projects:
        if not path_contains(root, normalised):
            continue
        depth = match_depth(root)
        if depth > best_depth:
            best_depth = depth
            best = RoutedProject(name=name, root=Path(str(root)))
    return best


def projects_for_roots(roots: Sequence[str], projects: Sequence[tuple[str, PurePath]]) -> list[str]:
    """Registered projects whose root equals, contains or lies inside one of *roots*.

    Covers a workspace opened at a monorepo root (projects inside it) and one
    opened at a subfolder of a project (the project contains it).
    """
    names: list[str] = []
    for raw in roots:
        if not isinstance(raw, str) or not raw:
            continue
        workspace_root = normalise_for_match(raw)
        for name, root in projects:
            if name in names:
                continue
            if path_contains(workspace_root, root) or path_contains(root, workspace_root):
                names.append(name)
    return names


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def read_payload(stream: Any = None) -> dict[str, Any]:
    """Parse the editor's JSON from stdin; anything unusable is an empty payload."""
    source = stream if stream is not None else sys.stdin
    try:
        raw = source.read(MAX_STDIN_BYTES + 1)
    except (OSError, ValueError):
        return {}
    if not raw or len(raw) > MAX_STDIN_BYTES:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def edited_path(payload: dict[str, Any]) -> str | None:
    """The absolute path an edit event names, or None.

    Cursor's ``afterFileEdit`` sends ``file_path``; Cursor's ``preToolUse`` and
    Claude Code's tool events send ``tool_input.file_path`` (``notebook_path``
    for notebooks). A relative path is taken against the payload's ``cwd``.
    """
    candidate: Any = payload.get("file_path") or payload.get("path")
    tool_input = payload.get("tool_input") or payload.get("toolInput")
    if not candidate and isinstance(tool_input, dict):
        candidate = (
            tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path")
        )
    if not isinstance(candidate, str) or not candidate:
        return None
    if not os.path.isabs(candidate):
        base = payload.get("cwd")
        if not isinstance(base, str) or not base:
            base = os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd()
        candidate = os.path.join(base, candidate)
    return str(os.path.realpath(candidate))


def _is_state_path(path: str) -> bool:
    """Writes to AgentScaffold's own state must never retrigger the hook (Plan 267)."""
    return ".scaffold" in Path(path).parts


def resolve_edit_target(path: str, scope: str, home: Path | None = None) -> RoutedProject | None:
    """Resolve the project an edit belongs to.

    The registry decides first. A project-level shim (``scope == "project"``)
    also serves a repo that was never registered, as the shell hook it replaces
    did: its working directory is the project root when that holds a
    ``scaffold.yaml`` and contains *path*. A user-level hook has no such
    fallback; its working directory is the editor's configuration directory.
    """
    routed = resolve_registered(path, load_registered_projects(home))
    if routed is not None or scope != "project":
        return routed
    cwd = Path.cwd()
    if (cwd / "scaffold.yaml").is_file() and path_contains(
        normalise_for_match(os.path.realpath(cwd)), normalise_for_match(path)
    ):
        return RoutedProject(name=None, root=Path(os.path.realpath(cwd)))
    return None


# ---------------------------------------------------------------------------
# Worker spawn
# ---------------------------------------------------------------------------


def scaffold_command() -> list[str] | None:
    """The installed ``scaffold`` executable beside this interpreter, else on PATH."""
    bindir = Path(sys.executable).parent
    for name in ("scaffold", "scaffold.exe"):
        candidate = bindir / name
        if candidate.is_file():
            return [str(candidate)]
    import shutil

    found = shutil.which("scaffold")
    return [found] if found else None


def spawn_worker(kind: str, project: RoutedProject, event: str) -> bool:
    """Start ``scaffold hook-worker`` detached from the editor's hook process."""
    command = scaffold_command()
    if command is None:
        return False
    import subprocess

    argv = [*command, "hook-worker", kind, "--root", str(project.root), "--event", event]
    kwargs: dict[str, Any] = {
        "cwd": str(project.root),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)  # noqa: S603 - fixed argv, installed binary
    return True


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def handle_edit(payload: dict[str, Any], scope: str, event: str) -> RoutedProject | None:
    """Schedule an incremental index for the project that owns the edited file."""
    path = edited_path(payload)
    if path is None or _is_state_path(path):
        return None
    project = resolve_edit_target(path, scope)
    if project is None:
        return None
    spawn_worker("index", project, event)
    return project


def protected_reason(payload: dict[str, Any], scope: str) -> str | None:
    """Why an agent edit must be refused, or None to allow it.

    Inside a registered project only, the project's configuration is loaded
    (this is the one hook path that imports config) and the edit is checked
    against ``semi_autonomous.safety.read_only_paths`` when
    ``agents.protect_read_only_paths`` is on.
    """
    path = edited_path(payload)
    if path is None:
        return None
    project = resolve_edit_target(path, scope)
    if project is None:
        return None
    config_path = project.root / "scaffold.yaml"
    if not config_path.is_file():
        return None

    from agentscaffold.config import load_config
    from agentscaffold.validate.safety import matches_read_only

    config = load_config(config_path)
    if not config.agents.protect_read_only_paths:
        return None
    try:
        rel = Path(path).relative_to(project.root).as_posix()
    except ValueError:
        return None
    if not matches_read_only(rel, config.semi_autonomous.safety.read_only_paths):
        return None
    label = project.name or project.root.name
    return (
        f"{rel} is read-only in project {label} "
        "(semi_autonomous.safety.read_only_paths in its scaffold.yaml). Ask the human "
        "to make this change or approve it explicitly; to stop this check, set "
        "agents.protect_read_only_paths: false."
    )


def _manifest(home: Path | None = None) -> dict[str, Any]:
    path = (home or resolve_home_dir()) / MANIFEST_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def plugin_paths_for(roots: Sequence[str], home: Path | None = None) -> list[str]:
    """Installed plugin directories for the projects in a workspace.

    The shared routing plugin comes once, followed by one pointer plugin per
    matching project. Only directories the install manifest lists, and that
    still exist, are returned.
    """
    plugins = _manifest(home).get("cursor_plugins")
    if not isinstance(plugins, dict):
        return []
    pointers = plugins.get("projects")
    if not isinstance(pointers, dict):
        return []
    names = projects_for_roots(roots, load_registered_projects(home))
    matched = [pointers[name] for name in names if isinstance(pointers.get(name), str)]
    matched = [p for p in matched if Path(p).is_dir()]
    if not matched:
        return []
    shared = plugins.get("shared")
    if isinstance(shared, str) and Path(shared).is_dir():
        return [shared, *matched]
    return matched


def session_context_for(cwd: str, home: Path | None = None) -> str:
    """The pointer guidance for the projects in a Claude Code session's folder."""
    pointers = _manifest(home).get("claude_context")
    if not isinstance(pointers, dict):
        return ""
    names = projects_for_roots([cwd], load_registered_projects(home))
    parts: list[str] = []
    for name in names:
        path = pointers.get(name)
        if not isinstance(path, str):
            continue
        try:
            parts.append(Path(path).read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return "\n\n".join(parts)


def handle_event(event: str, payload: dict[str, Any], scope: str) -> str:
    """Return the response for *event*. Raises on internal errors; see :func:`main`."""
    if os.environ.get(DISABLE_ENV) == "1":
        return _ALLOW_RESPONSES[event]

    if event in ("cursor-after-edit", "claude-post-tool-use"):
        handle_edit(payload, scope, event)
        return _ALLOW_RESPONSES[event]

    if event == "cursor-pre-edit":
        reason = protected_reason(payload, scope)
        if reason is None:
            return _ALLOW_RESPONSES[event]
        return json.dumps({"permission": "deny", "user_message": reason, "agent_message": reason})

    if event == "claude-pre-edit":
        reason = protected_reason(payload, scope)
        if reason is None:
            return _ALLOW_RESPONSES[event]
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )

    if event == "cursor-workspace-open":
        roots = payload.get("workspace_roots")
        paths = plugin_paths_for(roots if isinstance(roots, list) else [])
        return json.dumps({"pluginPaths": paths}) if paths else _ALLOW_RESPONSES[event]

    if event == "claude-session-start":
        cwd = payload.get("cwd")
        text = session_context_for(cwd) if isinstance(cwd, str) and cwd else ""
        if not text:
            return _ALLOW_RESPONSES[event]
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": text,
                }
            }
        )

    if event == "git-post-commit":
        project = resolve_edit_target(os.path.realpath(os.getcwd()), scope)
        if project is not None:
            spawn_worker("embed", project, event)
        return _ALLOW_RESPONSES[event]

    return _ALLOW_RESPONSES[event]


def _parse_args(argv: Sequence[str]) -> tuple[str, str]:
    event = argv[0] if argv else ""
    scope = "user"
    rest = list(argv[1:])
    if "--scope" in rest:
        index = rest.index("--scope")
        if index + 1 < len(rest) and rest[index + 1] in SCOPES:
            scope = rest[index + 1]
    return event, scope


def main(argv: Sequence[str] | None = None, *, stdin: Any = None, stdout: Any = None) -> int:
    """Run one hook event. Always exits 0 and writes at most one response."""
    event, scope = _parse_args(list(sys.argv[1:] if argv is None else argv))
    out = stdout if stdout is not None else sys.stdout
    response = _ALLOW_RESPONSES.get(event, "{}")

    saved_stdout = sys.stdout
    sys.stdout = sys.stderr
    started = time.monotonic()
    try:
        if event in _ALLOW_RESPONSES:
            response = handle_event(event, read_payload(stdin), scope)
    except BaseException as exc:  # noqa: BLE001 - a hook must never fail the editor
        print(f"agentscaffold hook {event}: {type(exc).__name__}: {exc}", file=sys.stderr)
        response = _ALLOW_RESPONSES.get(event, "{}")
    finally:
        sys.stdout = saved_stdout
    if os.environ.get("SCAFFOLD_HOOK_TIMING") == "1":
        print(f"agentscaffold hook {event}: {time.monotonic() - started:.3f}s", file=sys.stderr)

    if response:
        out.write(response + "\n")
        out.flush()
    return 0


def console_main() -> None:
    """Entry point for the ``scaffold-hook`` console script."""
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    console_main()
