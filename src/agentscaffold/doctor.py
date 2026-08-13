"""Read-only health checks for an AgentScaffold installation (Plan 249, Step B8).

Phase A and B each moved something that used to be self-evident. The MCP server
became one entry serving every project instead of one entry per project. The
graph moved out of the working tree into a per-workspace state directory. The
routing guidance became generated output with a canonical source. Every one of
those is invisible when correct, and *also* invisible when wrong -- a stale
server answers tool calls, a re-keyed graph re-indexes quietly, an unregenerated
rule file still routes the agent. This module is where that invisibility ends.

Checks are registered in :data:`CHECKS` rather than being called in sequence from
the command, because Plan 251 adds three more (commit durability, intent-map
drift, generated-file banners) and should be able to append rather than rework.

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
    """A named diagnostic. Plan 251 appends to :data:`CHECKS` with these."""

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
    be answered as a synthesised project instead (ADR-026). None of that surfaces
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

    canonical = canonical_guidance_path(context.project_root)
    if canonical is None:
        return CheckResult(
            status="ok",
            summary="No canonical guidance applies here, so there is nothing to drift from.",
            details=[
                "This project's rule files are the only copy: either a lone repo, "
                "or a workspace whose assets are still per-project."
            ],
        )

    drift = detect_guidance_drift(context.project_root)
    if not drift:
        return CheckResult(status="ok", summary="Generated rule files match the canonical source.")

    reasons = {
        "stale": "stale (generated from an older canonical)",
        "unstamped": "unstamped (hand-edited, or predates the canonical source)",
        "missing_canonical": "cites a canonical file that is gone",
    }
    return CheckResult(
        status="warn",
        summary=f"{len(drift)} generated rule file(s) have drifted.",
        details=[f"{item.path}: {reasons.get(item.reason, item.reason)}" for item in drift],
        remediation="Run `scaffold agents generate-all` to regenerate them.",
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
    # to the command whose job is to verify the migration (Plan 253).
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


def check_version_skew(context: DoctorContext) -> CheckResult:
    """Whether the server the client launches is the CLI you are running.

    This is the failure recorded as a blocker in the governance repo: the MCP
    server ran a pre-0.9.0 install, so composite tools returned a surface that
    had since moved, and every diagnosis pointed at the wrong repo because the
    CLI in the terminal was fine.
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

    Reported even when healthy: since Step B4 the graph is no longer where a
    user would think to look, and "which database am I actually reading" is the
    first question every other diagnosis depends on.
    """
    from agentscaffold.paths import (
        _DEFAULT_DB_PATH,
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

    in_tree = workspace_root / _DEFAULT_DB_PATH
    if in_tree.exists() and in_tree != resolved:
        return CheckResult(
            status="warn",
            summary="An in-tree graph is being ignored.",
            details=details + [f"orphaned: {in_tree}"],
            remediation=(
                "It is not the database in use. Remove it, or run "
                "`scaffold workspace migrate-state --restore` to go back to it."
            ),
        )
    return CheckResult(status="ok", summary="Graph resolves as expected.", details=details)


# ---------------------------------------------------------------------------
# Workspace id agreement
# ---------------------------------------------------------------------------


def check_workspace_id(context: DoctorContext) -> CheckResult:
    """Whether the manifest and the registry name this workspace the same way.

    Added after Step B5 found them diverging in practice. It is silent damage:
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

    Plan 255 added ``BacklogItem.resolution`` only inside ``init_schema``, so
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


CHECKS: list[Check] = [
    Check("registry", "Workspace registry", check_registry),
    Check("workspace_id", "Workspace identity", check_workspace_id),
    Check("guidance", "Routing guidance", check_guidance),
    Check("mcp_registration", "MCP registration", check_mcp_registration),
    Check("version_skew", "Version skew", check_version_skew),
    Check("state_location", "Graph state location", check_state_location),
    Check("graph_schema", "Graph schema", check_graph_schema),
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
