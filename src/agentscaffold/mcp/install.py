"""Install the single AgentScaffold entry into a client's MCP config (Plan 249, A8).

Before this, onboarding added one MCP server per project to the shared global
``mcp.json``, each hard-bound to a directory with ``cd`` and often to an absolute
venv path. Registering a third project meant a third server process. The registry
plus call-time resolution make one entry sufficient, and this module writes it.

Everything here is shaped by one fact: ``mcp.json`` is not ours. The user edits
it by hand and other tools register into it, so the risk is not that we write the
wrong AgentScaffold entry -- that is recoverable and obvious -- but that we
quietly damage a server we know nothing about (threat model, Vector 6).

Three properties follow, and the tests pin all three:

**We verify rather than trust.** The candidate document is compared against the
original before anything is written, and the write is refused if any entry we do
not own differs. The threat model originally asked for unrelated entries to
survive "byte-for-byte"; that is unachievable when you parse JSON and serialise
it back, because re-serialising reformats the whole file. The wording was amended
at this step to the property actually being protected -- unchanged *content*,
checked explicitly. Whole-document formatting may change.

**We refuse what we cannot parse.** A config with JSONC comments or a trailing
comma is left untouched and the entry is printed for the user to paste. Guessing
is how unrelated servers get destroyed.

**We do not remove legacy entries unless asked.** Per-project entries keep
working through a deprecation window, so a routine upgrade cannot break a working
setup; ``--migrate`` is the explicit, backed-up opt-in.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscaffold.config import ConfigError

logger = logging.getLogger(__name__)

#: The one entry this installs. Registering more projects adds none.
CANONICAL_ENTRY_NAME = "agentscaffold"

#: Key under which MCP clients list their servers.
SERVERS_KEY = "mcpServers"

#: Default client config. Cursor's user-level config; other clients can be
#: targeted with ``--config``.
DEFAULT_CONFIG_PATH = Path("~/.cursor/mcp.json")


class McpConfigError(ConfigError):
    """Raised when a client config cannot be read or safely rewritten."""


def canonical_entry() -> dict[str, Any]:
    """Return the single server entry.

    No ``cd`` binding, because that is what forced one server per project. No
    interpreter path, because pinning an absolute venv path breaks invisibly when
    the venv is rebuilt -- an observed real-world failure. ``scaffold`` resolves
    through ``PATH``, which is also how it resolves as ``scaffold.exe`` on
    Windows.
    """
    return {"command": "scaffold", "args": ["mcp"]}


def is_agentscaffold_entry(name: str) -> bool:
    """Return whether *name* is an entry AgentScaffold owns and may rewrite.

    Legacy installs named entries per project (``agentscaffold-project-b``), so
    ownership is a prefix test rather than an exact match. It is deliberately
    anchored: a user's own ``my-agent-scaffolding`` server is not ours to touch.
    """
    return (
        name == CANONICAL_ENTRY_NAME
        or name.startswith(f"{CANONICAL_ENTRY_NAME}-")
        or name.startswith(f"{CANONICAL_ENTRY_NAME}_")
    )


def find_legacy_entries(document: dict[str, Any]) -> list[str]:
    """Return AgentScaffold entries other than the canonical one, sorted.

    These are the per-project, ``cd``-bound entries the single-entry install
    replaces. They keep working through a deprecation window, so finding them is
    grounds for a notice, not a failure.
    """
    servers = document.get(SERVERS_KEY) or {}
    return sorted(
        name for name in servers if is_agentscaffold_entry(name) and name != CANONICAL_ENTRY_NAME
    )


#: Relative location of a project-scoped client config.
PROJECT_CONFIG_RELPATH = Path(".cursor") / "mcp.json"


def find_legacy_project_configs(roots: Iterable[Path]) -> list[Path]:
    """Return project-scoped configs that register an AgentScaffold server.

    The second shape of legacy registration, and the one actually found in the
    field. A per-repo ``.cursor/mcp.json`` holding an ``agentscaffold`` entry is
    a per-project server by construction: it is scoped to that checkout and runs
    only when that folder is open. Note that the entry is typically named plainly
    ``agentscaffold``, identical to the canonical name -- so unlike
    :func:`find_legacy_entries`, what makes it legacy is *where it lives*, not
    what it is called. Matching on the name alone would miss every one of them.
    """
    found: list[Path] = []
    for root in roots:
        path = Path(root) / PROJECT_CONFIG_RELPATH
        try:
            document = load_config(path)
        except (McpConfigError, OSError):
            continue
        servers = document.get(SERVERS_KEY) or {}
        if any(is_agentscaffold_entry(name) for name in servers):
            found.append(path)
    return found


def _scan_roots() -> list[Path]:
    """Project roots worth scanning for a legacy per-project config.

    Includes the working directory, not just registered projects, and that is the
    important half. A user who has not run `scaffold project register` yet is
    precisely the user who still has per-project entries -- scanning only the
    registry would stay silent until after they had partly migrated, which is the
    wrong way round for a notice whose job is to prompt the migration. A legacy
    server is launched with its cwd inside the repo that registered it, so this is
    how it recognises its own registration.
    """
    roots: list[Path] = []
    try:
        roots.append(Path.cwd())
    except OSError:  # cwd can be deleted out from under a long-lived process
        pass
    roots.extend(_registered_project_roots())

    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _comparison_key(path: Path) -> str:
    """Normalise *path* so two spellings of one directory compare equal.

    The registry stores a resolved path. A caller arrives with whatever the user
    typed, and the two need not match textually -- observed in the field as
    ``/private/tmp/x`` in the registry against ``/tmp/x`` on the command line.
    ``normcase`` additionally folds case on the platforms where it is not
    significant, so a Windows root does not miss on drive-letter casing.
    """
    try:
        resolved = path.resolve()
    except OSError:  # a path that cannot be stat'ed still has an absolute form
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def registered_roots() -> list[Path]:
    """Every directory the registry knows: workspace roots and project roots.

    Both shapes, because they arise from different commands.
    ``scaffold project register <root>`` records a lone repo as a workspace root
    holding one project at ``.``, so the two coincide; a ``workspace.yaml``
    records projects in subdirectories, where the workspace root is not itself a
    project root. Matching only project paths handles the common case and still
    misses real multi-project layouts.

    Never raises. An unreadable registry yields an empty list so callers fall
    back to their previous behaviour instead of failing over an advisory lookup.
    """
    try:
        from agentscaffold.workspace_registry import load_registry

        registry = load_registry()
    except Exception:  # noqa: BLE001 - an advisory lookup must not break callers
        logger.debug("Could not load registry to list registered roots", exc_info=True)
        return []

    roots: list[Path] = []
    for workspace in registry.workspaces:
        try:
            workspace_root = Path(workspace.root)
        except Exception:  # noqa: BLE001 - skip a malformed entry, keep going
            continue
        roots.append(workspace_root)
        for project in workspace.projects:
            try:
                roots.append(workspace_root / project.path)
            except Exception:  # noqa: BLE001 - skip a malformed entry, keep going
                continue
    return roots


def is_registered_root(path: Path) -> bool:
    """True when *path* is a workspace root or project root in the registry.

    Used to decide whether the shared server already covers a directory, so a
    per-project config need not be generated for it (Plan 253).
    """
    key = _comparison_key(path)
    return any(_comparison_key(root) == key for root in registered_roots())


def _registered_project_roots() -> list[Path]:
    """Best-effort list of registered project roots. Never raises."""
    try:
        from agentscaffold.workspace_registry import load_registry

        registry = load_registry()
    except Exception:  # noqa: BLE001 - a notice must not depend on a readable registry
        logger.debug("Could not load registry for deprecation scan", exc_info=True)
        return []

    roots: list[Path] = []
    for workspace in registry.workspaces:
        for project in workspace.projects:
            try:
                roots.append(Path(workspace.root) / project.path)
            except Exception:  # noqa: BLE001 - skip a malformed entry, keep scanning
                continue
    return roots


#: Emitted at most once per process. A server that repeated this on every call
#: would train the user to filter it out, which is the opposite of the intent.
_deprecation_warned = False


def warn_once_about_legacy_entries(
    config_path: Path | None = None,
    *,
    project_roots: Iterable[Path] | None = None,
) -> str | None:
    """Log a one-time deprecation notice if legacy registrations are configured.

    Checks both shapes: non-canonical ``agentscaffold-*`` entries in the shared
    user config, and per-repo ``.cursor/mcp.json`` files. Returns the message
    emitted, or None if there was nothing to say.

    Purely advisory. Every read failure is swallowed, because a server must never
    fail to start over a notice about configuration it merely observed.
    """
    global _deprecation_warned
    if _deprecation_warned:
        return None

    path = config_path or default_config_path()
    try:
        document = load_config(path)
    except (McpConfigError, OSError):
        # An unreadable or hand-edited config is not our business here, and
        # `scaffold mcp install` already refuses to touch it.
        document = {}

    legacy_entries = find_legacy_entries(document)
    roots = _scan_roots() if project_roots is None else list(project_roots)
    legacy_configs = find_legacy_project_configs(roots)

    if not legacy_entries and not legacy_configs:
        return None

    _deprecation_warned = True

    parts = ["Deprecated per-project AgentScaffold MCP registrations found."]
    if legacy_entries:
        parts.append(f"In {path}: {', '.join(legacy_entries)}.")
    if legacy_configs:
        parts.append("Project-scoped configs: " + ", ".join(str(p) for p in legacy_configs) + ".")
    parts.append(
        "One AgentScaffold server now serves every registered project. These still work, "
        "but will stop being supported."
    )
    if legacy_entries:
        parts.append("Collapse the shared-config entries with: scaffold mcp install --migrate")
    if legacy_configs:
        # Deliberately not offered as an automatic removal. These files are
        # per-repo and often committed, so deleting an entry on the user's behalf
        # could land in someone else's checkout via version control.
        parts.append(
            "Remove the project-scoped entries by hand once "
            "`scaffold mcp install` has run for your user."
        )

    message = " ".join(parts)
    logger.warning(message)
    return message


def reset_deprecation_warning() -> None:
    """Clear the once-per-process latch. For tests."""
    global _deprecation_warned
    _deprecation_warned = False


@dataclass
class InstallPlan:
    """What an install would do, computed before anything is written."""

    document: dict[str, Any]
    changed: bool
    #: Legacy per-project entries present in the config.
    legacy: list[str] = field(default_factory=list)
    #: Legacy entries this plan would remove (non-empty only with ``migrate``).
    removed: list[str] = field(default_factory=list)


def load_config(path: Path) -> dict[str, Any]:
    """Read and validate a client config, or return an empty document.

    An absent file is the normal first-install case, not an error. A file that
    exists but cannot be parsed *is* an error: rewriting a config we do not
    understand is how unrelated servers get destroyed.
    """
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise McpConfigError(
            f"Could not parse {path} as JSON ({exc}). It may contain comments or a "
            "trailing comma, which some clients tolerate. Refusing to rewrite a config "
            "that cannot be parsed; add the entry below by hand instead."
        ) from exc

    if not isinstance(raw, dict):
        raise McpConfigError(
            f"{path} does not contain a JSON object at the top level "
            f"(found {type(raw).__name__}). Refusing to rewrite it."
        )

    servers = raw.get(SERVERS_KEY)
    if servers is not None and not isinstance(servers, dict):
        raise McpConfigError(
            f"{path} has a {SERVERS_KEY!r} value that is not an object "
            f"(found {type(servers).__name__}). Refusing to rewrite it."
        )

    return raw


def plan_changes(original: dict[str, Any], *, migrate: bool) -> InstallPlan:
    """Compute the document that would be written, without writing it.

    Separated from the write so the decision can be shown by ``--dry-run`` and
    tested without a filesystem.
    """
    servers: dict[str, Any] = dict(original.get(SERVERS_KEY) or {})
    legacy = sorted(
        name for name in servers if is_agentscaffold_entry(name) and name != CANONICAL_ENTRY_NAME
    )

    removed: list[str] = []
    if migrate:
        for name in legacy:
            del servers[name]
            removed.append(name)

    servers[CANONICAL_ENTRY_NAME] = canonical_entry()

    document = dict(original)
    document[SERVERS_KEY] = servers

    changed = document != original
    return InstallPlan(document=document, changed=changed, legacy=legacy, removed=removed)


def verify_unrelated_preserved(
    original: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    """Raise unless every entry AgentScaffold does not own is unchanged.

    This is the control, not a sanity check, so it inspects the resulting
    document rather than trusting the code that produced it -- it has to hold
    even if :func:`plan_changes` is one day rewritten wrongly. It fails closed:
    anything unexpected refuses the write.
    """
    original_servers = original.get(SERVERS_KEY) or {}
    candidate_servers = candidate.get(SERVERS_KEY) or {}

    damaged: list[str] = []
    for name, value in original_servers.items():
        if is_agentscaffold_entry(name):
            continue
        if name not in candidate_servers:
            damaged.append(f"{name} (would be removed)")
        elif candidate_servers[name] != value:
            damaged.append(f"{name} (would be modified)")

    for key, value in original.items():
        if key == SERVERS_KEY:
            continue
        if key not in candidate:
            damaged.append(f"{key} (top-level key would be removed)")
        elif candidate[key] != value:
            damaged.append(f"{key} (top-level key would be modified)")

    if damaged:
        raise McpConfigError(
            "Refusing to write: the change would alter configuration AgentScaffold "
            "does not own: " + ", ".join(damaged) + ". Nothing has been written."
        )


def render(document: dict[str, Any]) -> str:
    """Serialise a config document the way clients write it."""
    return json.dumps(document, indent=2) + "\n"


def backup_path(path: Path) -> Path:
    """Return a timestamped backup path alongside *path*."""
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.name}.bak-{stamp}")


def default_config_path() -> Path:
    """Return the default client config path."""
    return DEFAULT_CONFIG_PATH.expanduser()
