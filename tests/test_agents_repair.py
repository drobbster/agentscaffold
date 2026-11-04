"""Plan 260: scaffold agents repair."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.agents.repair import ManualRepairConflictError, plan_repair, run_repair
from agentscaffold.rendering import render_managed_block


def test_repair_drops_identical_copies() -> None:
    text = "## Planning Rules\n\nSame body.\n\n" + render_managed_block(
        "## Planning Rules\n\nSame body.\n"
    )
    updated, report = plan_repair(text)
    assert report.dropped == ["## Planning Rules"]
    assert updated.count("## Planning Rules") == 1
    assert "Same body." in updated


def test_repair_refuses_divergent_copies() -> None:
    text = "## Planning Rules\n\nHuman edit.\n\n" + render_managed_block(
        "## Planning Rules\n\nGenerated edit.\n"
    )
    with pytest.raises(ManualRepairConflictError, match="Planning Rules"):
        plan_repair(text)


def test_repair_idempotent_on_clean_file() -> None:
    text = "## Planning Rules\n\nOnce.\n\n## Plan Lifecycle\n\nOnce more.\n"
    updated, report = plan_repair(text)
    assert report.dropped == []
    assert updated.count("## Planning Rules") == 1


def test_repair_dry_run_does_not_write(tmp_path: Path) -> None:
    dest = tmp_path / "AGENTS.md"
    original = "## Planning Rules\n\nSame.\n\n## Planning Rules\n\nSame.\n"
    dest.write_text(original)
    report = run_repair(dest, apply=False)
    assert report.dropped == ["## Planning Rules"]
    assert dest.read_text() == original
    run_repair(dest, apply=True)
    assert dest.read_text().count("## Planning Rules") == 1


# ---------------------------------------------------------------------------
# Plan 279: --prefer-managed recovers pre-0.12 unmarked routing copies
# ---------------------------------------------------------------------------

_LEGACY = "## Planning Rules\n\nOur manual.\n\n## Session Working Rhythm\n\nOld routing line.\n\n"


def test_prefer_managed_drops_a_differing_unmarked_copy() -> None:
    text = _LEGACY + render_managed_block("## Session Working Rhythm\n\nNew routing line.\n")
    updated, report = plan_repair(text, prefer_managed=True)
    assert report.dropped == ["## Session Working Rhythm"]
    assert updated.count("## Session Working Rhythm") == 1
    assert "New routing line." in updated
    assert "Old routing line." not in updated


def test_prefer_managed_never_drops_a_heading_absent_from_the_block() -> None:
    text = _LEGACY + render_managed_block("## Session Working Rhythm\n\nNew routing line.\n")
    updated, _report = plan_repair(text, prefer_managed=True)
    assert "## Planning Rules\n\nOur manual." in updated


def test_prefer_managed_keeps_and_reports_a_heading_the_governance_mapping_uses() -> None:
    text = _LEGACY + render_managed_block("## Session Working Rhythm\n\nNew routing line.\n")
    updated, report = plan_repair(
        text, prefer_managed=True, protected_headings={"session working rhythm"}
    )
    assert report.dropped == []
    assert report.protected == ["## Session Working Rhythm"]
    assert "Old routing line." in updated


def test_prefer_managed_on_a_markerless_file_adds_the_block() -> None:
    updated, report = plan_repair(
        _LEGACY,
        prefer_managed=True,
        managed_body="## Session Working Rhythm\n\nNew routing line.\n",
    )
    assert report.dropped == ["## Session Working Rhythm"]
    assert "BEGIN AGENTSCAFFOLD MANAGED SECTION" in updated
    assert "New routing line." in updated
    assert "Old routing line." not in updated
    assert "## Planning Rules\n\nOur manual." in updated


def test_prefer_managed_without_a_block_or_body_refuses() -> None:
    with pytest.raises(ManualRepairConflictError, match="managed block"):
        plan_repair(_LEGACY, prefer_managed=True)


def test_prefer_managed_apply_leaves_a_bak(tmp_path: Path) -> None:
    dest = tmp_path / "AGENTS.md"
    original = _LEGACY + render_managed_block("## Session Working Rhythm\n\nNew routing line.\n")
    dest.write_text(original)
    run_repair(dest, apply=True, prefer_managed=True)
    assert (tmp_path / "AGENTS.md.bak").read_text() == original
    assert "Old routing line." not in dest.read_text()


def test_governance_mapping_headings_are_protected() -> None:
    from agentscaffold.agents.governance_manual import governance_protected_headings
    from agentscaffold.config import ScaffoldConfig

    config = ScaffoldConfig(
        agents={"governance": {"orient": ["Session Working Rhythm (Mandatory)"]}}
    )
    protected = governance_protected_headings(config)
    assert "session working rhythm" in protected
    assert "plan lifecycle" in protected


def test_cli_prefer_managed_recovers_a_legacy_manual_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The field report: unmarked routing that differs by a line from the generator."""
    from typer.testing import CliRunner

    from agentscaffold.agents.generate import _render_project_agents_md
    from agentscaffold.cli import app
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.rendering import get_default_context

    project = tmp_path / "solo"
    project.mkdir()
    (project / "scaffold.yaml").write_text("framework:\n  project_name: solo\n")
    config = ScaffoldConfig()
    routing = _render_project_agents_md(config, project, get_default_context(config))
    legacy = "## Planning Rules\n\nOur manual.\n\n" + routing + "\nA line edited by hand.\n"
    (project / "AGENTS.md").write_text(legacy)
    monkeypatch.chdir(project)

    result = CliRunner().invoke(app, ["agents", "repair", "--prefer-managed", "--apply"])

    assert result.exit_code == 0, result.output
    repaired = (project / "AGENTS.md").read_text()
    assert repaired.count("BEGIN AGENTSCAFFOLD MANAGED SECTION") == 1
    assert "A line edited by hand." not in repaired
    assert "## Planning Rules\n\nOur manual." in repaired
    assert (project / "AGENTS.md.bak").read_text() == legacy
