"""User-scope guidance and hooks.

``scaffold agents install --scope user`` makes guidance and hooks reach a
registered project that is not the editor's workspace root, without writing
anything into the repository. Everything it writes is in the user's home:

- **Cursor rules** are generated plugins under ``$AGENTSCAFFOLD_HOME/cursor-plugins``:
  one shared routing plugin plus one small pointer plugin per project. A
  user-level ``workspaceOpen`` hook (``scaffold-hook cursor-workspace-open``)
  returns the plugins for the projects in the opened workspace, so the rules
  apply only there. Plugins ship no
  ``mcp.json``: the shared server is registered once by ``scaffold mcp install``.
- **Cursor hooks** are entries in ``~/.cursor/hooks.json`` for ``workspaceOpen``,
  ``afterFileEdit`` and ``preToolUse`` (matcher ``Write``).
- **Claude Code** gets ``SessionStart``, ``PostToolUse`` and ``PreToolUse``
  entries in ``~/.claude/settings.json``; session start adds the project
  pointer text to the session's context.

Shared files are merged, never replaced: other tools' entries survive, a
timestamped backup is taken before the first change, the write is atomic
(Cursor reloads ``hooks.json`` as soon as it changes), and a file that does not
parse is refused rather than overwritten. The install manifest
(``$AGENTSCAFFOLD_HOME/user-install.json``) records what was written so
``--uninstall`` removes exactly that.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import tempfile
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscaffold import __version__
from agentscaffold.config_home import resolve_home_dir
from agentscaffold.hooks.router import EVENTS, MANIFEST_FILENAME

CLIENTS = ("cursor", "claude")
COMPONENTS = ("rules", "hooks")

MANIFEST_VERSION = 1
PLUGINS_DIRNAME = "cursor-plugins"
CLAUDE_CONTEXT_DIRNAME = "claude-context"
SHARED_PLUGIN_NAME = "agentscaffold-routing"
SHARED_RULE_NAME = "agentscaffold-routing.mdc"
POINTER_RULE_NAME = "agentscaffold-project.mdc"
GENERATOR = "scaffold agents install --scope user"

#: Claude Code tool names that write files.
CLAUDE_EDIT_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"


class UserScopeError(Exception):
    """An install or uninstall that must stop before writing anything."""


@dataclass(frozen=True)
class HookEntry:
    """One hook entry this install owns, in one client's settings file."""

    client: str
    component: str
    event: str
    router_event: str
    matcher: str | None = None


#: Every hook entry, by client. ``rules`` entries deliver guidance;
#: ``hooks`` entries index and guard edits.
HOOK_ENTRIES: tuple[HookEntry, ...] = (
    HookEntry("cursor", "rules", "workspaceOpen", "cursor-workspace-open"),
    HookEntry("cursor", "hooks", "afterFileEdit", "cursor-after-edit"),
    HookEntry("cursor", "hooks", "preToolUse", "cursor-pre-edit", matcher="Write"),
    HookEntry("claude", "rules", "SessionStart", "claude-session-start", matcher=""),
    HookEntry("claude", "hooks", "PostToolUse", "claude-post-tool-use", CLAUDE_EDIT_MATCHER),
    HookEntry("claude", "hooks", "PreToolUse", "claude-pre-edit", CLAUDE_EDIT_MATCHER),
)


@dataclass(frozen=True)
class ProjectTarget:
    """A registered project to cover."""

    name: str
    root: Path


@dataclass
class InstallReport:
    """What an install or uninstall did (or, on a dry run, would do)."""

    dry_run: bool
    written: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    merged: list[Path] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Locations:
    """Where an install writes. Tests point these at a temporary home."""

    home: Path
    cursor_home: Path
    claude_home: Path

    @classmethod
    def default(cls) -> Locations:
        return cls(
            home=resolve_home_dir(),
            cursor_home=Path.home() / ".cursor",
            claude_home=Path.home() / ".claude",
        )

    @property
    def manifest(self) -> Path:
        return self.home / MANIFEST_FILENAME

    @property
    def plugins_dir(self) -> Path:
        return self.home / PLUGINS_DIRNAME

    @property
    def claude_context_dir(self) -> Path:
        return self.home / CLAUDE_CONTEXT_DIRNAME

    def client_settings(self, client: str) -> Path:
        if client == "cursor":
            return self.cursor_home / "hooks.json"
        return self.claude_home / "settings.json"


