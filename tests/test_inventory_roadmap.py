"""Current roadmap stage from the roadmap's Stage / Gate met table (contract v2)."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.inventory import roadmap

TABLE = """\
# Roadmap

Intro text.

| Stage | Goal | Gate met |
|-------|------|----------|
| 0 Integrity | Clean data | **Yes, 2026-09-04** |
| 1 Baseline | First model | Yes |
| Stage 2 | Promotion | No |
| 3 Scale | More | |
"""


def test_stage_table_reads_ids_and_gates() -> None:
    assert roadmap.stage_table(TABLE) == [("0", True), ("1", True), ("2", False), ("3", False)]


def test_current_stage_is_the_one_after_the_highest_met_gate() -> None:
    assert roadmap.current_stage(TABLE) == "2"


def test_no_gate_met_means_the_first_stage() -> None:
    text = "| Stage | Gate met |\n|---|---|\n| A | No |\n| B | |\n"
    assert roadmap.current_stage(text) == "A"


def test_every_gate_met_stays_on_the_last_stage() -> None:
    text = "| Stage | Gate met |\n|---|---|\n| 1 | Yes |\n| 2 | yes |\n"
    assert roadmap.current_stage(text) == "2"


def test_tables_without_both_columns_are_ignored() -> None:
    assert roadmap.current_stage("| Stage | Owner |\n|---|---|\n| 1 | me |\n") is None
    assert roadmap.current_stage("no table here") is None


def test_find_roadmap_prefers_config_then_candidates(tmp_path: Path) -> None:
    assert roadmap.find_roadmap(tmp_path) is None
    (tmp_path / "docs" / "ai").mkdir(parents=True)
    (tmp_path / "docs/ai/strategy_roadmap.md").write_text("no table\n")
    (tmp_path / "docs/ai/roadmap.md").write_text(TABLE)
    assert roadmap.find_roadmap(tmp_path) == "docs/ai/roadmap.md"
    assert roadmap.find_roadmap(tmp_path, "custom.md") == "custom.md"
    assert roadmap.read_current_stage(tmp_path, "docs/ai/roadmap.md") == "2"
    assert roadmap.read_current_stage(tmp_path, "missing.md") is None
    assert roadmap.read_current_stage(tmp_path, None) is None
