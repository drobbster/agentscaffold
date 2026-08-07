"""MCP resources serving canonical routing guidance (Plan 249 Step B2).

ADR-025 Decision 6 delivers the routing policy three ways from one source: the
canonical committed file, the per-project rule files generated from it, and this
resource. The resource exists so an MCP-first agent can ask for policy rather
than be handed it, and so an agent in a repo with no generated files at all
still has a way to find out how it is meant to behave.

Deliberately independent of the knowledge graph. The other resources in this
server read the graph and error without one, which is right for them -- they
serve indexed facts. Routing guidance is static text, and a fresh clone with no
graph yet is precisely the situation where an agent most needs to be told how to
behave.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.types import Resource

GUIDANCE_ROUTING_URI = "agentscaffold://guidance/routing"


def guidance_resource_definition() -> Resource:
    """Return the MCP resource definition for the routing guidance."""
    from mcp.types import Resource  # noqa: PLC0415
    from pydantic import AnyUrl  # noqa: PLC0415

    return Resource(
        uri=AnyUrl(GUIDANCE_ROUTING_URI),
        name="Routing Guidance",
        description=(
            "Canonical AgentScaffold routing policy: tool selection, graph trust "
            "discipline, workspace scoping, governance guardrails, and the intent map."
        ),
        mimeType="text/markdown",
    )


def read_guidance_routing(project_root: Path | None = None) -> str:
    """Return the canonical routing guidance for *project_root*.

    Prefers the committed canonical file so the resource and the file agents read
    cannot disagree. Falls back to rendering the guidance when no canonical file
    exists -- a lone repo has none by design, and must still be able to ask.
    """
    from agentscaffold.rendering import canonical_guidance_document, canonical_guidance_path

    if project_root is None:
        from agentscaffold.active_root import default_start  # noqa: PLC0415

        project_root = default_start()

    canonical = canonical_guidance_path(project_root)
    if canonical is not None and canonical.is_file():
        return canonical.read_text()

    return canonical_guidance_document(_load_config_or_default(project_root))


def _load_config_or_default(project_root: Path) -> Any:
    """Load *project_root*'s config, falling back to defaults.

    The guidance body varies only with two config values (the emoji prohibition
    and the core standards list), so defaults are a usable answer for a project
    whose config cannot be read.
    """
    from agentscaffold.config import ScaffoldConfig, find_config, load_config  # noqa: PLC0415

    try:
        config_path = find_config(project_root)
        if config_path is not None:
            return load_config(config_path)
    except Exception:  # pragma: no cover - defensive
        pass
    return ScaffoldConfig()