# ---------------------------------------------------------------------------
# Naming and content
# ---------------------------------------------------------------------------


def plugin_slug(project_name: str) -> str:
    """A kebab-case plugin name for *project_name*, unique per name.

    Project names allow upper case, ``.`` and ``_``; plugin names are
    kebab-case. When folding changes the name, a short hash of the original
    keeps two names that fold alike (``My_App``, ``my-app``) apart.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-") or "project"
    if slug != project_name:
        slug = f"{slug}-{hashlib.sha256(project_name.encode()).hexdigest()[:6]}"
    return f"agentscaffold-{slug}"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rule_file(description: str, body: str) -> str:
    from agentscaffold.rendering import prepend_generated_banner

    content = f"---\ndescription: {description}\nalwaysApply: true\n---\n\n{body}"
    return prepend_generated_banner(
        content, generator=GENERATOR, source="agentscaffold", digest=_sha(body)
    )


def render_shared_rule() -> str:
    """The shared plugin's rule: routing guidance that is the same for every project."""
    from agentscaffold.agents.rule_policy import generate_user_scope_routing_body

    return _rule_file("AgentScaffold MCP routing (user scope)", generate_user_scope_routing_body())


def render_pointer_text(target: ProjectTarget, config: Any) -> str:
    """The per-project pointer: where the project is and how to work in it."""
    from agentscaffold.agents.rule_policy import governance_guardrail_lines

    manual_rel = config.agents.manual_path
    manual = target.root / manual_rel
    if manual.is_file():
        manual_line = (
            f"- The governance manual is `{manual}`. Follow it; `scaffold_orient` carries its "
            "always-on sections and `scaffold_governance` returns any section by heading."
        )
    else:
        manual_line = f"- No governance manual was found at `{manual}`."
    lines = [
        f"# AgentScaffold project: {target.name}",
        "",
        f"This workspace contains the AgentScaffold project `{target.name}` at `{target.root}`.",
        "",
        f"- Pass `working_path` (the file or folder you are working on under `{target.root}`) "
        "on every AgentScaffold MCP tool call about this project.",
        "- At the start of a chat call `scaffold_session_start`, then `scaffold_orient`, and "
        "act on its `recommended_actions`.",
        manual_line,
        "- Full routing policy: MCP resource `agentscaffold://guidance/routing`.",
        "",
        *governance_guardrail_lines(config),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_pointer_rule(target: ProjectTarget, config: Any) -> str:
    return _rule_file(f"AgentScaffold project {target.name}", render_pointer_text(target, config))


def _plugin_manifest(name: str, description: str) -> str:
    return (
        json.dumps({"name": name, "version": __version__, "description": description}, indent=2)
        + "\n"
    )


# ---------------------------------------------------------------------------
# Hook commands and settings merges
# ---------------------------------------------------------------------------


def hook_command_for(router_event: str, hook_command: str) -> str:
    return f"{hook_command} {router_event}"


def is_agentscaffold_hook_command(command: Any) -> bool:
    """True for a command this install (any version, any interpreter path) wrote."""
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) < 2 or tokens[-1] not in EVENTS:
        return False
    program = Path(tokens[0]).name
    if program in ("scaffold-hook", "scaffold-hook.exe"):
        return len(tokens) == 2
    return program in ("scaffold", "scaffold.exe") and tokens[1:-1] == ["hook"]


def load_settings(path: Path) -> dict[str, Any]:
    """Load a client settings file; refuse one that exists but does not parse."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        raise UserScopeError(
            f"{path} is not valid JSON ({exc}). Fix or move it, then re-run; "
            "AgentScaffold will not overwrite a file it cannot read."
        ) from exc
    if not isinstance(data, dict):
        raise UserScopeError(f"{path} must hold a JSON object; refusing to change it.")
    return data


def merge_cursor_hooks(
    document: dict[str, Any], entries: Iterable[HookEntry], hook_command: str
) -> dict[str, Any]:
    """Return *document* with this install's Cursor entries replacing any older ones."""
    merged = _deep_copy(document)
    merged.setdefault("version", 1)
    hooks = merged.setdefault("hooks", {})
    for entry in entries:
        bucket = [e for e in hooks.get(entry.event, []) if not _owned_cursor_entry(e)]
        item: dict[str, Any] = {"command": hook_command_for(entry.router_event, hook_command)}
        if entry.matcher:
            item["matcher"] = entry.matcher
        bucket.append(item)
        hooks[entry.event] = bucket
    return merged


