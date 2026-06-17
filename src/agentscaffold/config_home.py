"""Org/user-level AgentScaffold home resolution (Plan 224).

Shared policy (rigor, gates, standards lists, reviewers, prohibitions) historically
had to be copied into every repo's ``scaffold.yaml`` and drifted. Config
inheritance (``extends:``) lets a project inherit from a base config; the special
base ``home`` resolves to an org/user-level config so one place defines shared
policy for all of a user's repos.

The home directory is ``$AGENTSCAFFOLD_HOME`` if set, else ``~/.agentscaffold``.
The home config is ``<home>/scaffold.yaml``. Resolution is local-only (an env var
or a fixed home path); there is no network or implicit discovery, and config is
parsed as YAML data, never executed.
"""

from __future__ import annotations

import os
from pathlib import Path

from agentscaffold.config import CONFIG_FILENAME

#: Environment variable that overrides the org/user home directory.
HOME_ENV_VAR = "AGENTSCAFFOLD_HOME"

#: Default home directory name under the user's home when the env var is unset.
DEFAULT_HOME_DIRNAME = ".agentscaffold"

#: The literal ``extends`` value that resolves to the org/user home config.
HOME_SENTINEL = "home"


def resolve_home_dir() -> Path:
    """Return the org/user home directory (``$AGENTSCAFFOLD_HOME`` or ``~/.agentscaffold``)."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(os.path.expanduser(override)).resolve()
    return (Path.home() / DEFAULT_HOME_DIRNAME).resolve()


def resolve_home_config() -> Path | None:
    """Return the home ``scaffold.yaml`` if it exists, else None.

    An absent home config is intentionally a no-op (not an error): a repo may set
    ``extends: home`` and still work on a machine that has no shared config.
    """
    candidate = resolve_home_dir() / CONFIG_FILENAME
    return candidate if candidate.is_file() else None
