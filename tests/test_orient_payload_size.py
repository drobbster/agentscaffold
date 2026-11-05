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
    "282": (
        0,
        "session_brief.lifecycle_debt is omitted while the inventory is disabled (the default "
        "for a project without an inventory: block); the enabled block is bounded by "
        "test_lifecycle_debt_is_bounded_when_enabled",
    ),
}

#: Plan 282: five capped categories, a snapshot status and the review line, at the cap
#: with 60-character items. Measured 3,548 characters.
LIFECYCLE_DEBT_CEILING = 3700

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


def test_lifecycle_debt_is_bounded_when_enabled(tmp_path) -> None:
    """Every category past the cap, with long ids: the block stays under its ceiling."""
    import datetime as dt

    import yaml

    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.mcp.session_brief import lifecycle_debt

    def entry(n: int, lifecycle: str) -> dict[str, Any]:
        return {
            "id": f"prefect:a-long-component-name-for-the-bound-{lifecycle}-{n:03d}",
            "kind": "scheduled_job",
            "name": f"job-{n}",
            "source": "prefect.yaml",
            "entrypoint": f"flows/job_{n}.py:run",
            "owner_plan": "001",
            "lifecycle": lifecycle,
            "since": "2025-01-01",
            "reason": "r",
            "review_by": "2026-01-01",
        }

    components = [entry(n, "active") for n in range(30)]
    components += [entry(n, "deprecated") for n in range(30)]
    inventory = {"schema_version": 1, "review_cadence_days": 30, "components": components}
    (tmp_path / "docs" / "ai").mkdir(parents=True)
    (tmp_path / "docs" / "ai" / "system_inventory.yaml").write_text(yaml.safe_dump(inventory))
    snapshot = {
        "generated_at": "2026-11-04T00:00:00Z",
        "components": {c["id"]: {"last_success": "2025-02-01"} for c in components},
    }
    (tmp_path / "outputs" / "governance").mkdir(parents=True)
    (tmp_path / "outputs" / "governance" / "inventory_health.json").write_text(json.dumps(snapshot))

    class Store:
        def query(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
            return [
                {"number": n, "status": "Draft", "createdDate": "2025-01-01"} for n in range(30)
            ]

    config = ScaffoldConfig()
    config.inventory.enabled = True
    debt = lifecycle_debt(Store(), tmp_path, config, today=dt.date(2026, 11, 5))
    assert debt is not None
    full = {"expired_reviews", "overdue_deprecations", "failing", "zombies", "stale_drafts"}
    assert full <= set(debt)
    assert all(debt[k]["count"] == 30 for k in full)
    size = len(json.dumps({"lifecycle_debt": debt}, sort_keys=True))
    assert size <= LIFECYCLE_DEBT_CEILING, f"lifecycle_debt is {size} characters"