def _deep_copy(document: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = json.loads(json.dumps(document))
    return copied


def remove_cursor_hooks(document: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_copy(document)
    hooks = merged.get("hooks")
    if not isinstance(hooks, dict):
        return merged
    for event in list(hooks):
        bucket = hooks[event]
        if not isinstance(bucket, list):
            continue
        kept = [e for e in bucket if not _owned_cursor_entry(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    return merged


def _owned_cursor_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and is_agentscaffold_hook_command(entry.get("command"))


def merge_claude_hooks(
    document: dict[str, Any], entries: Iterable[HookEntry], hook_command: str
) -> dict[str, Any]:
    """Return *document* with this install's Claude Code entries replacing older ones."""
    merged = remove_claude_hooks(document, events={e.event for e in entries})
    hooks = merged.setdefault("hooks", {})
    for entry in entries:
        hooks.setdefault(entry.event, []).append(
            {
                "matcher": entry.matcher or "",
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command_for(entry.router_event, hook_command),
                    }
                ],
            }
        )
    return merged


def remove_claude_hooks(
    document: dict[str, Any], events: Iterable[str] | None = None
) -> dict[str, Any]:
    merged = _deep_copy(document)
    hooks = merged.get("hooks")
    if not isinstance(hooks, dict):
        return merged
    wanted = set(events) if events is not None else None
    for event in list(hooks):
        if wanted is not None and event not in wanted:
            continue
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            inner = [
                h
                for h in group["hooks"]
                if not (isinstance(h, dict) and is_agentscaffold_hook_command(h.get("command")))
            ]
            if inner:
                kept_groups.append({**group, "hooks": inner})
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        del merged["hooks"]
    return merged


# ---------------------------------------------------------------------------
# File writes
# ---------------------------------------------------------------------------


def atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory and rename over *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else None
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def backup(path: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"{path.name}.agentscaffold-{stamp}.bak")
    counter = 1
    while target.exists():
        target = path.with_name(f"{path.name}.agentscaffold-{stamp}-{counter}.bak")
        counter += 1
    target.write_bytes(path.read_bytes())
    return target


def _settings_text(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


def _write_settings(
    path: Path, before: dict[str, Any], after: dict[str, Any], report: InstallReport
) -> bool:
    if after == before:
        report.unchanged.append(path)
        return False
    report.merged.append(path)
    if report.dry_run:
        return True
    if path.exists():
        report.backups.append(backup(path))
    atomic_write(path, _settings_text(after))
    return True


def _write_file(path: Path, text: str, report: InstallReport) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        report.unchanged.append(path)
        return
    report.written.append(path)
    if not report.dry_run:
        atomic_write(path, text)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def load_manifest(locations: Locations) -> dict[str, Any]:
    try:
        data = json.loads(locations.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def manifest_projects(manifest: dict[str, Any]) -> list[str]:
    plugins = manifest.get("cursor_plugins") or {}
    names = set((plugins.get("projects") or {}).keys())
    names |= set((manifest.get("claude_context") or {}).keys())
    return sorted(names)


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------


def registered_targets(names: Sequence[str] | None = None) -> list[ProjectTarget]:
    """Registered projects to cover; *names* narrows the set and must all exist."""
    from agentscaffold.workspace_registry import load_registry

    registry = load_registry()
    found: dict[str, ProjectTarget] = {}
    for workspace in registry.workspaces:
        for project in workspace.projects:
            found[project.name] = ProjectTarget(project.name, workspace.project_root(project))
    if not names:
        return sorted(found.values(), key=lambda t: t.name)
    unknown = [n for n in names if n not in found]
    if unknown:
        raise UserScopeError(
            f"Not registered: {', '.join(unknown)}. Register with `scaffold project register`."
        )
    return [found[n] for n in names]


def detect_clients(locations: Locations) -> list[str]:
    """Clients whose configuration directory exists on this machine."""
    detected = []
    if locations.cursor_home.is_dir():
        detected.append("cursor")
    if locations.claude_home.is_dir():
        detected.append("claude")
    return detected


def _load_project_config(root: Path) -> Any:
    from agentscaffold.config import ScaffoldConfig, load_config

    path = root / "scaffold.yaml"
    return load_config(path) if path.is_file() else ScaffoldConfig()


def legacy_project_hooks(targets: Iterable[ProjectTarget]) -> list[Path]:
    """Project-level hook scripts that predate the router.

    They keep their own lock under a relative ``.scaffold/`` and fire alongside
    the user-level hook, so both can start an index on one database.
    """
    from agentscaffold.hooks.generators.cursor import INDEX_HOOK_REL_PATH, is_router_shim

    stale = []
    for target in targets:
        script = target.root / INDEX_HOOK_REL_PATH
        try:
            if script.is_file() and not is_router_shim(script.read_text(encoding="utf-8")):
                stale.append(script)
        except OSError:
            continue
    return stale


def install_user_scope(
    *,
    projects: Sequence[str] | None = None,
    components: Sequence[str] = COMPONENTS,
    clients: Sequence[str] | None = None,
    hook_command: str | None = None,
    dry_run: bool = False,
    locations: Locations | None = None,
) -> InstallReport:
    """Install user-scope guidance and hooks for registered projects."""
    loc = locations or Locations.default()
    report = InstallReport(dry_run=dry_run)
    bad = [c for c in components if c not in COMPONENTS]
    if bad:
        raise UserScopeError(f"Unknown component(s): {', '.join(bad)}.")
    chosen = list(clients) if clients is not None else detect_clients(loc)
    bad = [c for c in chosen if c not in CLIENTS]
    if bad:
        raise UserScopeError(f"Unknown client(s): {', '.join(bad)}.")
    if not chosen:
        raise UserScopeError("Neither ~/.cursor nor ~/.claude exists; pass --client to choose one.")

    targets = registered_targets(projects)
    if not targets:
        raise UserScopeError("No registered projects. Run `scaffold project register` first.")

    if hook_command is None:
        from agentscaffold.hooks.generators.cursor import resolve_hook_command

        hook_command = resolve_hook_command()

    # Read every shared settings file first so a bad one stops the install
    # before anything is written.
    settings = {c: load_settings(loc.client_settings(c)) for c in chosen}
    created = {str(loc.client_settings(c)) for c in chosen if not loc.client_settings(c).exists()}

    manifest = load_manifest(loc)
    plugins = dict((manifest.get("cursor_plugins") or {}).get("projects") or {})
    contexts = dict(manifest.get("claude_context") or {})
    files: dict[str, str] = dict(manifest.get("files") or {})
    shared_dir: str | None = (manifest.get("cursor_plugins") or {}).get("shared")

    if "rules" in components:
        if "cursor" in chosen:
            shared = loc.plugins_dir / SHARED_PLUGIN_NAME
            shared_files = {
                shared / ".cursor-plugin" / "plugin.json": _plugin_manifest(
                    SHARED_PLUGIN_NAME, "AgentScaffold MCP routing (generated)"
                ),
                shared / "rules" / SHARED_RULE_NAME: render_shared_rule(),
            }
            for path, text in shared_files.items():
                _write_file(path, text, report)
                files[str(path)] = _sha(text)
            shared_dir = str(shared)
        for target in targets:
            config = _load_project_config(target.root)
            if "cursor" in chosen:
                slug = plugin_slug(target.name)
                pdir = loc.plugins_dir / slug
                pointer_files = {
                    pdir / ".cursor-plugin" / "plugin.json": _plugin_manifest(
                        slug, f"AgentScaffold project {target.name} (generated)"
                    ),
                    pdir / "rules" / POINTER_RULE_NAME: render_pointer_rule(target, config),
                }
                for path, text in pointer_files.items():
                    _write_file(path, text, report)
                    files[str(path)] = _sha(text)
                plugins[target.name] = str(pdir)
            if "claude" in chosen:
                context = loc.claude_context_dir / f"{plugin_slug(target.name)}.md"
                text = render_pointer_text(target, config)
                _write_file(context, text, report)
                files[str(context)] = _sha(text)
                contexts[target.name] = str(context)

    for client in chosen:
        wanted = [e for e in HOOK_ENTRIES if e.client == client and e.component in components]
        if not wanted:
            continue
        path = loc.client_settings(client)
        before = settings[client]
        if client == "cursor":
            after = merge_cursor_hooks(before, wanted, hook_command)
        else:
            after = merge_claude_hooks(before, wanted, hook_command)
        _write_settings(path, before, after, report)

    for script in legacy_project_hooks(targets):
        report.notes.append(
            f"{script} predates the hook router and keeps its own lock; run "
            f"`scaffold agents hooks` in {script.parents[2]} so both hooks share one."
        )

    new_manifest = {
        "version": MANIFEST_VERSION,
        "package_version": __version__,
        "installed_at": time.time(),
        "hook_command": hook_command,
        "clients": sorted(set(chosen) | set(manifest.get("clients") or [])),
        "components": sorted(set(components) | set(manifest.get("components") or [])),
        "cursor_plugins": {"shared": shared_dir, "projects": plugins},
        "claude_context": contexts,
        "files": files,
        "settings_files": sorted(
            {str(loc.client_settings(c)) for c in chosen}
            | set(manifest.get("settings_files") or [])
        ),
        "backups": [*(manifest.get("backups") or []), *(str(b) for b in report.backups)],
        "created_settings": sorted(created | set(manifest.get("created_settings") or [])),
    }
    if not dry_run:
        atomic_write(loc.manifest, json.dumps(new_manifest, indent=2) + "\n")
    return report


def _remove_file(path: Path, report: InstallReport) -> None:
    if not path.is_file():
        return
    report.removed.append(path)
    if not report.dry_run:
        path.unlink()


def _prune_empty_dirs(start: Path, stop: Path) -> None:
    current = start
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def uninstall_user_scope(
    *,
    projects: Sequence[str] | None = None,
    dry_run: bool = False,
    locations: Locations | None = None,
) -> InstallReport:
    """Remove what the install manifest lists.

    With *projects*, only those projects' pointer files go; the shared plugin
    and the hook entries stay for the rest. Without, everything goes, hook
    entries included (backups are kept).
    """
    loc = locations or Locations.default()
    report = InstallReport(dry_run=dry_run)
    manifest = load_manifest(loc)
    if not manifest:
        report.notes.append(f"Nothing to remove: no install manifest at {loc.manifest}.")
        return report

    plugins = dict((manifest.get("cursor_plugins") or {}).get("projects") or {})
    contexts = dict(manifest.get("claude_context") or {})
    files: dict[str, str] = dict(manifest.get("files") or {})
    names = list(projects) if projects else sorted(set(plugins) | set(contexts))

    doomed: list[Path] = []
    for name in names:
        if name in plugins:
            pdir = Path(plugins.pop(name))
            doomed.extend(p for p in map(Path, files) if pdir in p.parents)
        if name in contexts:
            doomed.append(Path(contexts.pop(name)))

    everything = not projects or not (plugins or contexts)
    shared = (manifest.get("cursor_plugins") or {}).get("shared")
    if everything and shared:
        doomed.extend(p for p in map(Path, files) if Path(shared) in p.parents)

    for path in doomed:
        _remove_file(path, report)
        files.pop(str(path), None)
        if not dry_run:
            _prune_empty_dirs(path.parent, loc.home)

    if everything:
        created = set(manifest.get("created_settings") or [])
        for raw in manifest.get("settings_files") or []:
            path = Path(raw)
            before = load_settings(path)
            if path.name == "hooks.json":
                after = remove_cursor_hooks(before)
                leftover = {k: v for k, v in after.items() if not (k == "hooks" and not v)}
                emptied = set(leftover) <= {"version"}
            else:
                after = remove_claude_hooks(before)
                emptied = not after
            if raw in created and emptied:
                _remove_file(path, report)
                continue
            _write_settings(path, before, after, report)
        _remove_file(loc.manifest, report)
        return report

    manifest["cursor_plugins"] = {"shared": shared, "projects": plugins}
    manifest["claude_context"] = contexts
    manifest["files"] = files
    if not dry_run:
        atomic_write(loc.manifest, json.dumps(manifest, indent=2) + "\n")
    return report
