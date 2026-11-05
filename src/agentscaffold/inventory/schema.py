"""Inventory file models for contract v1.

The models accept what a human may have written and leave judgement to the
checks: a missing or malformed field is an INV-003 finding, not a load error.
Only a file that is not YAML, or whose top level is not the contract's shape,
fails to load.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION = 1

KINDS: tuple[str, ...] = (
    "scheduled_job",
    "manual_job",
    "service",
    "app",
    "config_family",
    "model",
    "workflow",
    "script",
)
LIFECYCLES: tuple[str, ...] = ("experimental", "active", "shadow", "paused", "deprecated")
#: Lifecycles whose declared paths a change or a plan must not touch silently.
DORMANT: frozenset[str] = frozenset({"paused", "deprecated"})


class InventoryError(Exception):
    """The inventory file cannot be read as contract v1."""


def _text(value: Any) -> str | None:
    """YAML reads ``080`` as a string but ``80`` and ``2026-01-01`` as other types."""
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()[:10]
    text = str(value).strip()
    return text or None


def parse_date(value: str | None) -> dt.date | None:
    """A ``YYYY-MM-DD`` date, or None when absent or malformed."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


class Component(BaseModel):
    """One ``components:`` entry. Unknown keys are kept and ignored."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    kind: str | None = None
    name: str | None = None
    source: str | None = None
    entrypoint: str | None = None
    reads: list[str] = Field(default_factory=list)
    layer: str | None = None
    owner_plan: str | None = None
    roadmap_stage: str | None = None
    lifecycle: str | None = None
    since: str | None = None
    reason: str | None = None
    review_by: str | None = None
    exit_criteria: str | None = None
    replaced_by: str | None = None

    @field_validator(
        "id",
        "kind",
        "name",
        "source",
        "entrypoint",
        "layer",
        "owner_plan",
        "roadmap_stage",
        "lifecycle",
        "since",
        "reason",
        "review_by",
        "exit_criteria",
        "replaced_by",
        mode="before",
    )
    @classmethod
    def _as_text(cls, value: Any) -> str | None:
        return _text(value)

    @field_validator("reads", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("reads must be a list of paths")
        return [t for t in (_text(v) for v in value) if t]

    @property
    def since_date(self) -> dt.date | None:
        return parse_date(self.since)

    @property
    def review_by_date(self) -> dt.date | None:
        return parse_date(self.review_by)

    def declared(self, field: str) -> bool:
        """True when the file names *field*, even as an explicit null."""
        return field in self.model_fields_set


class Inventory(BaseModel):
    """The whole inventory file."""

    model_config = ConfigDict(extra="allow")

    schema_version: int = SCHEMA_VERSION
    current_roadmap_stage: str | None = None
    last_architecture_review: str | None = None
    review_cadence_days: int = 30
    components: list[Component] = Field(default_factory=list)

    @field_validator("current_roadmap_stage", "last_architecture_review", mode="before")
    @classmethod
    def _as_text(cls, value: Any) -> str | None:
        return _text(value)

    @field_validator("components", mode="before")
    @classmethod
    def _as_components(cls, value: Any) -> Any:
        return [] if value is None else value

    @property
    def last_review_date(self) -> dt.date | None:
        return parse_date(self.last_architecture_review)

    def by_id(self) -> dict[str, Component]:
        return {c.id: c for c in self.components if c.id}


def parse_inventory(text: str, *, label: str = "inventory") -> Inventory:
    """Parse inventory YAML text. Raises InventoryError on a malformed file."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InventoryError(f"{label} is not valid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise InventoryError(f"{label} must be a mapping with a components list")
    version = raw.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise InventoryError(f"{label} has schema_version {version!r}; this tool reads 1")
    try:
        return Inventory.model_validate(raw)
    except ValidationError as exc:
        raise InventoryError(f"{label} does not match contract v1: {exc}") from exc


def load_inventory(path: Path) -> Inventory:
    """Read the inventory at *path*. Raises InventoryError when absent or malformed."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InventoryError(f"no inventory at {path}") from exc
    except OSError as exc:
        raise InventoryError(f"cannot read {path}: {exc}") from exc
    return parse_inventory(text, label=str(path))
