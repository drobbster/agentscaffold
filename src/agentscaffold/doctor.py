"""Read-only health checks for an AgentScaffold installation.

Recent releases each moved something that used to be self-evident. The MCP server
became one entry serving every project instead of one entry per project. The
graph moved out of the working tree into a per-workspace state directory. The
routing guidance became generated output with a canonical source. Every one of
those is invisible when correct, and *also* invisible when wrong -- a stale
server answers tool calls, a re-keyed graph re-indexes quietly, an unregenerated
rule file still routes the agent. This module is where that invisibility ends.

Checks are registered in :data:`CHECKS` rather than being called in sequence from
the command, so later checks (commit durability, intent-map drift,
generated-file banners) can append rather than rework.

Every check is read-only. Nothing here creates, writes, or repairs; a check that
fixed things would be a check nobody could safely run on a broken machine, which
is the only time anyone runs it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agentscaffold import __version__

Status = Literal["ok", "warn", "fail", "skip"]

#: How long to wait for a probed executable to report its version. The probe
#: exists to diagnose a broken install, so it must not itself hang on one.
_PROBE_TIMEOUT_SECONDS = 10.0


@dataclass
class CheckResult:
    """The outcome of one check.

    *details* carries the specifics a user needs to act -- the entry name, the
    path, the two versions that disagree. A summary alone reproduces the problem
    this command exists to solve: knowing something is wrong without being told
    what.
    """

    status: Status
    summary: str
    details: list[str] = field(default_factory=list)
    remediation: str | None = None


@dataclass
class DoctorContext:
    """What every check is allowed to look at."""

    project_root: Path
    mcp_config_path: Path


@dataclass(frozen=True)
class Check:
    """A named diagnostic. New checks append to :data:`CHECKS` with these."""

    name: str
    title: str
    run: Callable[[DoctorContext], CheckResult]


# ---------------------------------------------------------------------------
# Registry health
# ---------------------------------------------------------------------------


def check_registry(context: DoctorContext) -> CheckResult:
    """Registered roots that are no longer there.

    A moved or deleted repository leaves an entry behind, and that entry still
    participates in longest-prefix resolution -- so it is not merely untidy, it
    can win a match for a path underneath it.
    """
    from agentscaffold.workspace_registry import load_registry

    try:
        registry = load_registry()
    except Exception as exc:  # pragma: no cover - unreadable registry
        return CheckResult(
            status="fail",
            summary="The workspace registry could not be read.",
            details=[str(exc)],
            remediation="Inspect ~/.agentscaffold/registry.yaml, or delete it to start over.",
        )

    missing: list[str] = []
    for workspace in registry.workspaces:
        root = Path(workspace.root)
        if not root.is_dir():
            missing.append(f"{workspace.id} -> {workspace.root} (root is gone)")
            continue
        for project in workspace.projects:
            if not workspace.project_root(project).is_dir():
                missing.append(f"{project.name} -> {workspace.project_root(project)} (gone)")

    if not registry.workspaces:
        return CheckResult(status="ok", summary="No workspaces registered.")
    if missing:
        return CheckResult(
            status="warn",
            summary=f"{len(missing)} registered path(s) no longer exist.",
            details=missing,
            remediation="Run `scaffold gc --apply` to prune them.",
        )
    drift = _manifest_registry_drift(registry)
    if drift:
        return CheckResult(
            status="warn",
            summary=f"{len(drift)} project(s) declared in a workspace.yaml are not registered.",
            details=drift,
            remediation=(
                "Run `scaffold project register <path>` for each, or "
                "`scaffold workspace onboard` to re-register the workspace."
            ),
        )
    return CheckResult(
        status="ok",
        summary=f"{len(registry.workspaces)} workspace(s) registered, all present.",
    )


def _manifest_registry_drift(registry: Any) -> list[str]:
    """Projects a registered workspace declares but has not registered.

    Registration snapshots the manifest, so a project added to ``workspace.yaml``
    afterwards is invisible to every registry-driven read: it cannot be named with
    ``project=``, it is absent from the candidate list in a refusal, and it is not
    a registered root -- which used to mean a call anchored at its workspace could
    be answered as a synthesised project instead. None of that surfaces
    as an error, so the drift has to be reported before it can be explained.
    """
    from agentscaffold.config import load_workspace_manifest

    drift: list[str] = []
    for workspace in registry.workspaces:
        manifest = Path(workspace.root) / "workspace.yaml"
        if not manifest.is_file():
            continue
        try:
            declared = load_workspace_manifest(manifest).projects
        except Exception:  # noqa: BLE001 - a malformed manifest is check_config's business
            continue
        registered = {entry.name for entry in workspace.projects}
        for entry in declared:
            if entry.name not in registered:
                drift.append(f"{entry.name} (declared in {manifest}, not in the registry)")
    return drift


# ---------------------------------------------------------------------------
# Guidance drift
# ---------------------------------------------------------------------------


def check_guidance(context: DoctorContext) -> CheckResult:
    """Generated rule files that no longer match the canonical guidance.

    Silence here is correct for a lone repo, which has no canonical file by
    design -- its rule files are the only copy and cannot drift from anything.
    """
    from agentscaffold.rendering import canonical_guidance_path, detect_guidance_drift

    user_drift = user_copy_drift()
    user_remedy = "Run `scaffold agents install --scope user` to regenerate the user-scope copies."
    canonical = canonical_guidance_path(context.project_root)
    if canonical is None:
        if user_drift:
            return CheckResult(
                status="warn",
                summary=f"{len(user_drift)} user-scope guidance file(s) have drifted.",
                details=user_drift,
                remediation=user_remedy,
            )
        return CheckResult(
            status="ok",
            summary="No canonical guidance applies here, so there is nothing to drift from.",
            details=[
                "This project's rule files are the only copy: either a lone repo, "
                "or a workspace whose assets are still per-project."
            ],
        )

    drift = detect_guidance_drift(context.project_root)
    if not drift and not user_drift:
        return CheckResult(status="ok", summary="Generated rule files match the canonical source.")

    reasons = {
        "stale": "stale (generated from an older canonical)",
        "unstamped": "unstamped (hand-edited, or predates the canonical source)",
        "missing_canonical": "cites a canonical file that is gone",
    }
    remedies = ["Run `scaffold agents generate-all` to regenerate them."] if drift else []
    if user_drift:
        remedies.append(user_remedy)
    return CheckResult(
        status="warn",
        summary=f"{len(drift) + len(user_drift)} generated rule file(s) have drifted.",
        details=[f"{item.path}: {reasons.get(item.reason, item.reason)}" for item in drift]
        + user_drift,
        remediation=" ".join(remedies),
    )


def _user_install_manifest() -> dict[str, Any]:
    from agentscaffold.config_home import resolve_home_dir
    from agentscaffold.hooks.router import MANIFEST_FILENAME

    try:
        data = json.loads((resolve_home_dir() / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def user_copy_drift() -> list[str]:
    """User-scope files that are gone, hand-edited, or behind the package.

    The install manifest records a hash per file it wrote; the shared routing
    rule is also re-rendered, because it changes when the package does.
    """
    import hashlib

    manifest = _user_install_manifest()
    files = manifest.get("files")
    if not isinstance(files, dict):
        return []
    from agentscaffold.agents.user_scope import SHARED_RULE_NAME, render_shared_rule

    problems: list[str] = []
    for raw, recorded in sorted(files.items()):
        path = Path(raw)
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            problems.append(f"{path}: missing (user scope)")
            continue
        if current != recorded:
            problems.append(f"{path}: edited since it was installed (user scope)")
        elif path.name == SHARED_RULE_NAME:
            fresh = hashlib.sha256(render_shared_rule().encode("utf-8")).hexdigest()
            if fresh != recorded:
                problems.append(f"{path}: stale (generated by an older AgentScaffold)")
    return problems


def check_guidance_ignored(context: DoctorContext) -> CheckResult:
    """Guidance files that git will not commit.

    A parent-directory exclude (``.cursor/``) cannot be undone by a file-level
    negation. Remediation is directory-scoped: ``.cursor/*`` plus
    ``!.cursor/rules/``.
    """
    from agentscaffold.rendering import GUIDANCE_IGNORE_REMEDIATION, ignored_guidance_files

    ignored = ignored_guidance_files(context.project_root)
    if not ignored:
        return CheckResult(
            status="ok",
            summary="Generated guidance files are not gitignored.",
        )
    config = _project_config(context.project_root)
    if config is not None and config.agents.durability == "local":
        return CheckResult(
            status="ok",
            summary=f"{len(ignored)} guidance file(s) are gitignored, as intended.",
            details=["agents.durability is 'local': generated guidance stays on this machine."],
        )
    return CheckResult(
        status="warn",
        summary=f"{len(ignored)} guidance file(s) are ignored by git.",
        details=[str(path) for path in ignored],
        remediation=GUIDANCE_IGNORE_REMEDIATION
        + " Or set agents.durability: local if they are meant to stay uncommitted.",
    )


def _project_config(root: Path) -> Any:
    """The project's ScaffoldConfig, defaults without a scaffold.yaml, None if unreadable."""
    from agentscaffold.config import ScaffoldConfig, load_config

    path = root / "scaffold.yaml"
    try:
        return load_config(path) if path.is_file() else ScaffoldConfig()
    except Exception:  # noqa: BLE001 - other checks report a broken scaffold.yaml
        return None


# ---------------------------------------------------------------------------
# Reachability and hook liveness
# ---------------------------------------------------------------------------

#: Project-level files an editor reads only from the folder it opened.
_ROOT_ONLY_GUIDANCE = (".cursor/hooks.json", ".claude/settings.json", ".windsurfrules")

#: A hook that has not run for this long, while the graph was indexed since, is suspect.
HOOK_SILENCE_SECONDS = 7 * 24 * 3600


def _vcs_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _registered_name(root: Path) -> str | None:
    from agentscaffold.hooks.router import load_registered_projects, resolve_registered

    routed = resolve_registered(str(root.resolve()), load_registered_projects())
    return routed.name if routed is not None else None


def _user_scope_covers(name: str | None, manifest: dict[str, Any]) -> bool:
    if name is None:
        return False
    plugins = (manifest.get("cursor_plugins") or {}).get("projects") or {}
    contexts = manifest.get("claude_context") or {}
    return name in plugins or name in contexts


def check_guidance_reachable(context: DoctorContext) -> CheckResult:
    """Project-level rules and hooks that the editor will not load.

    Cursor and Claude Code read ``.cursor/`` and ``.claude/`` from the folder
    that was opened, so a project below its repository root gets them only when
    someone opens the project folder itself. A user-scope install delivers the
    same guidance and hooks wherever the workspace is opened.
    """
    root = context.project_root.resolve()
    vcs_root = _vcs_root(root)
    if vcs_root is None or vcs_root == root:
        return CheckResult(
            status="ok",
            summary="The project is its repository root; project-level guidance loads there.",
        )

    files = [root / rel for rel in _ROOT_ONLY_GUIDANCE if (root / rel).is_file()]
    rules_dir = root / ".cursor" / "rules"
    if rules_dir.is_dir():
        files += sorted(p for p in rules_dir.rglob("*") if p.is_file())
    name = _registered_name(root)
    covered = _user_scope_covers(name, _user_install_manifest())
    details = [f"repository root: {vcs_root}"] + [str(p.relative_to(root)) for p in files]
    if covered:
        return CheckResult(
            status="ok",
            summary=f"A user-scope install covers project {name} wherever it is opened.",
            details=details,
        )
    if not files:
        return CheckResult(
            status="ok",
            summary="No project-level rule or hook files to reach.",
            details=details,
        )
    if name is None:
        remediation = (
            "Register the project (`scaffold project register`), then run "
            "`scaffold agents install --scope user`."
        )
    else:
        remediation = f"Run `scaffold agents install --scope user --project {name}`."
    return CheckResult(
        status="warn",
        summary=(
            f"{len(files)} project-level file(s) load only when {root.name}/ itself is "
            "opened, not the repository root."
        ),
        details=details,
        remediation=remediation,
    )


def _project_hook_kind(root: Path) -> str | None:
    """``shim``, ``legacy`` or None for the project-level edit hook script."""
    from agentscaffold.hooks.generators.cursor import INDEX_HOOK_REL_PATH, is_router_shim

    script = root / INDEX_HOOK_REL_PATH
    try:
        text = script.read_text(encoding="utf-8")
    except OSError:
        return None
    return "shim" if is_router_shim(text) else "legacy"


def check_hooks_ran(context: DoctorContext) -> CheckResult:
    """An edit hook that is installed but has never fired.

    The worker writes ``hook.last_run`` beside the graph each time a hook
    reaches it. A graph that keeps being indexed while that file is missing or
    old means the index is being refreshed some other way and the hook is not
    running. Also flags a project still on the pre-router shell hook alongside
    a user-scope hook: the two keep different locks.
    """
    import time

    from agentscaffold.hooks.worker import read_last_run
    from agentscaffold.paths import resolve_db_path

    root = context.project_root.resolve()
    project_hook = _project_hook_kind(root)
    manifest = _user_install_manifest()
    user_hooks = (
        "hooks" in (manifest.get("components") or []) and _registered_name(root) is not None
    )
    if project_hook is None and not user_hooks:
        return CheckResult(status="skip", summary="No edit hook is installed for this project.")

    if project_hook == "legacy" and user_hooks:
        return CheckResult(
            status="warn",
            summary="Two edit hooks with different locks can index this project at once.",
            details=[
                "project hook: pre-router shell script (lock under ./.scaffold/)",
                "user hook: router (lock in the graph's state directory)",
            ],
            remediation="Run `scaffold agents hooks` in the project to regenerate it as a shim.",
        )

    config = _project_config(root)
    try:
        db_path = resolve_db_path(config, start=root)
    except Exception as exc:  # pragma: no cover - unresolvable layout
        return CheckResult(
            status="skip", summary="Could not resolve the graph.", details=[str(exc)]
        )
    last = read_last_run(db_path.parent)
    try:
        indexed_at: float | None = db_path.stat().st_mtime
    except OSError:
        indexed_at = None
    installed = ", ".join(
        label
        for label, present in (("project", project_hook is not None), ("user", user_hooks))
        if present
    )

    last = last or {}
    ran_at = last.get("at")
    if isinstance(ran_at, (int, float)):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ran_at))
        stale = (
            indexed_at is not None
            and time.time() - ran_at > HOOK_SILENCE_SECONDS
            and indexed_at > ran_at + 24 * 3600
        )
        if not stale:
            return CheckResult(
                status="ok",
                summary=f"Edit hook last ran {when} ({last.get('event', 'unknown event')}).",
                details=[f"installed: {installed}"],
            )
        return CheckResult(
            status="warn",
            summary=f"Edit hook has not run since {when}, but the graph was indexed since.",
            details=[f"installed: {installed}", f"graph: {db_path}"],
            remediation=(
                "Check that the editor trusts its hooks (Cursor: Settings, Hooks) and that "
                "SCAFFOLD_HOOK_DISABLE is not set."
            ),
        )
    if indexed_at is None:
        return CheckResult(
            status="ok",
            summary="Edit hook installed; no graph yet, so it has had nothing to do.",
            details=[f"installed: {installed}"],
        )
    return CheckResult(
        status="warn",
        summary="Edit hook is installed but has never recorded a run.",
        details=[f"installed: {installed}", f"graph: {db_path}"],
        remediation=(
            "Make an agent edit in this project and re-run doctor. If it still has not "
            "run, check the editor's hook settings and SCAFFOLD_HOOK_DISABLE."
        ),
    )


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def _load_client_config(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _entry_command_text(entry: dict[str, Any]) -> str:
    """Flatten an entry's command and arguments into one searchable string."""
    parts = [str(entry.get("command", ""))]
    parts.extend(str(arg) for arg in entry.get("args", []) or [])
    return " ".join(parts)


def _looks_like_an_interpreter_path(entry: dict[str, Any]) -> bool:
    """Whether the entry launches a pinned interpreter rather than ``scaffold``.

    A pinned absolute path is the mechanism behind the version skew this command
    was specified to catch: rebuild the venv and the entry keeps launching
    whatever is left at that path, forever, without an error.
    """
    command = str(entry.get("command", ""))
    if not command:
        return False
    name = Path(command).name.lower()
    is_python = name.startswith("python") or name in {"python.exe", "pythonw.exe"}
    return is_python and Path(command).is_absolute()


def _is_cd_bound(entry: dict[str, Any]) -> bool:
    """Whether the entry pins itself to one directory before launching."""
    text = _entry_command_text(entry)
    return "cd " in text or "--cwd" in text or bool(entry.get("cwd"))


def _agentscaffold_entries(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from agentscaffold.mcp.install import SERVERS_KEY, is_agentscaffold_entry

    servers = document.get(SERVERS_KEY) or {}
    return {
        name: entry
        for name, entry in servers.items()
        if is_agentscaffold_entry(name) and isinstance(entry, dict)
    }


def check_mcp_registration(context: DoctorContext) -> CheckResult:
    """Cursor's canonical-entry check, plus Claude Code when that client expects a server."""
    cursor = _cursor_mcp_registration(context)
    claude = _claude_mcp_registration()
    if claude is None:
        return cursor
    rank = {"fail": 3, "warn": 2, "ok": 1, "skip": 0}
    worst = cursor if rank[cursor.status] >= rank[claude.status] else claude
    return CheckResult(
        status=worst.status,
        summary=f"{cursor.summary} {claude.summary}",
        details=[*cursor.details, *claude.details],
        remediation=claude.remediation or cursor.remediation,
    )


def _cursor_mcp_registration(context: DoctorContext) -> CheckResult:
    """Duplicate, `cd`-bound, or interpreter-pinned server entries."""
    document = _load_client_config(context.mcp_config_path)
    if document is None:
        return CheckResult(
            status="skip",
            summary=f"No MCP client config at {context.mcp_config_path}.",
        )

    entries = _agentscaffold_entries(document)
    if not entries:
        return CheckResult(
            status="warn",
            summary="No AgentScaffold server is registered with the client.",
            remediation="Run `scaffold mcp install`.",
        )

    problems: list[str] = []
    from agentscaffold.mcp.install import CANONICAL_ENTRY_NAME

    for name in sorted(entries):
        if name != CANONICAL_ENTRY_NAME:
            problems.append(f"{name}: legacy per-project entry, superseded by one shared server")
        entry = entries[name]
        if _is_cd_bound(entry):
            problems.append(f"{name}: bound to one directory with cd/cwd")
        if _looks_like_an_interpreter_path(entry):
            problems.append(
                f"{name}: launches a hardcoded interpreter "
                f"({entry.get('command')}) instead of `scaffold` on PATH"
            )

    # Per-project configs the client also loads. A clean shared config says
    # nothing about these: a `.cursor/mcp.json` holding an agentscaffold entry is
    # a project-scoped server by construction, which is what the 0.10 migration
    # collapses. Checking only the shared config made that regression invisible
    # to the command whose job is to verify the migration.
    from agentscaffold.mcp.install import find_legacy_project_configs, registered_roots

    # Only redundant if a shared server exists to make it redundant. A lone repo
    # whose per-project config is its *only* registration is not misconfigured,
    # and flagging it would be crying wolf -- the absent shared entry is already
    # reported above.
    stray: list[Path] = []
    if CANONICAL_ENTRY_NAME in entries:
        scan_roots: list[Path] = []
        seen: set[str] = set()
        for root in [context.project_root, *registered_roots()]:
            key = str(root)
            if key not in seen:
                seen.add(key)
                scan_roots.append(root)
        stray = find_legacy_project_configs(scan_roots)
    for path in stray:
        problems.append(f"{path}: project-scoped server config, loaded alongside the shared one")

    if problems:
        remediation = "Run `scaffold mcp install --migrate`, then restart the client."
        if stray:
            # Deliberately not offered as an automatic removal: these files are
            # per-repo and often committed, so deleting one on the user's behalf
            # could reach a colleague's checkout through version control.
            removals = " ".join(f"rm {path}" for path in stray)
            remediation = (
                f"Remove the project-scoped config(s) by hand: {removals}. "
                "The shared server already serves these projects."
            )
            if len(problems) > len(stray):
                remediation += " Then run `scaffold mcp install --migrate`."
            remediation += " Restart the client afterwards."
        return CheckResult(
            status="warn",
            summary=f"{len(problems)} problem(s) with the registered server entries.",
            details=problems,
            remediation=remediation,
        )
    return CheckResult(status="ok", summary=f"One canonical entry at {context.mcp_config_path}.")


def _claude_mcp_registration() -> CheckResult | None:
    """None when Claude has no AgentScaffold guidance.

    Cursor-only installs are unchanged.
    """
    from agentscaffold.mcp.claude_register import claude_binary, parse_probe, probe_argv

    manifest = _user_install_manifest()
    clients = manifest.get("clients") or []
    settings_path = Path.home() / ".claude" / "settings.json"
    expecting = "claude" in clients or _claude_settings_expect_server(settings_path)
    if not expecting:
        return None
    remediation = "Run `scaffold mcp install --client claude`."
    binary, reason = claude_binary()
    if binary is None:
        summary = "Claude Code guidance is installed and no server is registered."
        if reason == "refused":
            summary = "Claude Code guidance is installed and the claude binary was refused."
        return CheckResult(status="fail", summary=summary, remediation=remediation)
    try:
        import tempfile

        from agentscaffold.mcp.claude_register import _default_runner

        with tempfile.TemporaryDirectory(prefix="agentscaffold-claude-") as tmp:
            _code, text = _default_runner(probe_argv(str(binary)), Path(tmp))
    except (OSError, Exception) as exc:  # noqa: BLE001 - doctor reports, it does not raise
        return CheckResult(
            status="warn",
            summary=f"Could not check the Claude Code server: {exc}",
            remediation=remediation,
        )
    probe = parse_probe(text)
    if probe.kind == "canonical" and probe.scope == "user" and probe.connected:
        shadows = _claude_scope_shadows(binary)
        if shadows:
            return CheckResult(
                status="warn",
                summary=(
                    "Claude Code user-scope server is connected, but a "
                    "higher-precedence entry hides it."
                ),
                details=shadows,
                remediation=(
                    "Remove that entry with `claude mcp remove agentscaffold "
                    "--scope local` or `--scope project`."
                ),
            )
        return CheckResult(status="ok", summary="Claude Code user-scope server is connected.")
    if probe.kind == "canonical" and probe.scope == "user":
        return CheckResult(
            status="fail",
            summary=(
                "Claude Code has the canonical server but it did not connect"
                + (f": {probe.issue}" if probe.issue else ".")
            ),
            remediation="`scaffold` must be on the PATH Claude Code starts with.",
        )
    if probe.kind == "foreign" and probe.scope == "user":
        return CheckResult(
            status="fail",
            summary="Claude Code has a user-scope server whose command is not scaffold mcp.",
            remediation=remediation,
        )
    if probe.kind == "missing":
        return CheckResult(
            status="fail",
            summary="Claude Code guidance is installed and no server is registered.",
            remediation=remediation,
        )
    return CheckResult(
        status="warn",
        summary="Claude Code server check did not recognize claude mcp get output.",
        details=[probe.raw.strip()] if probe.raw.strip() else [],
        remediation=remediation,
    )


def _claude_scope_shadows(binary: Path) -> list[str]:
    """Higher-precedence Claude entries that are not the canonical server."""
    from agentscaffold.mcp.claude_register import _default_runner, parse_probe, probe_argv
    from agentscaffold.mcp.install import registered_roots

    found: list[str] = []
    for root in registered_roots():
        try:
            _code, text = _default_runner(probe_argv(str(binary)), root)
        except (OSError, Exception):  # noqa: BLE001 - one root must not hide the rest
            found.append(f"{root}: claude mcp get failed")
            continue
        probe = parse_probe(text)
        if probe.scope in {"local", "project"} and not (
            probe.kind == "canonical" and probe.connected
        ):
            found.append(f"{root}: {probe.scope} scope entry outranks the user server")
    return found


def _claude_settings_expect_server(path: Path) -> bool:
    from agentscaffold.agents.user_scope import is_agentscaffold_hook_command

    if not path.is_file():
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return False
    hooks = document.get("hooks") if isinstance(document, dict) else None
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            command = group.get("command")
            if is_agentscaffold_hook_command(command):
                return True
            for inner in group.get("hooks") or []:
                if isinstance(inner, dict) and is_agentscaffold_hook_command(inner.get("command")):
                    return True
    return False


# ---------------------------------------------------------------------------
# Version skew
# ---------------------------------------------------------------------------


def _interpreter_behind(executable: Path) -> str | None:
    """Return the interpreter a console script's shebang names, if any.

    ``scaffold`` installed by pip or uv is a small Python script whose first
    line points at the interpreter of the environment it was installed into.
    Reading it is how this check works against an *old* install: asking
    ``scaffold --version`` only works if that version had the flag, and the
    versions worth catching are precisely the ones that predate it.
    """
    try:
        with executable.open("rb") as handle:
            first = handle.readline(512).decode("utf-8", "replace").strip()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    # `#!/usr/bin/env python3` names the interpreter in the second token.
    tokens = first[2:].strip().split()
    if not tokens:
        return None
    candidate = tokens[1] if Path(tokens[0]).name == "env" and len(tokens) > 1 else tokens[0]
    return candidate if "python" in Path(candidate).name.lower() else None


def _ask_interpreter(interpreter: str) -> str | None:
    return _run_probe([interpreter, "-c", "import agentscaffold; print(agentscaffold.__version__)"])


def _run_probe(argv: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    # `--version` output carries a program name; the version is the last token
    # that starts with a digit.
    for token in reversed(completed.stdout.split()):
        if token and token[0].isdigit():
            return token
    return None


def probe_launched_version(command: str) -> str | None:
    """Ask the executable an MCP entry launches which agentscaffold it has.

    Deliberately a module-level function: it shells out, so tests replace it
    wholesale rather than arranging for a second install to exist. None means
    the question could not be answered -- unresolvable command, timeout, or an
    executable that answered with something unparseable -- which is reported as
    unknown rather than as agreement.
    """
    resolved = shutil.which(command) or (command if Path(command).is_file() else None)
    if resolved is None:
        return None
    executable = Path(resolved)

    if executable.name.lower().startswith("python"):
        return _ask_interpreter(resolved)

    interpreter = _interpreter_behind(executable)
    if interpreter is not None:
        found = _ask_interpreter(interpreter)
        if found is not None:
            return found

    # Native launchers (Windows `scaffold.exe`) carry no shebang to read.
    return _run_probe([resolved, "--version"])


def path_scaffold() -> str | None:
    """The ``scaffold`` executable on PATH, if any.

    A function so tests can replace it. Reading the real PATH would make
    ``doctor`` report on the machine running the suite.
    """
    return shutil.which("scaffold")


def check_path_install(context: DoctorContext) -> CheckResult:
    """Whether ``scaffold`` on PATH is this version.

    ``uv tool install agentscaffold==x.y.z`` records an exact pin.
    ``uv tool upgrade`` then stays on that version, so the terminal and the
    hooks keep launching the old release after a newer one is published.
    """
    found = path_scaffold()
    if not found:
        return CheckResult(status="skip", summary="scaffold is not on PATH.")
    version = probe_launched_version(found)
    if version is None:
        return CheckResult(
            status="warn",
            summary="Could not read the version of scaffold on PATH.",
            details=[found],
        )
    if version == __version__:
        return CheckResult(status="ok", summary=f"scaffold on PATH is {version}.")
    return CheckResult(
        status="warn",
        summary=f"scaffold on PATH is {version}; this command is {__version__}.",
        details=[found],
        remediation=(
            "An exact pin from `uv tool install agentscaffold==...` makes "
            "`uv tool upgrade` stay there. Run `uv tool install -U "
            "'agentscaffold[all]'`, then `scaffold agents hooks` in each project."
        ),
    )


def check_hook_generation(context: DoctorContext) -> CheckResult:
    """Whether the project edit hook is the current shim.

    The older shell hook stores an absolute path to whatever ``scaffold``
    existed when it was generated, so a later upgrade does not reach it.
    """
    kind = _project_hook_kind(context.project_root)
    if kind is None:
        return CheckResult(status="skip", summary="No project edit hook is installed.")
    if kind == "legacy":
        return CheckResult(
            status="warn",
            summary="The edit hook is the pre-router shell script.",
            details=["It launches the scaffold path baked in when it was generated."],
            remediation="Run `scaffold agents hooks` with the scaffold you want it to launch.",
        )
    return CheckResult(status="ok", summary="The edit hook is a router shim.")


def check_version_skew(context: DoctorContext) -> CheckResult:
    """Whether the server the client launches is the CLI you are running.

    This is a failure seen in practice: the MCP server ran a pre-0.9.0 install,
    so composite tools returned a surface that had since moved, and every
    diagnosis pointed at the wrong repo because the CLI in the terminal was fine.
    """
    document = _load_client_config(context.mcp_config_path)
    if document is None:
        return CheckResult(status="skip", summary="No MCP client config to probe.")

    entries = _agentscaffold_entries(document)
    if not entries:
        return CheckResult(status="skip", summary="No AgentScaffold entry to probe.")

    skewed: list[str] = []
    unknown: list[str] = []
    for name in sorted(entries):
        command = str(entries[name].get("command", ""))
        launched = probe_launched_version(command) if command else None
        if launched is None:
            unknown.append(f"{name}: could not determine the version behind `{command}`")
        elif launched != __version__:
            skewed.append(f"{name}: launches agentscaffold {launched}, this CLI is {__version__}")

    if skewed:
        return CheckResult(
            status="fail",
            summary="The MCP server runs a different agentscaffold than this CLI.",
            details=skewed + unknown,
            remediation=(
                "Reinstall agentscaffold into the environment the entry launches, "
                "or run `scaffold mcp install --migrate` to drop the pinned path."
            ),
        )
    if unknown:
        return CheckResult(
            status="warn",
            summary="The version behind the MCP entry is unknown.",
            details=unknown,
            remediation="Check that `scaffold` resolves on the PATH the client uses.",
        )
    return CheckResult(status="ok", summary=f"Client and CLI both run {__version__}.")


# ---------------------------------------------------------------------------
# State location
# ---------------------------------------------------------------------------


def check_state_location(context: DoctorContext) -> CheckResult:
    """Where the graph actually resolves, and what got left behind.

    Reported even when healthy: since state relocation the graph is no longer where a
    user would think to look, and "which database am I actually reading" is the
    first question every other diagnosis depends on.
    """
    from agentscaffold.paths import (
        resolve_db_path,
        resolve_workspace_root,
        resolve_workspace_state_id,
    )

    try:
        resolved = resolve_db_path(None, context.project_root)
        workspace_root = resolve_workspace_root(context.project_root)
        workspace_id = resolve_workspace_state_id(context.project_root)
    except Exception as exc:  # pragma: no cover - unresolvable layout
        return CheckResult(
            status="fail",
            summary="Could not resolve the graph location.",
            details=[str(exc)],
        )

    details = [f"graph: {resolved}"]
    if workspace_id:
        details.append(f"workspace id: {workspace_id}")
    else:
        details.append("workspace id: none (unregistered repo, graph stays in-tree)")

    orphans = [
        candidate
        for candidate in _in_tree_graph_candidates(context.project_root, workspace_root)
        if candidate.exists() and candidate.resolve() != resolved.resolve()
    ]
    if orphans:
        return CheckResult(
            status="warn",
            summary="An in-tree graph is being ignored.",
            details=details + [f"orphaned: {orphan}" for orphan in orphans],
            remediation=(
                "None of these is the database in use. Remove them, or run "
                "`scaffold workspace migrate-state --restore` to go back to the "
                "workspace-root one."
            ),
        )
    return CheckResult(status="ok", summary="Graph resolves as expected.", details=details)


def _in_tree_graph_candidates(project_root: Path, workspace_root: Path) -> list[Path]:
    """Every in-tree graph location a project here may have used.

    The workspace root and each project folder: a team folder that indexed
    before its workspace was registered keeps its own ``.scaffold/`` behind.
    """
    from agentscaffold.paths import _DEFAULT_DB_PATH, load_workspace

    roots = [workspace_root, project_root]
    try:
        workspace = load_workspace(project_root)
    except Exception:
        workspace = None
    if workspace is not None:
        for entry in workspace.projects:
            entry_path = Path(entry.path)
            roots.append(entry_path if entry_path.is_absolute() else workspace_root / entry_path)
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        candidate = root / _DEFAULT_DB_PATH
        key = candidate.resolve()
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)
    return candidates


# ---------------------------------------------------------------------------
# Workspace id agreement
# ---------------------------------------------------------------------------


def check_workspace_id(context: DoctorContext) -> CheckResult:
    """Whether the manifest and the registry name this workspace the same way.

    Added after they were found diverging in practice. It is silent damage:
    resolution prefers the manifest, so the graph keeps working while the
    registry reports an id that keys nothing -- and removing the manifest
    re-keys state to the other id and orphans a populated database.
    """
    from agentscaffold.paths import load_workspace, resolve_workspace_root
    from agentscaffold.workspace_registry import load_registry

    try:
        root = resolve_workspace_root(context.project_root)
        workspace = load_workspace(context.project_root)
        entry = load_registry().find_workspace_by_root(root)
    except Exception:
        return CheckResult(status="skip", summary="No workspace manifest to compare.")

    manifest_id = getattr(workspace, "id", None)
    registry_id = entry.id if entry is not None else None
    if not manifest_id or not registry_id:
        return CheckResult(status="ok", summary="Nothing to disagree about.")
    if manifest_id != registry_id:
        return CheckResult(
            status="fail",
            summary="This workspace is recorded under two different ids.",
            details=[
                f"workspace.yaml: {manifest_id}",
                f"registry: {registry_id}",
                f"root: {root}",
            ],
            remediation=(
                "The manifest wins at resolution time. Re-run "
                "`scaffold project register` from this workspace to make the registry agree."
            ),
        )
    return CheckResult(status="ok", summary=f"Manifest and registry agree on {manifest_id}.")


# ---------------------------------------------------------------------------
# Graph schema vs installed code
# ---------------------------------------------------------------------------


def check_graph_schema(context: DoctorContext) -> CheckResult:
    """Whether the on-disk graph has every additive column the code expects.

    An earlier change added ``BacklogItem.resolution`` only inside ``init_schema``, so
    upgrading the package did not heal an existing graph. 0.10.5 applies those
    columns on writable open; this check reports a graph that is still behind
    without writing anything. A missing graph, or one we cannot open because
    the MCP server holds the file lock, is skip -- not fail.
    """
    from agentscaffold.graph.duckpgq_schema import missing_additive_columns
    from agentscaffold.paths import resolve_db_path

    try:
        resolved = resolve_db_path(None, context.project_root)
    except Exception as exc:  # pragma: no cover - unresolvable layout
        return CheckResult(
            status="fail",
            summary="Could not resolve the graph location.",
            details=[str(exc)],
        )
    if not resolved.is_file():
        return CheckResult(status="skip", summary="No graph to inspect.")

    try:
        import duckdb

        conn = duckdb.connect(str(resolved), read_only=True)
        try:
            missing = missing_additive_columns(conn)
        finally:
            conn.close()
    except Exception as exc:
        message = str(exc).lower()
        if "lock" in message:
            return CheckResult(
                status="skip",
                summary="Graph is locked; could not inspect schema.",
                details=[str(exc)],
            )
        return CheckResult(
            status="warn",
            summary="Could not inspect graph schema.",
            details=[str(exc)],
        )

    if not missing:
        return CheckResult(status="ok", summary="Graph columns match the installed code.")
    details = [f"{table}.{column}" for table, column in missing]
    return CheckResult(
        status="fail",
        summary="Graph schema is behind the installed code.",
        details=details,
        remediation=(
            "Restart the MCP server after upgrading to 0.10.5+, or run "
            "`scaffold index`. Additive columns are applied on writable open "
            "and during index; no rebuild is required."
        ),
    )


def check_unstamped_rows(context: DoctorContext) -> CheckResult:
    """Rows with no project in a multi-project workspace's graph.

    A single-project repo keeps ``project = ''`` by design, so the check only
    runs where scoping filters on the column: there, an empty project is a row
    every scoped read silently skips. Read-only; a missing or locked graph is
    skip.
    """
    from agentscaffold.graph.duckpgq_schema import NODE_TABLE_NAMES
    from agentscaffold.paths import load_workspace, resolve_db_path

    try:
        multi = load_workspace(context.project_root).is_multi_project
        resolved = resolve_db_path(None, context.project_root)
    except Exception:
        return CheckResult(status="skip", summary="No workspace to inspect.")
    if not multi:
        return CheckResult(status="skip", summary="One project here; rows need no project stamp.")
    if not resolved.is_file():
        return CheckResult(status="skip", summary="No graph to inspect.")

    counts: dict[str, int] = {}
    try:
        import duckdb

        conn = duckdb.connect(str(resolved), read_only=True)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE column_name = 'project'"
                ).fetchall()
            }
            for table in NODE_TABLE_NAMES:
                if table not in tables:
                    continue
                row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE project = ''").fetchone()
                if row and row[0]:
                    counts[table] = int(row[0])
        finally:
            conn.close()
    except Exception as exc:
        return CheckResult(
            status="skip" if "lock" in str(exc).lower() else "warn",
            summary="Could not inspect graph rows.",
            details=[str(exc)],
        )

    if not counts:
        return CheckResult(status="ok", summary="Every graph row carries a project.")
    return CheckResult(
        status="warn",
        summary=f"{sum(counts.values())} graph row(s) carry no project; scoped reads skip them.",
        details=[f"{table}: {count}" for table, count in sorted(counts.items())],
        remediation=(
            "Usually left over from before the workspace had more than one project. "
            "Nothing backfills them yet; report the counts if they matter to you."
        ),
    )


def check_governance_mapping(context: DoctorContext) -> CheckResult:
    """Manual sections the MCP server is configured to deliver but cannot find.

    Tools still succeed when a mapped heading is missing; they report it in
    ``missing``. This check names each one so the mapping or the manual can be
    fixed. Headings listed under ``agents.governance.optional`` are never
    reported.
    """
    from agentscaffold.agents.governance_manual import load_manual, normalize_heading
    from agentscaffold.config import ScaffoldConfig, load_config

    config_path = context.project_root / "scaffold.yaml"
    try:
        config = load_config(config_path) if config_path.is_file() else ScaffoldConfig()
    except Exception as exc:
        return CheckResult(
            status="warn", summary="Could not read scaffold.yaml.", details=[str(exc)]
        )
    agents = config.agents
    manual = load_manual(context.project_root, agents.manual_path)
    if manual is None:
        if not agents.agents_md:
            return CheckResult(status="ok", summary="No governance manual is configured.")
        return CheckResult(
            status="warn",
            summary=f"No governance manual at {agents.manual_path}.",
            details=["scaffold_orient and the lifecycle tools will deliver no manual sections."],
            remediation=(
                "Create the manual (scaffold init writes the template), or point "
                "agents.manual_path at it in scaffold.yaml."
            ),
        )

    governance = agents.governance
    optional = {normalize_heading(name.split(" / ")[-1]) for name in governance.optional}
    mapped = [("orient", name) for name in governance.orient]
    for step in ("review", "implementation", "completion", "backlog"):
        mapped += [(step, name) for name in getattr(governance.steps, step)]
    missing = [
        f"{step}: {name}"
        for step, name in mapped
        if manual.resolve(name) is None and normalize_heading(name.split(" / ")[-1]) not in optional
    ]
    if not missing:
        return CheckResult(
            status="ok",
            summary=f"All {len(mapped)} mapped sections found in {manual.path}.",
        )
    return CheckResult(
        status="warn",
        summary=f"{len(missing)} mapped section(s) not found in {manual.path}.",
        details=missing,
        remediation=(
            "Rename the heading in the manual, update agents.governance in scaffold.yaml, "
            "or list it under agents.governance.optional."
        ),
    )


def check_agent_docs(context: DoctorContext) -> CheckResult:
    """Heading overlap in AGENTS.md -- sections copied in twice."""
    from agentscaffold.agents.repair import heading_overlap, split_managed
    from agentscaffold.rendering import markdown_h2_headings

    path = context.project_root / "AGENTS.md"
    if not path.is_file():
        return CheckResult(status="ok", summary="No AGENTS.md in this project.")
    text = path.read_text()
    prefix, managed, _suffix = split_managed(text)
    shared = sorted(set(markdown_h2_headings(prefix)) & set(markdown_h2_headings(managed)))
    repeated = heading_overlap(text)
    if not shared and not repeated:
        return CheckResult(status="ok", summary="AGENTS.md headings are unique.")
    details = [f"shared across managed boundary: {heading}" for heading in shared]
    details.extend(f"repeated: {heading}" for heading in repeated if heading not in shared)
    return CheckResult(
        status="warn",
        summary=f"AGENTS.md has {len(set(shared) | set(repeated))} duplicated heading(s).",
        details=details,
        remediation="Run `scaffold agents repair` (dry run), then `--apply` if the copies match.",
    )


def check_inventory(context: DoctorContext) -> CheckResult:
    """The system inventory: file present, review current, sources match, workflow present.

    A collector on its default sources that finds nothing is normal (the project
    has nothing of that kind yet); explicit ``sources`` that match nothing are
    most likely a wrong glob, so only those are reported.
    """
    import datetime as dt

    from agentscaffold.ci.setup import REVIEW_WORKFLOW
    from agentscaffold.inventory.collectors import expand_sources
    from agentscaffold.inventory.project import (
        ignore_patterns,
        inventory_path,
        load_human_inventory,
    )
    from agentscaffold.inventory.schema import InventoryError

    root = context.project_root
    config = _project_config(root)
    if config is None:
        return CheckResult(status="skip", summary="scaffold.yaml could not be read.")
    if not config.inventory.enabled:
        return CheckResult(
            status="skip",
            summary="The system inventory is not enabled.",
            remediation="Run `scaffold inventory enable` to turn it on.",
        )
    path = inventory_path(root, config)
    if not path.is_file():
        return CheckResult(
            status="warn",
            summary=f"No inventory at {config.inventory.path}.",
            remediation="Run `scaffold inventory enable` (writes only what is missing).",
        )
    try:
        inventory = load_human_inventory(root, config)
    except InventoryError as exc:
        return CheckResult(
            status="warn",
            summary="The inventory cannot be read.",
            details=[str(exc)],
            remediation="Run `scaffold inventory check` for the exact problem.",
        )

    details: list[str] = []
    today = dt.date.today()
    last = inventory.last_review_date
    if last is None:
        details.append("architecture review: last_architecture_review is not recorded")
    elif (today - last).days > inventory.review_cadence_days + 5:
        details.append(
            f"architecture review: last {last}, cadence {inventory.review_cadence_days} days"
        )
    patterns = ignore_patterns(root, config)
    for collector in config.inventory.collectors:
        if collector.sources and not expand_sources(root, collector.sources, ignore=patterns):
            globs = ", ".join(collector.sources)
            details.append(f"collector {collector.name}: sources match no files ({globs})")
    workflows = root / ".github" / "workflows"
    if workflows.is_dir() and not (workflows / REVIEW_WORKFLOW).exists():
        details.append(f"no scheduled review workflow at .github/workflows/{REVIEW_WORKFLOW}")
    if not details:
        return CheckResult(
            status="ok",
            summary=f"{len(inventory.components)} components; review recorded {last}.",
        )
    return CheckResult(
        status="warn",
        summary=f"{len(details)} inventory issue(s).",
        details=details,
        remediation=(
            "Run `scaffold inventory review --record` after the review; fix collector "
            "globs in scaffold.yaml; `scaffold inventory enable` adds a missing workflow."
        ),
    )


def check_claude_hook_overlap(context: DoctorContext) -> CheckResult:
    """Warn when a project and the user-scope install both install Claude hooks."""
    manifest = _user_install_manifest()
    if "claude" not in (manifest.get("clients") or []):
        return CheckResult(status="skip", summary="No user-scope Claude install.")
    from agentscaffold.agents.user_scope import project_claude_hooks_present
    from agentscaffold.mcp.install import registered_roots

    roots: list[Path] = []
    seen: set[str] = set()
    for root in [context.project_root, *registered_roots()]:
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    overlaps = [
        str(root / ".claude" / "settings.json")
        for root in roots
        if project_claude_hooks_present(root / ".claude" / "settings.json")
    ]
    if not overlaps:
        return CheckResult(
            status="ok",
            summary="No project Claude hooks beside the user-scope install.",
        )
    return CheckResult(
        status="warn",
        summary="Claude sessions run both project hooks and the user-scope hooks.",
        details=overlaps,
        remediation=(
            "Disable the claude_code hook platform in that project's scaffold.yaml and "
            "remove the AgentScaffold entries from its .claude/settings.json, or uninstall "
            "the user-scope Claude client."
        ),
    )


def check_claude_permission_rules(context: DoctorContext) -> CheckResult:
    """Warn when recorded allow rules no longer match the read-only tool set."""
    del context
    manifest = _user_install_manifest()
    recorded = manifest.get("claude_permission_rules")
    if not isinstance(recorded, list) or not recorded:
        return CheckResult(status="skip", summary="No recorded Claude permission rules.")
    from agentscaffold.agents.user_scope import read_only_permission_rules

    wanted = set(read_only_permission_rules())
    if set(recorded) == wanted:
        return CheckResult(
            status="ok", summary="Claude permission rules match the read-only tools."
        )
    return CheckResult(
        status="warn",
        summary="Recorded Claude permission rules do not match the read-only tools.",
        remediation="Run `scaffold agents install --scope user`.",
    )


CHECKS: list[Check] = [
    Check("registry", "Workspace registry", check_registry),
    Check("workspace_id", "Workspace identity", check_workspace_id),
    Check("guidance", "Routing guidance", check_guidance),
    Check("guidance_ignored", "Guidance not gitignored", check_guidance_ignored),
    Check("guidance_reachable", "Guidance reaches the editor", check_guidance_reachable),
    Check("agent_docs", "Agent document integrity", check_agent_docs),
    Check("governance_mapping", "Governance manual mapping", check_governance_mapping),
    Check("inventory", "System inventory", check_inventory),
    Check("mcp_registration", "MCP registration", check_mcp_registration),
    Check("claude_hook_overlap", "Claude hook overlap", check_claude_hook_overlap),
    Check("claude_permissions", "Claude permission rules", check_claude_permission_rules),
    Check("version_skew", "Version skew", check_version_skew),
    Check("path_install", "scaffold on PATH", check_path_install),
    Check("hook_generation", "Edit hook generation", check_hook_generation),
    Check("state_location", "Graph state location", check_state_location),
    Check("hooks_ran", "Edit hook activity", check_hooks_ran),
    Check("graph_schema", "Graph schema", check_graph_schema),
    Check("unstamped_rows", "Graph rows without a project", check_unstamped_rows),
]


def default_mcp_config_path() -> Path:
    from agentscaffold.mcp.install import default_config_path

    return default_config_path()


def run_checks(context: DoctorContext) -> list[tuple[Check, CheckResult]]:
    """Run every registered check, never letting one failure hide the rest."""
    results: list[tuple[Check, CheckResult]] = []
    for check in CHECKS:
        try:
            results.append((check, check.run(context)))
        except Exception as exc:  # pragma: no cover - defensive
            results.append(
                (
                    check,
                    CheckResult(
                        status="fail",
                        summary=f"The {check.name} check raised {type(exc).__name__}.",
                        details=[str(exc)],
                    ),
                )
            )
    return results


def worst_status(results: list[tuple[Check, CheckResult]]) -> Status:
    order: list[Status] = ["skip", "ok", "warn", "fail"]
    worst: Status = "ok"
    for _, result in results:
        if order.index(result.status) > order.index(worst):
            worst = result.status
    return worst


__all__ = [
    "CHECKS",
    "Check",
    "CheckResult",
    "DoctorContext",
    "Status",
    "default_mcp_config_path",
    "probe_launched_version",
    "run_checks",
    "worst_status",
]
