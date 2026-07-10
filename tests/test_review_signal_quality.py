"""Tests for Plan 236: pre-review signal quality and finding-graph hygiene.

Covers the shared source-file classifier, status/date normalization, the
non-code exclusions in HISTORY / TEST_COVERAGE, the LEARNING cap+rank, and the
begin_plan finding persistence filter + dedup.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# filters.is_source_code_file
# ---------------------------------------------------------------------------


def test_is_source_code_file_by_language():
    from agentscaffold.review.filters import is_source_code_file

    assert is_source_code_file("a/b.py", "python")
    assert is_source_code_file("a/b.ts", "typescript")
    assert not is_source_code_file("docs/x.md", "markdown")
    assert not is_source_code_file("docs/x.md", "")


def test_is_source_code_file_extension_fallback():
    from agentscaffold.review.filters import is_source_code_file

    # No language recorded -> fall back to extension.
    assert is_source_code_file("adapters/execution/base.py", "")
    assert is_source_code_file("pkg/mod.rs", None)
    assert not is_source_code_file("docs/ai/state/workflow_state.md", "")
    assert not is_source_code_file("README", "")


# ---------------------------------------------------------------------------
# filters.normalize_plan_status / recover_plan_date
# ---------------------------------------------------------------------------


def test_normalize_plan_status():
    from agentscaffold.review.filters import normalize_plan_status

    assert normalize_plan_status("COMPLETE") == "Complete"
    assert normalize_plan_status("Complete; 144-F control-plane done") == "Complete"
    assert normalize_plan_status("COMPLETE (2026-07-09)") == "Complete"
    assert normalize_plan_status("In Progress") == "In Progress"
    assert normalize_plan_status("Draft") == "Draft"
    assert normalize_plan_status("SUPERSEDED") == "Superseded"
    assert normalize_plan_status("Ready for Implementation") == "Ready"
    assert normalize_plan_status("") == "Unknown"
    assert normalize_plan_status("unknown") == "Unknown"
    assert normalize_plan_status("some weird status") == "Unknown"


def test_recover_plan_date():
    from agentscaffold.review.filters import recover_plan_date

    assert recover_plan_date("2026-02-24", None) == "2026-02-24"
    assert recover_plan_date("", "COMPLETE (2026-07-09)") == "2026-07-09"
    assert recover_plan_date("", "COMPLETE") == ""
    assert recover_plan_date("", None) == ""


# ---------------------------------------------------------------------------
# challenges._check_history non-code exclusion
# ---------------------------------------------------------------------------


def test_check_history_skips_non_code():
    from agentscaffold.review.challenges import _check_history

    out: list = []
    with patch("agentscaffold.review.challenges.get_plans_impacting_file") as gp:
        _check_history(
            MagicMock(),
            "docs/ai/state/workflow_state.md",
            999,
            out,
            language="markdown",
        )
        # Non-code file: must not even query the graph, and no challenge.
        gp.assert_not_called()
    assert out == []


def test_check_history_fires_for_code():
    from agentscaffold.review.challenges import _check_history

    out: list = []
    prior = [{"p.number": n} for n in (1, 2, 3, 4)]
    with patch("agentscaffold.review.challenges.get_plans_impacting_file", return_value=prior):
        _check_history(MagicMock(), "libs/foo.py", 999, out, language="python")
    assert len(out) == 1
    assert out[0].category == "HISTORY"


# ---------------------------------------------------------------------------
# challenges._check_learnings cap + rank
# ---------------------------------------------------------------------------


def test_check_learnings_capped_and_ranked():
    from agentscaffold.review.challenges import _check_learnings

    learnings = [
        {
            "lr.learningId": f"L{i}",
            "lr.planNumber": i,
            "lr.description": f"desc {i}",
            "lr.status": "Incorporated 2026-07-08" if i < 6 else "Pending",
        }
        for i in range(8)
    ]
    out: list = []
    with patch("agentscaffold.review.challenges.get_learnings_for_file", return_value=learnings):
        _check_learnings(MagicMock(), "data_contracts/pipeline.py", out, max_per_file=5)

    assert len(out) == 5
    # Pending (unincorporated) learnings rank first.
    assert out[0].evidence["learning_id"] in {"L6", "L7"}
    # Truncation is disclosed on the first item.
    assert "of 8 learnings" in out[0].text
    assert out[0].evidence["total_linked_learnings"] == 8
    assert out[0].evidence["shown"] == 5


# ---------------------------------------------------------------------------
# gaps._test_coverage_gaps non-code exclusion
# ---------------------------------------------------------------------------


def test_test_coverage_gaps_skips_non_code():
    from agentscaffold.review.gaps import _test_coverage_gaps

    impacted = [
        {"f.path": "libs/tca/estimator.py", "f.language": "python"},
        {"f.path": "docs/runbook/tca.md", "f.language": "markdown"},
        {"f.path": "docs/ai/contracts/README.md", "f.language": "markdown"},
    ]
    out: list = []
    # No test files exist for anything -> only the code file should be flagged.
    with patch("agentscaffold.review.gaps.ql", return_value=[]):
        _test_coverage_gaps(MagicMock(), impacted, out)

    assert len(out) == 1
    missing = out[0].evidence["missing_test_files"]
    assert "libs/tca/estimator.py" in missing
    assert not any(p.endswith(".md") for p in missing)


# ---------------------------------------------------------------------------
# server._select_findings_to_persist
# ---------------------------------------------------------------------------


def _cand(category: str, finding: str, severity: str) -> dict:
    return {"category": category, "finding": finding, "severity": severity, "file_paths": []}


def test_select_findings_only_high_severity():
    from agentscaffold.mcp.server import _select_findings_to_persist

    candidates = [
        _cand("CONSUMER", "consumer issue", "high"),
        _cand("LEARNING", "learning noise", "medium"),
        _cand("HISTORY", "history note", "medium"),
        _cand("TEST_COVERAGE", "no tests", "high"),
    ]
    selected = _select_findings_to_persist(candidates, [])
    cats = {f["category"] for f in selected}
    assert cats == {"CONSUMER", "TEST_COVERAGE"}


def test_select_findings_dedups_against_existing():
    from agentscaffold.mcp.server import _select_findings_to_persist

    candidates = [_cand("CONSUMER", "Same finding text.", "high")]
    existing = [{"rf.category": "consumer", "rf.finding": "same   finding   text."}]
    # Case- and whitespace-insensitive match -> dropped.
    assert _select_findings_to_persist(candidates, existing) == []


def test_select_findings_dedups_within_batch():
    from agentscaffold.mcp.server import _select_findings_to_persist

    candidates = [
        _cand("CONSUMER", "dup", "high"),
        _cand("CONSUMER", "dup", "high"),
    ]
    assert len(_select_findings_to_persist(candidates, [])) == 1
