"""``scaffold agents generate-all`` installs shipped prompts a project lacks."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.agents.generate import SHIPPED_PROMPTS, install_missing_prompts
from agentscaffold.config import ScaffoldConfig


def test_missing_prompts_are_installed_and_existing_ones_kept(tmp_path: Path) -> None:
    prompts = tmp_path / "docs" / "ai" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "plan_critique.md").write_text("our own critique prompt\n")

    written = install_missing_prompts(ScaffoldConfig(), tmp_path)

    assert sorted(p.name for p in written) == sorted(
        name for name in SHIPPED_PROMPTS.values() if name != "plan_critique.md"
    )
    assert (prompts / "plan_critique.md").read_text() == "our own critique prompt\n"
    assert (prompts / "architecture_review.md").read_text().strip()
    assert install_missing_prompts(ScaffoldConfig(), tmp_path) == []


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    prompts = tmp_path / "docs" / "ai" / "prompts"
    prompts.mkdir(parents=True)
    written = install_missing_prompts(ScaffoldConfig(), tmp_path, dry_run=True)
    assert len(written) == len(SHIPPED_PROMPTS)
    assert list(prompts.iterdir()) == []


def test_a_project_without_a_prompts_directory_gets_none(tmp_path: Path) -> None:
    assert install_missing_prompts(ScaffoldConfig(), tmp_path) == []
    assert not (tmp_path / "docs").exists()
