"""Plan 260: provenance stamp and three-way manual diff."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.agents.manual_diff import (
    ManualDiffConflictError,
    apply_manual_diff,
    build_manual_stamp,
    diff_manual,
    read_manual_stamp,
    stamp_manual,
)


def test_stamp_round_trip() -> None:
    raw = "## Source of Truth\n\npaths\n\n## Planning Rules\n\nrules\n"
    stamped = stamp_manual(raw)
    stamp = read_manual_stamp(stamped)
    assert stamp is not None
    assert stamp.sha256 == build_manual_stamp(raw).sha256
    assert "## Planning Rules" in stamp.sections


def test_upstream_only_is_offered() -> None:
    base = "## Alpha\n\nold\n\n## Beta\n\nkeep\n"
    stamped = stamp_manual(base)
    upstream = "## Alpha\n\nnew\n\n## Beta\n\nkeep\n"
    report = diff_manual(stamped, upstream)
    assert report.mode == "three_way"
    assert [item.heading for item in report.offered] == ["## Alpha"]
    assert report.conflicts == []


def test_local_only_is_left_alone() -> None:
    base = "## Alpha\n\nold\n"
    stamped = stamp_manual(base).replace("old", "mine", 1)
    report = diff_manual(stamped, base)
    assert report.offered == []
    assert report.conflicts == []


def test_both_changed_is_conflict() -> None:
    base = "## Alpha\n\nold\n"
    stamped = stamp_manual(base).replace("old", "mine", 1)
    report = diff_manual(stamped, "## Alpha\n\nupstream\n")
    assert [item.heading for item in report.conflicts] == ["## Alpha"]
    with pytest.raises(ManualDiffConflictError):
        apply_manual_diff(stamped, report)


def test_new_upstream_is_offered() -> None:
    base = "## Alpha\n\nold\n"
    stamped = stamp_manual(base)
    report = diff_manual(stamped, "## Alpha\n\nold\n\n## Beta\n\nnew\n")
    assert [item.heading for item in report.offered] == ["## Beta"]


def test_deleted_section_is_not_resurrected() -> None:
    base = "## Alpha\n\nold\n\n## Beta\n\ngone soon\n"
    stamped = stamp_manual(base)
    local = stamped.replace("## Beta\n\ngone soon\n", "")
    report = diff_manual(local, base)
    assert all(item.heading != "## Beta" for item in report.offered)


def test_missing_stamp_is_two_way() -> None:
    report = diff_manual("## Alpha\n\nmine\n", "## Alpha\n\nupstream\n")
    assert report.mode == "two_way"
    assert report.notes
    assert report.conflicts


def test_apply_updates_upstream_only(tmp_path: Path) -> None:
    base = "## Alpha\n\nold\n\n## Beta\n\nkeep\n"
    dest = tmp_path / "AGENTS.md"
    dest.write_text(stamp_manual(base))
    report = diff_manual(dest.read_text(), "## Alpha\n\nnew\n\n## Beta\n\nkeep\n")
    dest.write_text(apply_manual_diff(dest.read_text(), report))
    assert "## Alpha" in dest.read_text()
    assert "new" in dest.read_text()
    assert "keep" in dest.read_text()
