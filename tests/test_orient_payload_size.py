"""Shared ceiling on the size of orient's default payload (Plan 276).

Several plans add to ``scaffold_orient`` and nothing else bounds its growth.
The ceiling is the 0.12.0 baseline plus one allowance row per plan that adds
to orient. A plan that needs more raises its own row, with a reason, in the
same change.

The payload is built through the dispatcher on an indexed single-project
repository. The project root is replaced by a fixed token and volatile meta
values are dropped, so the measure does not move with the temporary path or
with timing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")

#: Measured on the Plan 275/276 branch with AGENTSCAFFOLD_MCP_INSTRUCTIONS=off
#: before any Plan 276 code, which equals 0.12.0 for orient: Plan 275 adds only
#: meta keys, and the opt-out removes them.
BASELINE_0_12_0 = 2564

ALLOWANCES: dict[str, tuple[int, str]] = {
    "275": (260, "meta.session_open and meta.procedure_hint (hint at most 200 characters)"),
    "276": (
        300,
        "workflow_state.last_updated, stale and contradictions; plan_progress idle-next "
        "title and status (measured 248 on this fixture; session_warning is absent by default)",
    ),
    "280": (
        2830,
        "governance block: path, hash, ## headings, Hard Prohibitions and Approval Gates, "
        "bounded by agents.governance.orient_budget (2,800) plus its key; measured 2,630 "
        "with the shipped template's manual",
    ),
}

#: Freshness and retrieval states change a few characters between runs.
SLACK = 64

_VOLATILE_META = frozenset(
    {
        "graph_indexed_at",
        "oracle_latency_ms",
        "refresh_debounce_remaining_s",
        "embedding_debounce_remaining_s",
        "refresh_last_error",
        "embedding_last_error",
    }
)


def orient_measure(payload: dict[str, Any], root) -> int:
    meta = {k: v for k, v in (payload.get("meta") or {}).items() if k not in _VOLATILE_META}
    text = json.dumps({**payload, "meta": meta}, sort_keys=True, default=str)
    for prefix in {str(root.resolve()), str(root)}:
        text = text.replace(prefix, "<root>")
    return len(text)


def _default_orient(tmp_path):
    from agentscaffold.agents.manual_diff import render_governance_manual
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.mcp.server import _dispatch_tool
    from tests.fixtures.lone_project import STALE_WORKFLOW, build_lone_project

    repo = build_lone_project(
        tmp_path,
        workflow=STALE_WORKFLOW,
        draft_plan=True,
        manual=render_governance_manual(ScaffoldConfig()),
    )
    return _dispatch_tool("scaffold_orient", {"working_path": str(repo)}), repo


def test_default_orient_stays_under_the_shared_ceiling(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", raising=False)
    payload, repo = _default_orient(tmp_path)
    assert "error" not in payload
    ceiling = BASELINE_0_12_0 + sum(size for size, _ in ALLOWANCES.values()) + SLACK
    measured = orient_measure(payload, repo)
    assert measured <= ceiling, f"orient is {measured} characters; ceiling {ceiling}"


def test_baseline_still_describes_orient_without_plan_additions(tmp_path, monkeypatch) -> None:
    """With the opt-out on, orient carries no Plan 275 keys; the baseline must stay honest.

    Plan 280's ``governance`` block is removed before measuring: it has its own
    allowance and no opt-out variable.
    """
    monkeypatch.setenv("AGENTSCAFFOLD_MCP_INSTRUCTIONS", "off")
    payload, repo = _default_orient(tmp_path)
    payload.pop("governance", None)
    measured = orient_measure(payload, repo)
    allowance_276 = ALLOWANCES.get("276", (0, ""))[0]
    assert measured <= BASELINE_0_12_0 + allowance_276 + SLACK
