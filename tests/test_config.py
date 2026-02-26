"""Tests for scaffold configuration schema and loading."""

from __future__ import annotations

from pathlib import Path

import yaml

from agentscaffold.config import (
    ScaffoldConfig,
    apply_rigor_preset,
    find_config,
    load_config,
)


def test_default_config() -> None:
    """ScaffoldConfig() produces valid defaults."""
    cfg = ScaffoldConfig()
    assert cfg.framework.project_name == "My Project"
    assert cfg.framework.version == "1.0"
    assert cfg.framework.architecture_layers == 6
    assert cfg.profile == "interactive"
    assert cfg.rigor == "standard"
    assert cfg.gates.draft_to_review.plan_lint is True
    assert cfg.semi_autonomous.enabled is False


def test_load_config_missing(tmp_path: Path) -> None:
    """load_config with no scaffold.yaml returns defaults."""
    cfg = load_config(tmp_path / "nonexistent.yaml")
    assert cfg.framework.project_name == "My Project"
    assert cfg.rigor == "standard"


def test_load_config_from_yaml(tmp_path: Path) -> None:
    """Write a scaffold.yaml, load it, verify values."""
    data = {
        "framework": {"project_name": "TestProj", "architecture_layers": 4},
        "rigor": "strict",
        "domains": ["trading"],
    }
    yaml_path = tmp_path / "scaffold.yaml"
    yaml_path.write_text(yaml.dump(data))

    cfg = load_config(yaml_path)
    assert cfg.framework.project_name == "TestProj"
    assert cfg.framework.architecture_layers == 4
    assert cfg.rigor == "strict"
    assert cfg.domains == ["trading"]


def test_rigor_minimal_preset() -> None:
    """apply_rigor_preset with 'minimal' disables many gates."""
    cfg = ScaffoldConfig(rigor="minimal")
    result = apply_rigor_preset(cfg)
    assert result.gates.review_to_ready.devils_advocate is False
    assert result.gates.review_to_ready.expansion_review is False
    assert result.gates.review_to_ready.spike_for_high_uncertainty is False
    assert result.gates.review_to_ready.interface_contracts is False
    assert result.gates.ready_to_in_progress.review_checklist is False
    assert result.gates.ready_to_in_progress.approval_gates is False
    assert result.gates.in_progress_to_complete.retrospective is False
    # Minimal still keeps basic quality gates on
    assert result.gates.in_progress_to_complete.tests_pass is True
    assert result.gates.in_progress_to_complete.validation_commands is True


def test_rigor_strict_preset() -> None:
    """apply_rigor_preset with 'strict' enables all gates."""
    cfg = ScaffoldConfig(rigor="strict")
    result = apply_rigor_preset(cfg)
    assert result.gates.review_to_ready.security_review is True
    assert result.gates.ready_to_in_progress.approval_gates is True
    assert result.gates.in_progress_to_complete.domain_implementation_review is True
    assert result.ci.plan_lint is True


def test_find_config_walks_up(tmp_path: Path) -> None:
    """find_config walks up from child dir to find scaffold.yaml in parent."""
    parent = tmp_path / "parent"
    child = parent / "child" / "grandchild"
    child.mkdir(parents=True)

    config_file = parent / "scaffold.yaml"
    config_file.write_text("framework:\n  project_name: WalkUp\n")

    found = find_config(start=child)
    assert found is not None
    assert found.resolve() == config_file.resolve()


def test_find_config_returns_none_when_absent(tmp_path: Path) -> None:
    """find_config returns None when no scaffold.yaml exists."""
    found = find_config(start=tmp_path)
    assert found is None


def test_semi_autonomous_config() -> None:
    """Verify semi_autonomous defaults."""
    cfg = ScaffoldConfig()
    sa = cfg.semi_autonomous
    assert sa.enabled is False
    assert sa.session_tracking is True
    assert sa.context_handoff is True
    assert sa.safety.read_only_paths == [
        "docs/ai/system_architecture.md",
        "scaffold.yaml",
        ".github/",
    ]
    assert sa.notifications.enabled is True
    assert sa.notifications.channel == "github_issue"
    assert sa.cautious_execution.max_fix_attempts == 2
    assert sa.cautious_execution.max_new_files_before_escalation == 5


def test_load_config_empty_yaml(tmp_path: Path) -> None:
    """load_config handles an empty YAML file gracefully."""
    yaml_path = tmp_path / "scaffold.yaml"
    yaml_path.write_text("")
    cfg = load_config(yaml_path)
    assert cfg.framework.project_name == "My Project"


def test_rigor_standard_preset_is_noop() -> None:
    """The 'standard' rigor preset does not change any defaults."""
    cfg = ScaffoldConfig(rigor="standard")
    result = apply_rigor_preset(cfg)
    assert result.gates.draft_to_review.plan_lint is True
    assert result.gates.review_to_ready.devils_advocate is True
    assert result.gates.in_progress_to_complete.domain_implementation_review is False
