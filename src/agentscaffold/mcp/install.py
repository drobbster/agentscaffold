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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscaffold.config import ConfigError

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
