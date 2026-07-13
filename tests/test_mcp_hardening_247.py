"""Plan 247: MCP call-compression hardening regressions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.mcp.detail import apply_detail
from agentscaffold.mcp.diff_plan import diff_plan_vs_code
from agentscaffold.mcp.empty_fallback import attach_empty_fallback
from agentscaffold.mcp.plan_card import count_execution_checkboxes, next_unchecked_step
from agentscaffold.review.filters import (
    meaningful_plan_file_overlap,
    rank_lead_overlap,
)


def test_checkbox_counts_execution_steps_only() -> None:
    text = """# Plan

## Tests
- [ ] unit
- [ ] integration

## 6. Execution Steps
- [ ] Step A
- [x] Step B
- [ ] Step C

## Completion Checklist
- [ ] All done
"""
    unchecked, checked = count_execution_checkboxes(text)
    assert unchecked == 2
    assert checked == 1
    assert next_unchecked_step(text) == "Step A"


def test_rank_lead_overlap_prefers_code_over_docs() -> None:
    paths = [
        "docs/ai/standards/testing.md",
        "src/agentscaffold/mcp/server.py",
        "AGENTS.md",
    ]
    lead = rank_lead_overlap(paths, limit=2)
    assert lead[0] == "src/agentscaffold/mcp/server.py"
    assert "docs/ai/standards/testing.md" not in lead[:1]


def test_frequency_demotion_moves_ubiquitous_paths() -> None:
    a = {"src/common.py", "configs/rare.yaml"}
    b = {"src/common.py", "configs/rare.yaml"}
    meaningful, noise = meaningful_plan_file_overlap(
        a,
        b,
        path_frequency={"src/common.py": 12, "configs/rare.yaml": 1},
        frequency_demote_threshold=5,
    )
    assert meaningful == ["configs/rare.yaml"]
    assert "src/common.py" in noise


def test_attach_empty_fallback_inlines_why_and_grep(tmp_path: Path) -> None:
    (tmp_path / "hit.py").write_text("def normalize_feeds():\n    pass\n", encoding="utf-8")
    store = MagicMock()
    store.query.return_value = [{"cnt": 10, "parsed": 8}]
    # repo_coverage may call various queries; tolerate empty
    store.get_stats.return_value = {"files": 1}

    with patch(
        "agentscaffold.mcp.coverage.repo_coverage",
        return_value={"available": True, "parsed_pct": 80},
    ):
        payload = attach_empty_fallback(
            {"results": [], "count": 0},
            store=store,
            root=tmp_path,
            meta={},
            kind="search",
            query="normalize_feeds",
        )

    assert "why_empty" in payload
    assert payload["grep_fallback"]["count"] >= 1
    assert any("normalize_feeds" in (h.get("text") or "") for h in payload["grep_fallback"]["hits"])


def test_empty_search_response_includes_fallback(tmp_path: Path) -> None:
    from agentscaffold.mcp.server import _tool_search

    (tmp_path / "mod.py").write_text("def orphan_symbol_xyz():\n    return 1\n", encoding="utf-8")
    store = MagicMock()

    with (
        patch(
            "agentscaffold.graph.search.evaluate_retrieval",
            return_value={"retrieval_status": "ok", "retrieval_effective_mode": "keyword"},
        ),
        patch("agentscaffold.graph.search.hybrid_search", return_value=[]),
        patch(
            "agentscaffold.mcp.coverage.repo_coverage",
            return_value={"available": True, "parsed_pct": 90},
        ),
    ):
        result = _tool_search(
            store,
            {"query": "orphan_symbol_xyz", "mode": "keyword"},
            {},
            root=tmp_path,
        )

    assert result["count"] == 0
    assert "why_empty" in result
    assert result["grep_fallback"]["count"] >= 1


def test_empty_impact_includes_fallback(tmp_path: Path) -> None:
    from agentscaffold.mcp.server import _tool_impact

    (tmp_path / "lonely.py").write_text("# lonely\n", encoding="utf-8")
    store = MagicMock()

    with (
        patch("agentscaffold.mcp.server._transitive_importers", return_value=[]),
        patch("agentscaffold.mcp.server._config_consumers", return_value=[]),
        patch("agentscaffold.graph.query_compat.ql", return_value=[]),
        patch(
            "agentscaffold.mcp.coverage.repo_coverage",
            return_value={"available": True, "parsed_pct": 90},
        ),
    ):
        result = _tool_impact(
            store,
            {"file_or_symbol": "lonely.py"},
            {},
            root=tmp_path,
        )

    assert result["importer_count"] == 0
    assert "why_empty" in result
    assert "grep_fallback" in result


def test_orient_embeds_recommended_actions(tmp_path: Path) -> None:
    from agentscaffold.mcp.server import _tool_orient

    store = MagicMock()
    store.get_stats.return_value = {"files": 1, "plans": 1}
    store.query.return_value = [{"cnt": 0}]
    config = MagicMock()

    with (
        patch(
            "agentscaffold.mcp.coverage.repo_coverage",
            return_value={"available": True, "parsed_pct": 90},
        ),
        patch("agentscaffold.review.queries.get_all_plans", return_value=[]),
        patch("agentscaffold.review.queries.get_hot_files", return_value=[]),
        patch("agentscaffold.review.queries.get_all_studies", return_value=[]),
        patch("agentscaffold.review.queries.get_all_adrs", return_value=[]),
        patch("agentscaffold.review.queries.get_open_backlog_items", return_value=[]),
        patch(
            "agentscaffold.mcp.server._parse_workflow_state",
            return_value={"blockers": "None", "next_steps": "", "in_progress_plans": []},
        ),
        patch(
            "agentscaffold.mcp.next_action.next_actions",
            return_value={
                "focus_plan": 247,
                "actions": [
                    {
                        "priority": 1,
                        "action": "Continue Plan 247",
                        "tool": "scaffold_diff_plan_vs_code",
                        "arguments": {"plan_number": 247},
                    }
                ],
            },
        ),
    ):
        result = _tool_orient(store, {}, tmp_path, config, {})

    assert result["recommended_actions"]
    assert result["recommended_actions"][0]["tool"] == "scaffold_diff_plan_vs_code"
    assert result["next_action_focus"] == 247
    assert "plan_progress" in result


def test_diff_returns_next_unchecked_step(tmp_path: Path) -> None:
    plan = tmp_path / "docs" / "ai" / "plans" / "1-x.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "# Plan\n\n## File Impact Map\n\n| File | Change Type | Notes |\n"
        "|------|-------------|-------|\n"
        "| `src/exists.py` | MODIFY | add WidgetFactory |\n\n"
        "## Execution Steps\n- [ ] Wire WidgetFactory\n- [x] Scaffold file\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "exists.py").write_text(
        "class WidgetFactory:\n    pass\n",
        encoding="utf-8",
    )

    store = MagicMock()
    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={
                "p.number": 1,
                "p.title": "T",
                "p.status": "In Progress",
                "p.filePath": str(plan.relative_to(tmp_path)),
            },
        ),
        patch("agentscaffold.review.queries.get_plan_impacted_files", return_value=[]),
        patch("agentscaffold.mcp.diff_plan._file_in_graph", return_value=False),
        patch(
            "agentscaffold.mcp.plan_card._open_finding_summary",
            return_value={"count": 0, "ids": []},
        ),
    ):
        result = diff_plan_vs_code(store, 1, root=tmp_path)

    assert result["next_unchecked_step"] == "Wire WidgetFactory"
    assert result["symbol_spot_checks"]
    assert "WidgetFactory" in result["symbol_spot_checks"][0]["found_symbols"]


def test_detail_summary_keeps_recommended_actions() -> None:
    payload = apply_detail(
        {
            "recommended_actions": [
                {"action": "a"},
                {"action": "b"},
                {"action": "c"},
                {"action": "d"},
            ],
            "challenges": [
                {"severity": "low", "text": "l"},
                {"severity": "critical", "text": "c"},
            ],
        },
        "summary",
    )
    assert len(payload["recommended_actions"]) == 3
    assert payload["challenges"][0]["severity"] == "critical"
