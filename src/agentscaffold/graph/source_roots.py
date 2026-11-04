"""Monorepo module prefixes for Python import resolution (Plan 278).

A project registered at ``<repo>/company/team_x`` is imported as
``company.team_x.foo`` by code that runs from the repository root. The import
resolver works relative to the project root, so it needs to know that
``company.team_x`` names the project root itself. That prefix is inferred from
the project's path below its version-control root, and ``graph.module_prefixes``
adds further prefix-to-directory mappings.
"""

from __future__ import annotations

import keyword
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agentscaffold.paths import vcs_root

if TYPE_CHECKING:
    from agentscaffold.config import GraphConfig

logger = logging.getLogger(__name__)


def is_module_name(dotted: str) -> bool:
    """True when every dotted segment is a Python identifier and not a keyword."""
    segments = dotted.split(".")
    return all(seg.isidentifier() and not keyword.iskeyword(seg) for seg in segments)


def infer_module_prefix(project_root: Path) -> str | None:
    """Return the dotted path of *project_root* below its VCS root, or None.

    Nothing is inferred when there is no VCS root, when the project is the VCS
    root, or when any path segment could not appear in an import statement
    (``team-x``, ``class``).
    """
    root = project_root.resolve()
    repo = vcs_root(root)
    if repo is None or repo == root:
        return None
    parts = root.relative_to(repo).parts
    dotted = ".".join(parts)
    if not is_module_name(dotted):
        logger.debug("No module prefix inferred for %s: %r is not importable", root, dotted)
        return None
    return dotted


def effective_module_prefixes(project_root: Path, config: GraphConfig) -> dict[str, str]:
    """Merge the inferred prefix with ``graph.module_prefixes``.

    The inferred prefix maps to the project root (``"."``). An explicit entry
    for the same prefix replaces it.
    """
    prefixes: dict[str, str] = {}
    if config.infer_module_prefix:
        inferred = infer_module_prefix(project_root)
        if inferred:
            prefixes[inferred] = "."
    prefixes.update(config.module_prefixes)
    return prefixes
