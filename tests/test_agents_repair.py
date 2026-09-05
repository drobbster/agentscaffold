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
