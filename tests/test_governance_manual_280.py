"""Plan 280: the project's governance manual, parsed into addressable sections."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from agentscaffold.agents.governance_manual import load_manual, parse_manual
from agentscaffold.rendering import MANAGED_BLOCK_BEGIN, MANAGED_BLOCK_END

FIXTURE = Path(__file__).parent / "fixtures" / "governance" / "agents_md_governance_repo.md"


@pytest.fixture(scope="module")
def manual():
    return parse_manual(FIXTURE.read_text(encoding="utf-8"))


def _project_owned(text: str) -> str:
    begin = text.index(MANAGED_BLOCK_BEGIN)
    end = text.index(MANAGED_BLOCK_END) + len(MANAGED_BLOCK_END)
    return text[:begin] + text[end:]


def test_every_heading_in_the_project_region_is_addressable(manual) -> None:
    text = _project_owned(FIXTURE.read_text(encoding="utf-8"))
    in_fence = False
    expected = []
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        match = re.match(r"^(#{2,3}) (.+)$", line)
        if match and not in_fence:
            expected.append(match.group(2).strip())
    assert expected
    for heading in expected:
        assert manual.section(heading) is not None, heading


def test_gate_subsection_is_found_by_its_short_path(manual) -> None:
    text = manual.section("Plan Lifecycle / Ready -> In Progress")
    assert text is not None
    assert "Plan review checklist completed" in text
    assert manual.resolve("Plan Lifecycle / Ready -> In Progress") == (
        "Plan Lifecycle / Gate: Ready -> In Progress"
    )


def test_a_unique_subsection_resolves_without_its_parent(manual) -> None:
    assert manual.resolve("Gate: Review -> Ready") == "Plan Lifecycle / Gate: Review -> Ready"


def test_a_trailing_qualifier_is_ignored(manual) -> None:
    assert manual.resolve("Backlog Rules") == "Backlog Rules (Mandatory)"
    assert manual.resolve("review terminology") == "Review Terminology (Human-Readable)"


def test_a_top_section_includes_its_subsections(manual) -> None:
    text = manual.section("Plan Lifecycle")
    assert "### Gate: Draft -> Review" in text
    assert "### Gate: In Progress -> Complete" in text


def test_managed_block_headings_are_absent(manual) -> None:
    assert manual.section("Intent Map") is None
    assert manual.section("Call Compression Discipline") is None
    assert all("Intent Map" not in heading for heading in manual.headings)


def test_top_headings_are_the_h2_sections_in_order(manual) -> None:
    top = manual.top_headings
    assert top[0] == "Repository Relationship"
    assert "Hard Prohibitions" in top
    assert all(" / " not in heading for heading in top)
    assert len(top) < len(manual.headings)


def test_unknown_heading_suggests_the_closest(manual) -> None:
    assert manual.section("Backlog Rulez") is None
    suggestions = manual.suggestions("Backlog Rulez")
    assert len(suggestions) == 3
    assert suggestions[0] == "Backlog Rules (Mandatory)"


def test_headings_inside_code_fences_are_not_sections() -> None:
    manual = parse_manual("## Real\n\n```md\n## Not a heading\n```\n\n## Also real\nbody\n")
    assert manual.top_headings == ["Real", "Also real"]
    assert "## Not a heading" in manual.section("Real")


def test_text_after_the_managed_block_is_project_owned() -> None:
    text = f"## Before\na\n{MANAGED_BLOCK_BEGIN}\n## Managed\nm\n{MANAGED_BLOCK_END}\n## After\nb\n"
    manual = parse_manual(text)
    assert manual.top_headings == ["Before", "After"]


def test_hash_is_of_the_project_region_and_deterministic() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    first, second = parse_manual(text), parse_manual(text)
    assert first.sha256 == second.sha256
    owned = _project_owned(text)
    assert first.sha256 == hashlib.sha256(owned.encode("utf-8")).hexdigest()


def test_load_reads_from_the_project_root_and_caches(tmp_path) -> None:
    manual_file = tmp_path / "AGENTS.md"
    manual_file.write_text("## One\nfirst\n", encoding="utf-8")
    first = load_manual(tmp_path)
    assert first is not None and first.path == "AGENTS.md"
    assert load_manual(tmp_path) is first

    manual_file.write_text("## One\nsecond, longer\n", encoding="utf-8")
    stat = manual_file.stat()
    os.utime(manual_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    reloaded = load_manual(tmp_path)
    assert reloaded is not first
    assert "second" in reloaded.section("One")


def test_a_configured_manual_path(tmp_path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "MANUAL.md").write_text("## Rules\nr\n", encoding="utf-8")
    manual = load_manual(tmp_path, "docs/MANUAL.md")
    assert manual is not None and manual.path == "docs/MANUAL.md"


def test_no_manual_is_none(tmp_path) -> None:
    assert load_manual(tmp_path) is None
