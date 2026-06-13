"""Pydantic model for domain pack manifest.yaml — Step B.8."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DomainManifest(BaseModel):
    """Schema for a domain pack ``manifest.yaml`` file.

    Attributes:
        name: Machine-readable pack name (matches directory name).
        display_name: Human-readable name.
        description: One-line description of the domain pack.
        reviews: List of review prompt file stems in the pack's ``prompts/`` dir.
        standards: List of standard file stems in the pack's ``standards/`` dir.
        approval_gates: Dict of approval gate flags.
        file_patterns: Optional glob patterns identifying files relevant to this
            domain.  Used by Cursor rule generators to produce
            ``globs: [<patterns>]`` frontmatter instead of ``alwaysApply: true``.
            An empty list means ``alwaysApply: true`` (safe fallback).
    """

    name: str = ""
    display_name: str = ""
    description: str = ""
    reviews: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    approval_gates: dict[str, bool] = Field(default_factory=dict)
    file_patterns: list[str] = Field(default_factory=list)

    @property
    def has_file_patterns(self) -> bool:
        """Return True if the manifest specifies file patterns."""
        return bool(self.file_patterns)

    @property
    def cursor_always_apply(self) -> bool:
        """Return True if Cursor rules should use ``alwaysApply: true``."""
        return not self.has_file_patterns
