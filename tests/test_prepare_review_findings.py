"""Tests for Step C.3: open_findings and reviewer_hints in scaffold_prepare_review."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    fid: str,
    severity: str = "medium",
    plan_number: int = 10,
    review_type: str = "quant_architect",
    category: str = "correctness",
    finding: str = "some finding",
) -> dict:
    return {
        "rf.id": fid,
        "rf.severity": severity,
        "rf.planNumber": plan_number,
        "rf.reviewType": review_type,
        "rf.category": category,
        "rf.finding": finding,
    }


def _make_store(plan_findings: list[dict], file_findings: dict[str, list[dict]]) -> MagicMock:
    """Return a mock store; get_open_findings dispatches based on kwargs."""
    from agentscaffold.mcp.server import _sev_key  # noqa: PLC0415

    store = MagicMock()
    store.is_duckpgq = True

    def _fake_get_open_findings(s, *, plan_number=None, file_path=None, limit=20, project=None):
        if file_path is not None:
            return file_findings.get(file_path, [])
        result = plan_findings[:]
        if plan_number is not None:
            result = [r for r in result if r.get("rf.planNumber") == plan_number]
        return sorted(result, key=_sev_key)[:limit]

    return store, _fake_get_open_findings


# ---------------------------------------------------------------------------
# _file_matches_domain_pattern
# ---------------------------------------------------------------------------


def test_pattern_slash_starstar():
    from agentscaffold.mcp.server import _file_matches_domain_pattern

    assert _file_matches_domain_pattern("libs/risk/foo.py", "libs/risk/**")
    assert _file_matches_domain_pattern("libs/risk", "libs/risk/**")
    assert not _file_matches_domain_pattern("libs/other/foo.py", "libs/risk/**")


def test_pattern_fnmatch_simple():
    from agentscaffold.mcp.server import _file_matches_domain_pattern

    assert _file_matches_domain_pattern("execution/broker.py", "execution/**")
    assert not _file_matches_domain_pattern("other/foo.py", "execution/**")


def test_pattern_fnmatch_exact():
    from agentscaffold.mcp.server import _file_matches_domain_pattern

    assert _file_matches_domain_pattern("api/v1/handler.py", "api/**")


# ---------------------------------------------------------------------------
# _build_reviewer_hints
# ---------------------------------------------------------------------------


def test_build_hints_empty_paths(tmp_path: Path):
    from agentscaffold.mcp.server import _build_reviewer_hints

    hints = _build_reviewer_hints(tmp_path, [])
    assert isinstance(hints, list)
    # No .cursor/rules/agentscaffold.md exists in tmp_path → empty
    assert hints == []


def test_build_hints_includes_agentscaffold_rule(tmp_path: Path):
    from agentscaffold.mcp.server import _build_reviewer_hints

    rules_dir = tmp_path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "agentscaffold.md").write_text("# scaffold rules")

    hints = _build_reviewer_hints(tmp_path, [])
    assert ".cursor/rules/agentscaffold.md" in hints


def test_build_hints_domain_match_adds_standards(tmp_path: Path):
    from agentscaffold.mcp.server import _build_reviewer_hints

    # Create a fake standard file
    std_dir = tmp_path / "docs" / "ai" / "standards"
    std_dir.mkdir(parents=True)
    (std_dir / "idempotency.md").write_text("# idempotency")

    packs = ["data_engineering"]
    manifests = {
        "data_engineering": {
            "file_patterns": ["pipelines/**"],
            "standards": ["idempotency"],
        }
    }

    with (
        patch(
            "agentscaffold.domain_packs.loader._get_available_packs",
            return_value=packs,
        ),
        patch(
            "agentscaffold.domain_packs.loader._load_manifest",
            side_effect=lambda p: manifests[p],
        ),
    ):
        hints = _build_reviewer_hints(tmp_path, ["pipelines/ingest.py"])

    assert "docs/ai/standards/idempotency.md" in hints


def test_build_hints_no_match_skips_standards(tmp_path: Path):
    from agentscaffold.mcp.server import _build_reviewer_hints

    std_dir = tmp_path / "docs" / "ai" / "standards"
    std_dir.mkdir(parents=True)
    (std_dir / "idempotency.md").write_text("# idempotency")

    packs = ["data_engineering"]
    manifests = {
        "data_engineering": {
            "file_patterns": ["pipelines/**"],
            "standards": ["idempotency"],
        }
    }

    with (
        patch(
            "agentscaffold.domain_packs.loader._get_available_packs",
            return_value=packs,
        ),
        patch(
            "agentscaffold.domain_packs.loader._load_manifest",
            side_effect=lambda p: manifests[p],
        ),
    ):
        # File is NOT under pipelines/
        hints = _build_reviewer_hints(tmp_path, ["api/handler.py"])

    assert "docs/ai/standards/idempotency.md" not in hints


def test_build_hints_standard_not_on_disk_excluded(tmp_path: Path):
    from agentscaffold.mcp.server import _build_reviewer_hints

    packs = ["data_engineering"]
    manifests = {
        "data_engineering": {
            "file_patterns": ["pipelines/**"],
            "standards": ["nonexistent_std"],
        }
    }

    with (
        patch(
            "agentscaffold.domain_packs.loader._get_available_packs",
            return_value=packs,
        ),
        patch(
            "agentscaffold.domain_packs.loader._load_manifest",
            side_effect=lambda p: manifests[p],
        ),
    ):
        hints = _build_reviewer_hints(tmp_path, ["pipelines/ingest.py"])

    # Standard file doesn't exist on disk → not included
    assert not any("nonexistent_std" in h for h in hints)


def test_build_hints_missing_manifest_skipped(tmp_path: Path):
    from agentscaffold.mcp.server import _build_reviewer_hints

    packs = ["bad_pack"]

    with (
        patch(
            "agentscaffold.domain_packs.loader._get_available_packs",
            return_value=packs,
        ),
        patch(
            "agentscaffold.domain_packs.loader._load_manifest",
            side_effect=FileNotFoundError("no manifest"),
        ),
    ):
        hints = _build_reviewer_hints(tmp_path, ["pipelines/ingest.py"])

    assert isinstance(hints, list)  # no crash


# ---------------------------------------------------------------------------
# _sev_key ordering
# ---------------------------------------------------------------------------


def test_sev_key_ordering():
    from agentscaffold.mcp.server import _sev_key

    findings = [
        _make_finding("f1", "low"),
        _make_finding("f2", "critical"),
        _make_finding("f3", "medium"),
        _make_finding("f4", "high"),
    ]
    sorted_f = sorted(findings, key=_sev_key)
    severities = [f["rf.severity"] for f in sorted_f]
    assert severities == ["critical", "high", "medium", "low"]


def test_sev_key_unknown_severity_last():
    from agentscaffold.mcp.server import _sev_key

    findings = [
        _make_finding("f1", "unknown_level"),
        _make_finding("f2", "critical"),
    ]
    sorted_f = sorted(findings, key=_sev_key)
    assert sorted_f[0]["rf.severity"] == "critical"
    assert sorted_f[1]["rf.severity"] == "unknown_level"


# ---------------------------------------------------------------------------
# _tool_prepare_review integration (mocked)
# ---------------------------------------------------------------------------


def _make_review_store_mocks(pn: int = 10) -> MagicMock:
    """Return a store mock suitable for _tool_prepare_review tests."""
    store = MagicMock()
    return store


def test_prepare_review_includes_open_findings_key(tmp_path: Path):
    """open_findings key must be present in the result."""
    from agentscaffold.mcp.server import _tool_prepare_review

    store = MagicMock()
    meta = {"session_id": "test"}

    plan_finding = _make_finding("rf::abc", severity="high", plan_number=10)

    with (
        patch(
            "agentscaffold.mcp.server._build_reviewer_hints",
            return_value=[],
        ),
        patch(
            "agentscaffold.graph.findings.get_open_findings",
            return_value=[plan_finding],
        ),
        patch(
            "agentscaffold.review.brief.generate_brief",
            return_value={"file_profiles": [], "summary": {}},
        ),
        patch(
            "agentscaffold.review.brief.format_brief_markdown",
            return_value="",
        ),
        patch(
            "agentscaffold.review.challenges.generate_challenges",
            return_value=[],
        ),
        patch(
            "agentscaffold.review.challenges.format_challenges_markdown",
            return_value="",
        ),
        patch("agentscaffold.review.gaps.generate_gaps", return_value=[]),
        patch(
            "agentscaffold.review.gaps.format_gaps_markdown",
            return_value="",
        ),
        patch(
            "agentscaffold.review.queries.get_adrs_for_plan",
            return_value=[],
        ),
        patch(
            "agentscaffold.review.queries.get_spikes_for_plan",
            return_value=[],
        ),
        patch(
            "agentscaffold.review.queries.get_studies_for_plan",
            return_value=[],
        ),
        patch(
            "agentscaffold.review.queries.get_plan_dependencies",
            return_value=[],
        ),
    ):
        result = _tool_prepare_review(store, {"plan_number": 10}, meta, tmp_path, None)

    assert "open_findings" in result
    assert "reviewer_hints" in result


def test_prepare_review_missing_plan_number(tmp_path: Path):
    from agentscaffold.mcp.server import _tool_prepare_review

    store = MagicMock()
    result = _tool_prepare_review(store, {}, {}, tmp_path, None)
    assert "error" in result


def test_prepare_review_deduplicates_findings(tmp_path: Path):
    """File-scoped findings already in plan findings must not be duplicated."""
    from agentscaffold.mcp.server import _tool_prepare_review

    store = MagicMock()
    shared_finding = _make_finding("rf::shared", severity="critical", plan_number=10)
    impacted_file = "libs/risk/foo.py"

    call_count = {"n": 0}

    def _fake_get_open(s, *, plan_number=None, file_path=None, limit=20, project=None):
        call_count["n"] += 1
        if file_path == impacted_file:
            # Return the same finding that was already in plan_findings
            return [shared_finding]
        return [shared_finding]

    with (
        patch(
            "agentscaffold.graph.findings.get_open_findings",
            side_effect=_fake_get_open,
        ),
        patch(
            "agentscaffold.mcp.server._build_reviewer_hints",
            return_value=[],
        ),
        patch(
            "agentscaffold.review.brief.generate_brief",
            return_value={
                "file_profiles": [{"path": impacted_file}],
                "summary": {},
            },
        ),
        patch("agentscaffold.review.brief.format_brief_markdown", return_value=""),
        patch("agentscaffold.review.challenges.generate_challenges", return_value=[]),
        patch(
            "agentscaffold.review.challenges.format_challenges_markdown",
            return_value="",
        ),
        patch("agentscaffold.review.gaps.generate_gaps", return_value=[]),
        patch("agentscaffold.review.gaps.format_gaps_markdown", return_value=""),
        patch("agentscaffold.review.queries.get_adrs_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_spikes_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_plan_dependencies", return_value=[]),
    ):
        result = _tool_prepare_review(store, {"plan_number": 10}, {}, tmp_path, None)

    # shared_finding appeared in both plan and file queries → must appear only once
    ids = [f["rf.id"] for f in result["open_findings"]]
    assert ids.count("rf::shared") == 1


def test_prepare_review_findings_sorted_by_severity(tmp_path: Path):
    from agentscaffold.mcp.server import _tool_prepare_review

    store = MagicMock()
    findings = [
        _make_finding("f1", "low", plan_number=10),
        _make_finding("f2", "critical", plan_number=10),
        _make_finding("f3", "medium", plan_number=10),
    ]

    def _fake_get_open(s, *, plan_number=None, file_path=None, limit=20, project=None):
        if file_path:
            return []
        return findings

    with (
        patch("agentscaffold.graph.findings.get_open_findings", side_effect=_fake_get_open),
        patch("agentscaffold.mcp.server._build_reviewer_hints", return_value=[]),
        patch(
            "agentscaffold.review.brief.generate_brief",
            return_value={"file_profiles": [], "summary": {}},
        ),
        patch("agentscaffold.review.brief.format_brief_markdown", return_value=""),
        patch("agentscaffold.review.challenges.generate_challenges", return_value=[]),
        patch(
            "agentscaffold.review.challenges.format_challenges_markdown",
            return_value="",
        ),
        patch("agentscaffold.review.gaps.generate_gaps", return_value=[]),
        patch("agentscaffold.review.gaps.format_gaps_markdown", return_value=""),
        patch("agentscaffold.review.queries.get_adrs_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_spikes_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_plan_dependencies", return_value=[]),
    ):
        result = _tool_prepare_review(store, {"plan_number": 10}, {}, tmp_path, None)

    severities = [f["rf.severity"] for f in result["open_findings"]]
    assert severities[0] == "critical"
    assert severities[-1] == "low"


def test_prepare_review_findings_capped_at_20(tmp_path: Path):
    from agentscaffold.mcp.server import _tool_prepare_review

    store = MagicMock()
    many_findings = [_make_finding(f"f{i}", "medium", plan_number=10) for i in range(30)]

    def _fake_get_open(s, *, plan_number=None, file_path=None, limit=20, project=None):
        if file_path:
            return []
        return many_findings

    with (
        patch("agentscaffold.graph.findings.get_open_findings", side_effect=_fake_get_open),
        patch("agentscaffold.mcp.server._build_reviewer_hints", return_value=[]),
        patch(
            "agentscaffold.review.brief.generate_brief",
            return_value={"file_profiles": [], "summary": {}},
        ),
        patch("agentscaffold.review.brief.format_brief_markdown", return_value=""),
        patch("agentscaffold.review.challenges.generate_challenges", return_value=[]),
        patch(
            "agentscaffold.review.challenges.format_challenges_markdown",
            return_value="",
        ),
        patch("agentscaffold.review.gaps.generate_gaps", return_value=[]),
        patch("agentscaffold.review.gaps.format_gaps_markdown", return_value=""),
        patch("agentscaffold.review.queries.get_adrs_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_spikes_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_studies_for_plan", return_value=[]),
        patch("agentscaffold.review.queries.get_plan_dependencies", return_value=[]),
    ):
        result = _tool_prepare_review(store, {"plan_number": 10}, {}, tmp_path, None)

    assert len(result["open_findings"]) <= 20
