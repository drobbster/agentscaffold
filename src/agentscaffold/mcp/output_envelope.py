"""C10 envelopes from live payloads (Plan 251 spike). Not hand-written schemas."""

from __future__ import annotations

from typing import Any

#: Keys Plan 273 keeps off ``detail=summary``. A summary envelope must not
#: require them; a full envelope may include them.
_DIARY_KEYS = frozenset(
    {"stats", "hot_files", "recent_plans", "recent_studies", "active_adrs"}
)


def top_level_keys(payload: dict[str, Any]) -> frozenset[str]:
    """Stable envelope keys: top-level minus volatile ``meta`` internals."""
    return frozenset(payload) - {"meta"}


def intersect_keys(samples: list[dict[str, Any]]) -> frozenset[str]:
    """Required keys = intersection of samples, diary keys never required."""
    if not samples:
        return frozenset()
    required = top_level_keys(samples[0])
    for sample in samples[1:]:
        required &= top_level_keys(sample)
    return required - _DIARY_KEYS


def validate_envelope(payload: Any, required: frozenset[str]) -> list[str]:
    """Return errors if *payload* is missing a required top-level key.

    ``meta`` must be a dict when present. Extra keys are allowed.
    """
    if not isinstance(payload, dict):
        return [f"payload is {type(payload).__name__}, not an object"]
    errors = [f"missing {key}" for key in sorted(required) if key not in payload]
    meta = payload.get("meta")
    if meta is not None and not isinstance(meta, dict):
        errors.append("meta is not an object")
    return errors
