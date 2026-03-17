"""Plugin manifest schema — Step D.4.

Defines the Pydantic model for ``plugin.json``, the descriptor file for
distributable AgentScaffold domain pack plugins.

Fields:
    name         Slug identifier (e.g. "agentscaffold-trading")
    version      Semver string (e.g. "1.0.0")
    description  Human-readable description
    skills       List of SKILL.md relative paths
    agents       List of agent markdown relative paths
    hooks        List of hook config relative paths
    mcp_servers  Dict of MCP server name -> command spec
    domain_pack  Name of the bundled domain pack (optional)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class PluginManifest(BaseModel):
    """Descriptor for a distributable AgentScaffold plugin."""

    name: str
    version: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    mcp_servers: dict[str, Any] = Field(default_factory=dict)
    domain_pack: str | None = None

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"version must be semver, got: {v!r}")
        return v

    def validate_files_exist(self, plugin_dir: Path) -> list[str]:
        """Check that all referenced files exist under plugin_dir.

        Returns:
            List of missing file paths (relative strings).
            Empty list if all files are present.
        """
        missing: list[str] = []
        for paths_list in (self.skills, self.agents, self.hooks):
            for rel_path in paths_list:
                if not (plugin_dir / rel_path).exists():
                    missing.append(rel_path)
        return missing

    @classmethod
    def from_json(cls, path: Path) -> PluginManifest:
        """Load a PluginManifest from a plugin.json file."""
        import json  # noqa: PLC0415

        with open(path) as fh:
            data = json.load(fh)
        return cls.model_validate(data)

    def to_json(self, path: Path) -> None:
        """Write this manifest to a plugin.json file."""
        import json  # noqa: PLC0415

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.model_dump(exclude_none=True), fh, indent=2)
            fh.write("\n")
