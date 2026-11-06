"""Optional runtime health snapshot (contract v2, Health snapshot).

The checker never calls a runtime. A project may write a JSON snapshot; this
module reads it as untrusted input (size-capped and schema-validated; anything
malformed is ignored with a reason) and applies the two contract rules:
an ``active`` scheduled job with no success in ``failing_days`` is failing, and
a component with no success in ``zombie_days`` is a deprecation candidate.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscaffold.inventory.schema import Inventory, parse_date


@dataclass
class ComponentHealth:
    last_success: dt.date | None
    last_attempt: dt.date | None
    state: str


@dataclass
class HealthSnapshot:
    """A validated snapshot, or the reason none could be used."""

    status: str  # ok, not_evaluated (no snapshot), stale, malformed
    generated_at: dt.date | None = None
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status == "ok"


def _generated_date(value: Any) -> dt.date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return parse_date(value)


def _optional_date(entry: dict[str, Any], key: str) -> tuple[dt.date | None, bool]:
    value = entry.get(key)
    if value is None:
        return None, True
    parsed = parse_date(value) if isinstance(value, str) else None
    return parsed, parsed is not None


def read_snapshot(path: Path, *, today: dt.date, max_bytes: int, stale_days: int) -> HealthSnapshot:
    """Read *path*. Never raises: an unusable snapshot carries its status and reason."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return HealthSnapshot("not_evaluated", reason=f"no snapshot at {path}")
    except OSError as exc:
        return HealthSnapshot("malformed", reason=f"cannot stat {path}: {exc}")
    if size > max_bytes:
        return HealthSnapshot(
            "malformed", reason=f"snapshot is {size} bytes; the cap is {max_bytes}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return HealthSnapshot("malformed", reason=f"snapshot is not JSON: {exc}")
    if not isinstance(raw, dict) or not isinstance(raw.get("components"), dict):
        return HealthSnapshot(
            "malformed", reason="snapshot needs generated_at and a components map"
        )
    generated = _generated_date(raw.get("generated_at"))
    if generated is None:
        return HealthSnapshot("malformed", reason="generated_at is missing or not ISO 8601")
    components: dict[str, ComponentHealth] = {}
    for cid, entry in raw["components"].items():
        if not isinstance(cid, str) or not isinstance(entry, dict):
            return HealthSnapshot("malformed", reason=f"component {cid!r} is not an object")
        success, ok_success = _optional_date(entry, "last_success")
        attempt, ok_attempt = _optional_date(entry, "last_attempt")
        state = entry.get("state", "")
        if not (ok_success and ok_attempt) or not isinstance(state, str):
            return HealthSnapshot("malformed", reason=f"component {cid!r} has a malformed field")
        components[cid] = ComponentHealth(success, attempt, state)
    if (today - generated).days > stale_days:
        return HealthSnapshot(
            "stale",
            generated_at=generated,
            reason=f"snapshot generated {generated} is older than {stale_days} days",
        )
    return HealthSnapshot("ok", generated_at=generated, components=components)


def _days_since(day: dt.date | None, ref: dt.date) -> int | None:
    return None if day is None else (ref - day).days


def failing(inventory: Inventory, snapshot: HealthSnapshot, *, days: int) -> list[dict[str, Any]]:
    """Active scheduled jobs with no success in *days* (relative to the snapshot)."""
    if not snapshot.usable or snapshot.generated_at is None:
        return []
    ref = snapshot.generated_at
    out: list[dict[str, Any]] = []
    for entry in inventory.components:
        if entry.kind != "scheduled_job" or entry.lifecycle != "active" or not entry.id:
            continue
        health = snapshot.components.get(entry.id)
        if health is None:
            continue
        age = _days_since(health.last_success, ref)
        if age is None or age > days:
            out.append(
                {
                    "component": entry.id,
                    "last_success": health.last_success.isoformat()
                    if health.last_success
                    else None,
                    "days_without_success": age,
                }
            )
    return out


def zombies(inventory: Inventory, snapshot: HealthSnapshot, *, days: int) -> list[dict[str, Any]]:
    """Components with no success in *days*: deprecation candidates (not deprecated yet)."""
    if not snapshot.usable or snapshot.generated_at is None:
        return []
    ref = snapshot.generated_at
    out: list[dict[str, Any]] = []
    for entry in inventory.components:
        if not entry.id or entry.lifecycle == "deprecated":
            continue
        health = snapshot.components.get(entry.id)
        if health is None:
            continue
        age = _days_since(health.last_success, ref)
        if age is None:
            since = entry.since_date
            if since is not None and (ref - since).days <= days:
                continue
        elif age <= days:
            continue
        out.append(
            {
                "component": entry.id,
                "lifecycle": entry.lifecycle,
                "last_success": health.last_success.isoformat() if health.last_success else None,
                "days_without_success": age,
            }
        )
    return out
