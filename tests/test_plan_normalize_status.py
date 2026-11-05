"""``scaffold plan normalize-status`` and the shared status reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentscaffold.plan.normalize import collect, insert_status, propose, run_normalize_status
from agentscaffold.plan.status import plan_status, status_lines

LIST_PLAN = """# Plan 010: Done work

## 0. Metadata
- Plan: 010
- Approved: 2026-01-02 by someone

## 8. Execution Steps
- [x] Step 1
- [x] Step 2
"""

TABLE_PLAN = """# Plan 011: Half done

| Field | Value |
|-------|-------|
| Title | Half done |
| Created | 2026-02-01 |

## Execution Steps
- [x] Step 1
- [ ] Step 2
"""

UNSTARTED = """# Plan 012: Not started

## Metadata
- Plan: 012

## Execution Steps
- [ ] Step 1
"""

QUALIFIED = """# Plan 013

## Metadata
- Status: Review (awaiting approval)

- [ ] Step 1
"""

TWO_STATUS = """# Plan 014

## Metadata
- Status: Draft
- Status: Complete
"""

OUT_OF_VOCAB = """# Plan 015

## Metadata
- Status: Blocked on vendor

- [x] Step 1
"""

NO_METADATA = """# Plan 016

Some prose.

- [x] Step 1
"""


@pytest.fixture()
def plans(tmp_path: Path) -> Path:
    directory = tmp_path / "plans"
    directory.mkdir()
    for name, text in {
        "010-done.md": LIST_PLAN,
        "011-half.md": TABLE_PLAN,
        "012-unstarted.md": UNSTARTED,
        "013-qualified.md": QUALIFIED,
        "014-two.md": TWO_STATUS,
        "015-vocab.md": OUT_OF_VOCAB,
        "016-bare.md": NO_METADATA,
    }.items():
        (directory / name).write_text(text)
    return directory


def test_dry_run_mapping_and_ambiguous_list(plans: Path) -> None:
    by_plan = {p.plan: p for p in collect(plans)}
    assert "013-qualified.md" not in by_plan
    assert by_plan["010-done.md"].proposed == "Complete"
    assert by_plan["010-done.md"].reason == "all 2 steps checked"
    assert by_plan["011-half.md"].proposed == "In Progress"
    ambiguous = {name for name, p in by_plan.items() if p.ambiguous}
    assert ambiguous == {"012-unstarted.md", "014-two.md", "015-vocab.md", "016-bare.md"}
    assert by_plan["014-two.md"].current == "Draft / Complete"
    assert "no metadata section" in by_plan["016-bare.md"].reason
    # Dry run writes nothing.
    assert (plans / "010-done.md").read_text() == LIST_PLAN


def test_apply_writes_only_confident_lines(plans: Path) -> None:
    code = run_normalize_status(plans, write=True, output="json")
    assert code == 0
    done = (plans / "010-done.md").read_text()
    assert "## 0. Metadata\n- Status: Complete\n- Plan: 010\n" in done
    half = (plans / "011-half.md").read_text()
    assert "|-------|-------|\n| Status | In Progress |\n| Title | Half done |" in half
    assert (plans / "012-unstarted.md").read_text() == UNSTARTED
    assert (plans / "015-vocab.md").read_text() == OUT_OF_VOCAB
    # Idempotent: a second run proposes nothing for the written plans.
    names = {p.plan for p in collect(plans)}
    assert not names & {"010-done.md", "011-half.md"}


def test_json_output(plans: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_normalize_status(plans, plan="010", output="json")
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] is False
    assert [p["plan"] for p in data["proposals"]] == ["010-done.md"]
    assert data["ambiguous"] == []
    assert data["written"] == []


def test_missing_directory_exits_2(tmp_path: Path) -> None:
    assert run_normalize_status(tmp_path / "absent") == 2


def test_insert_after_a_bare_heading() -> None:
    text = "# P\n\n## Metadata\n\nProse only.\n"
    assert insert_status(text, "Draft") == "# P\n\n## Metadata\n- Status: Draft\n\nProse only.\n"


def test_propose_reports_nothing_for_a_valid_line() -> None:
    assert propose(QUALIFIED) is None


def test_status_reader_prefers_the_status_line() -> None:
    assert plan_status("## Metadata\n- Status: Complete\n\n- [ ] Step 1\n") == "Complete"
    assert plan_status(QUALIFIED) == "Review"
    assert plan_status(OUT_OF_VOCAB) == "Complete"  # unknown line: checkbox inference
    assert plan_status(UNSTARTED) == "Ready"
    assert status_lines("## STATUS: SUPERSEDED\n| Status | Draft |\n") == ["SUPERSEDED", "Draft"]


def test_cli_normalize_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agentscaffold.cli import app

    root = tmp_path / "project"
    plans = root / "docs" / "ai" / "plans"
    plans.mkdir(parents=True)
    (plans / "010-done.md").write_text(LIST_PLAN)
    (root / "scaffold.yaml").write_text("project:\n  name: p\n")
    monkeypatch.chdir(root)
    runner = CliRunner()
    result = runner.invoke(app, ["plan", "normalize-status"])
    assert result.exit_code == 0, result.output
    assert "Run again with --apply" in result.output
    assert runner.invoke(app, ["plan", "normalize-status", "-f", "xml"]).exit_code == 2
    result = runner.invoke(app, ["plan", "normalize-status", "--apply"])
    assert result.exit_code == 0, result.output
    assert "- Status: Complete" in (plans / "010-done.md").read_text()
