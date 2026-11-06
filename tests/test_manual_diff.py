"""Provenance stamp and three-way manual diff."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.agents.manual_diff import (
    ManualDiffConflictError,
    apply_manual_diff,
    build_manual_stamp,
    diff_manual,
    insert_sections,
    parse_h2_sections,
    read_manual_stamp,
    stamp_manual,
    strip_manual_stamp,
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


UPSTREAM = (
    "## Alpha\n\nupstream alpha\n\n## Component Lifecycle\n\nlifecycle rules\n\n"
    "## Runbook Rules\n\nrunbook\n\n## Omega\n\nlast\n"
)
LOCAL = "# Our manual\n\n## Alpha\n\nmine, edited\n\n## Runbook Rules\n\nrunbook\n"


def _bodies(text: str) -> dict[str, str]:
    return {s.heading: s.body for s in parse_h2_sections(strip_manual_stamp(text)) if s.heading}


def test_insert_only_adds_the_named_section_before_runbook_rules() -> None:
    text, inserted = insert_sections(LOCAL, UPSTREAM, ["Component Lifecycle"])
    assert inserted == ["## Component Lifecycle"]
    body = strip_manual_stamp(text)
    assert (
        body.index("## Alpha")
        < body.index("## Component Lifecycle")
        < body.index("## Runbook Rules")
    )
    after = _bodies(text)
    for heading, value in _bodies(LOCAL).items():
        assert after[heading] == value
    assert "## Omega" not in text
    assert body.startswith("# Our manual\n")


def test_insert_only_stamps_template_hashes_so_local_edits_stay_local() -> None:
    text, _ = insert_sections(LOCAL, UPSTREAM, ["Component Lifecycle"])
    stamp = read_manual_stamp(text)
    assert stamp is not None
    assert set(stamp.sections) == {"## Alpha", "## Component Lifecycle", "## Runbook Rules"}
    report = diff_manual(text, UPSTREAM)
    assert report.mode == "three_way"
    assert [o.heading for o in report.offered] == ["## Omega"]
    assert report.conflicts == []
    changed = UPSTREAM.replace("upstream alpha", "newer alpha")
    assert [c.heading for c in diff_manual(text, changed).conflicts] == ["## Alpha"]


def test_insert_only_appends_without_an_anchor_and_keeps_the_managed_block() -> None:
    local = (
        "## Alpha\n\nmine\n\n<!-- BEGIN AGENTSCAFFOLD MANAGED SECTION -->\nmanaged\n"
        "<!-- END AGENTSCAFFOLD MANAGED SECTION -->\n"
    )
    text, inserted = insert_sections(local, "## Alpha\n\nx\n\n## Beta\n\nnew\n")
    assert inserted == ["## Beta"]
    assert text.index("## Beta") < text.index("BEGIN AGENTSCAFFOLD MANAGED SECTION")
    assert text.rstrip().endswith("<!-- END AGENTSCAFFOLD MANAGED SECTION -->")
    assert "## Alpha\n\nmine\n" in text


def test_insert_only_is_idempotent_and_respects_deleted_sections() -> None:
    once, _ = insert_sections(LOCAL, UPSTREAM)
    twice, inserted = insert_sections(once, UPSTREAM)
    assert inserted == [] and twice == once
    stamped = stamp_manual("## Alpha\n\na\n\n## Gone\n\ng\n").replace("## Gone\n\ng\n", "")
    _, inserted = insert_sections(stamped, "## Alpha\n\na\n\n## Gone\n\ng\n")
    assert inserted == []


def test_diff_manual_apply_on_an_unstamped_manual_inserts_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentscaffold.agents import manual_diff
    from agentscaffold.config import ScaffoldConfig

    monkeypatch.setattr(manual_diff, "render_governance_manual", lambda _config: UPSTREAM)
    dest = tmp_path / "AGENTS.md"
    dest.write_text(LOCAL)
    report = manual_diff.run_diff_manual(dest, ScaffoldConfig(), apply=True)
    assert report.mode == "two_way"
    assert [c.heading for c in report.conflicts] == ["## Alpha"]
    text = dest.read_text()
    assert read_manual_stamp(text) is not None
    assert "mine, edited" in text and "upstream alpha" not in text
    assert "## Component Lifecycle" in text and "## Omega" in text


def test_deliver_section_inserts_one_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentscaffold.agents import manual_diff
    from agentscaffold.config import ScaffoldConfig

    monkeypatch.setattr(manual_diff, "render_governance_manual", lambda _config: UPSTREAM)
    dest = tmp_path / "AGENTS.md"
    dest.write_text(LOCAL)
    assert manual_diff.deliver_section(dest, ScaffoldConfig(), "Component Lifecycle") == [
        "## Component Lifecycle"
    ]
    assert "## Omega" not in dest.read_text()
    assert manual_diff.deliver_section(dest, ScaffoldConfig(), "Component Lifecycle") == []
    assert manual_diff.deliver_section(tmp_path / "missing.md", ScaffoldConfig(), "X") == []


def test_apply_updates_upstream_only(tmp_path: Path) -> None:
    base = "## Alpha\n\nold\n\n## Beta\n\nkeep\n"
    dest = tmp_path / "AGENTS.md"
    dest.write_text(stamp_manual(base))
    report = diff_manual(dest.read_text(), "## Alpha\n\nnew\n\n## Beta\n\nkeep\n")
    dest.write_text(apply_manual_diff(dest.read_text(), report))
    assert "## Alpha" in dest.read_text()
    assert "new" in dest.read_text()
    assert "keep" in dest.read_text()
