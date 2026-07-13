"""Plan 245: overlap signal hygiene for staleness / compare / prior experiments."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agentscaffold.review.filters import (
    DEFAULT_OVERLAP_NOISE_PATHS,
    is_overlap_noise_path,
    meaningful_plan_file_overlap,
    rank_lead_overlap,
    resolve_overlap_noise_paths,
)


def test_default_noise_paths_include_governance_hubs():
    assert "docs/ai/contracts/README.md" in DEFAULT_OVERLAP_NOISE_PATHS
    assert "docs/ai/state/workflow_state.md" in DEFAULT_OVERLAP_NOISE_PATHS


def test_resolve_overlap_noise_paths_none_uses_defaults():
    assert resolve_overlap_noise_paths(None) == DEFAULT_OVERLAP_NOISE_PATHS


def test_resolve_overlap_noise_paths_empty_disables():
    assert resolve_overlap_noise_paths([]) == frozenset()


def test_is_overlap_noise_path_suffix_match():
    assert is_overlap_noise_path("docs/ai/state/workflow_state.md")
    assert is_overlap_noise_path("workspace/proj/docs/ai/contracts/README.md")
    assert not is_overlap_noise_path("configs/sentiment_pipeline.yaml")


def test_meaningful_overlap_splits_noise_and_code():
    a = {
        "docs/ai/contracts/README.md",
        "docs/ai/state/workflow_state.md",
        "configs/sentiment_pipeline.yaml",
    }
    b = {
        "docs/ai/contracts/README.md",
        "docs/ai/state/workflow_state.md",
        "configs/sentiment_pipeline.yaml",
        "libs/other.py",
    }
    meaningful, noise = meaningful_plan_file_overlap(a, b)
    assert meaningful == ["configs/sentiment_pipeline.yaml"]
    assert noise == [
        "docs/ai/contracts/README.md",
        "docs/ai/state/workflow_state.md",
    ]


def test_staleness_governance_only_overlap_not_stale():
    from agentscaffold.mcp.server import _tool_staleness_check

    store = MagicMock()
    store.get_stats.return_value = {"files": 10, "plans": 2}

    def _impacted(_s, num, **_k):
        return [
            {"f.path": "docs/ai/contracts/README.md"},
            {"f.path": "docs/ai/state/workflow_state.md"},
        ]

    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.title": "New", "p.status": "Draft", "p.lastUpdated": "2026-07-12"},
        ),
        patch("agentscaffold.review.queries.get_plan_impacted_files", side_effect=_impacted),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[
                {"p.number": 4, "p.title": "Prior", "p.status": "COMPLETE (2026-07-09)"},
            ],
        ),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
    ):
        result = _tool_staleness_check(store, {"plan_number": 5}, {})

    assert result["is_stale"] is False
    assert result["overlapping_completed_plans"] == []
    assert result["overlap_noise_filtered_count"] == 2


def test_staleness_mixed_overlap_still_stale():
    from agentscaffold.mcp.server import _tool_staleness_check

    store = MagicMock()
    store.get_stats.return_value = {"files": 10, "plans": 2}

    def _impacted(_s, num, **_k):
        return [
            {"f.path": "docs/ai/contracts/README.md"},
            {"f.path": "configs/sentiment_pipeline.yaml"},
        ]

    with (
        patch(
            "agentscaffold.review.queries.get_plan_by_number",
            return_value={"p.title": "New", "p.status": "Draft", "p.lastUpdated": "2026-07-12"},
        ),
        patch("agentscaffold.review.queries.get_plan_impacted_files", side_effect=_impacted),
        patch(
            "agentscaffold.review.queries.get_all_plans",
            return_value=[
                {"p.number": 4, "p.title": "Prior", "p.status": "COMPLETE (2026-07-09)"},
            ],
        ),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
    ):
        result = _tool_staleness_check(store, {"plan_number": 5}, {})

    assert result["is_stale"] is True
    assert len(result["overlapping_completed_plans"]) == 1
    assert result["overlapping_completed_plans"][0]["shared_files"] == [
        "configs/sentiment_pipeline.yaml"
    ]
    assert (
        "docs/ai/contracts/README.md"
        in result["overlapping_completed_plans"][0]["overlap_noise_filtered"]
    )


def test_compare_governance_only_is_low_conflict():
    from agentscaffold.mcp.server import _tool_compare_plans

    store = MagicMock()
    store.get_stats.return_value = {"files": 10, "plans": 2}

    def _by_num(_s, n, **_k):
        return {"p.title": f"Plan {n}", "p.status": "Draft"}

    def _impacted(_s, n, **_k):
        return [
            {"f.path": "docs/ai/contracts/README.md"},
            {"f.path": "docs/ai/state/workflow_state.md"},
            {"f.path": "docs/ai/backlog.md"},
            {"f.path": "docs/ai/architectural_design_changelog.md"},
        ]

    with (
        patch("agentscaffold.review.queries.get_plan_by_number", side_effect=_by_num),
        patch("agentscaffold.review.queries.get_plan_impacted_files", side_effect=_impacted),
    ):
        result = _tool_compare_plans(store, {"plan_a": 1, "plan_b": 2}, {})

    assert result["conflict_risk"] == "low"
    assert result["shared_files"] == []
    assert result["overlap_noise_filtered_count"] == 4
    assert "meaningful" in result["conflict_risk_basis"]


def test_compare_code_overlap_still_elevates_risk():
    from agentscaffold.mcp.server import _tool_compare_plans

    store = MagicMock()
    store.get_stats.return_value = {"files": 10, "plans": 2}

    def _by_num(_s, n, **_k):
        return {"p.title": f"Plan {n}", "p.status": "Draft"}

    def _impacted(_s, n, **_k):
        return [
            {"f.path": "docs/ai/contracts/README.md"},
            {"f.path": "a.py"},
            {"f.path": "b.py"},
            {"f.path": "c.py"},
            {"f.path": "d.py"},
        ]

    with (
        patch("agentscaffold.review.queries.get_plan_by_number", side_effect=_by_num),
        patch("agentscaffold.review.queries.get_plan_impacted_files", side_effect=_impacted),
    ):
        result = _tool_compare_plans(store, {"plan_a": 1, "plan_b": 2}, {})

    assert result["conflict_risk"] == "high"
    assert result["overlap_count"] == 4
    assert "docs/ai/contracts/README.md" not in result["shared_files"]
    assert result["overlap_noise_filtered_count"] == 1
    assert result["lead_shared_files"][0] in {"a.py", "b.py", "c.py", "d.py"}
    assert result["lead_overlap"] == result["lead_shared_files"][0]


def test_lead_overlap_ranks_code_before_soft_docs():
    paths = ["docs/ai/standards/testing.md", "src/foo.py", "AGENTS.md"]
    assert rank_lead_overlap(paths, limit=1) == ["src/foo.py"]


def test_prior_experiments_skips_noise_paths():
    from agentscaffold.mcp.server import _tool_prior_experiments

    store = MagicMock()

    def _studies_for_file(_s, fpath, **_k):
        return [{"s.studyId": f"stu-{fpath}", "s.title": fpath}]

    with (
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
        patch(
            "agentscaffold.review.queries.get_plan_impacted_files",
            return_value=[
                {"f.path": "docs/ai/state/workflow_state.md"},
                {"f.path": "configs/sentiment_pipeline.yaml"},
            ],
        ),
        patch(
            "agentscaffold.review.queries.get_studies_for_file",
            side_effect=_studies_for_file,
        ),
    ):
        result = _tool_prior_experiments(store, {"plan_number": 5}, {})

    assert result["overlap_noise_filtered_count"] == 1
    assert result["total_count"] == 1
    assert result["file_overlap_studies"][0]["studyId"] == "stu-configs/sentiment_pipeline.yaml"
