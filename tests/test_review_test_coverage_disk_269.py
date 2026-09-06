"""Plan 269: TEST_COVERAGE / test_delta see on-disk tests the graph omitted."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentscaffold.review.gaps import GapFinding, _test_coverage_gaps
from agentscaffold.review.verify import (
    VerificationItem,
    _check_plan_compliance,
    _check_test_delta,
)


def test_disk_test_file_suppresses_coverage_gap(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("def test_foo():\n    assert True\n")

    out: list[GapFinding] = []
    with (
        patch("agentscaffold.review.test_presence.ql", return_value=[]),
        patch("agentscaffold.review.test_presence.default_start", return_value=tmp_path),
    ):
        _test_coverage_gaps(
            MagicMock(),
            [{"f.path": "src/foo.py", "f.language": "python"}],
            out,
        )

    assert out == []


def test_missing_disk_and_graph_still_flags(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "tests").mkdir()

    out: list[GapFinding] = []
    with (
        patch("agentscaffold.review.test_presence.ql", return_value=[]),
        patch("agentscaffold.review.test_presence.default_start", return_value=tmp_path),
    ):
        _test_coverage_gaps(
            MagicMock(),
            [{"f.path": "src/foo.py", "f.language": "python"}],
            out,
        )

    assert len(out) == 1
    assert out[0].category == "TEST_COVERAGE"
    assert "src/foo.py" in out[0].evidence["missing_test_files"]


def test_test_delta_pass_from_disk(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("def test_foo():\n    assert True\n")

    out: list[VerificationItem] = []
    with (
        patch("agentscaffold.review.test_presence.ql", return_value=[]),
        patch("agentscaffold.review.test_presence.default_start", return_value=tmp_path),
    ):
        _check_test_delta(MagicMock(), {"src/foo.py"}, out)

    assert out[0].status == "pass"
    assert "all 1" in out[0].detail.lower()


def test_plan_compliance_zero_paths_is_skip_not_pass() -> None:
    out: list[VerificationItem] = []
    _check_plan_compliance(MagicMock(), 1, set(), out)
    assert out[0].check == "plan_compliance"
    assert out[0].status == "skip"
    assert "not a pass" in out[0].detail.lower()
