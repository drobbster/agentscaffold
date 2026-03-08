"""Parser for conversation/tool-call replay traces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ReplayTurn:
    """Single replay turn with normalized fields."""

    session_id: str
    turn_id: int
    user_text: str
    tool_calls: list[str]
    fallback_reason: str | None = None
    baseline_ok: bool | None = None
    mcp_ok: bool | None = None


def _as_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def parse_replay_jsonl(path: Path) -> tuple[list[ReplayTurn], list[str]]:
    """Parse replay jsonl file into turns + non-fatal validation warnings."""
    records: list[ReplayTurn] = []
    warnings: list[str] = []

    if not path.exists():
        return records, [f"Replay file not found: {path}"]

    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            warnings.append(f"Line {line_no}: invalid JSON ({exc})")
            continue

        if not isinstance(data, dict):
            warnings.append(f"Line {line_no}: expected object")
            continue

        session_id = data.get("session_id")
        turn_id = data.get("turn_id")
        user_text = data.get("user_text")
        tool_calls = data.get("tool_calls", [])
        fallback_reason = data.get("fallback_reason")

        missing = []
        if not isinstance(session_id, str) or not session_id.strip():
            missing.append("session_id")
        if not isinstance(turn_id, int):
            missing.append("turn_id")
        if not isinstance(user_text, str) or not user_text.strip():
            missing.append("user_text")
        if not isinstance(tool_calls, list) or any(not isinstance(t, str) for t in tool_calls):
            missing.append("tool_calls[list[str]]")
        if missing:
            warnings.append(f"Line {line_no}: invalid fields {missing}")
            continue

        quality = data.get("quality", {})
        baseline_ok: bool | None = None
        mcp_ok: bool | None = None
        if isinstance(quality, dict):
            baseline_ok = _as_bool_or_none(quality.get("baseline_ok"))
            mcp_ok = _as_bool_or_none(quality.get("mcp_ok"))

        records.append(
            ReplayTurn(
                session_id=session_id,
                turn_id=turn_id,
                user_text=user_text,
                tool_calls=tool_calls,
                fallback_reason=fallback_reason if isinstance(fallback_reason, str) else None,
                baseline_ok=baseline_ok,
                mcp_ok=mcp_ok,
            )
        )

    return records, warnings
