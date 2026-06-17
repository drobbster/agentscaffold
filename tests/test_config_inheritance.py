"""Tests for config inheritance via ``extends:`` (Plan 224)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentscaffold.config import (
    CONFIG_FILENAME,
    ConfigError,
    load_config,
    resolve_config_chain,
)


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))
    return path


def test_no_extends_is_unchanged(tmp_path: Path) -> None:
    """A config without ``extends`` loads exactly as before."""
    cfg_path = _write(
        tmp_path / CONFIG_FILENAME,
        {"framework": {"project_name": "Solo"}, "rigor": "standard"},
    )
    config = load_config(cfg_path)

    assert config.framework.project_name == "Solo"
    assert config.extends is None


def test_extends_relative_path_base_precedence(tmp_path: Path) -> None:
    """Project values override the base; unset project values inherit the base."""
    _write(
        tmp_path / "shared" / CONFIG_FILENAME,
        {
            "rigor": "strict",
            "standards": {"core": ["errors", "logging"], "domain": ["trading"]},
            "domains": ["trading", "ml"],
        },
    )
    project = _write(
        tmp_path / "proj" / CONFIG_FILENAME,
        {
            "extends": "../shared/scaffold.yaml",
            "framework": {"project_name": "ProjA"},
            "domains": ["trading"],  # child replaces base list wholesale
        },
    )

    config = load_config(project)

    # Inherited from base (project did not set it):
    assert config.rigor == "strict"
    assert config.standards.domain == ["trading"]
    # Overridden by project:
    assert config.framework.project_name == "ProjA"
    assert config.domains == ["trading"]
    assert config.extends == "../shared/scaffold.yaml"


def test_extends_deep_merge_partial_override(tmp_path: Path) -> None:
    """Deep-merge: a nested field set by the child overrides only that field."""
    _write(
        tmp_path / "base" / CONFIG_FILENAME,
        {"framework": {"project_name": "Base", "architecture_layers": 6}},
    )
    project = _write(
        tmp_path / "p" / CONFIG_FILENAME,
        {"extends": "../base/scaffold.yaml", "framework": {"project_name": "Child"}},
    )

    config = load_config(project)

    assert config.framework.project_name == "Child"
    assert config.framework.architecture_layers == 6  # inherited


def test_extends_multi_level_chain(tmp_path: Path) -> None:
    """A -> B -> C chain merges with the nearest child winning."""
    _write(tmp_path / "c" / CONFIG_FILENAME, {"rigor": "minimal", "profile": "interactive"})
    _write(
        tmp_path / "b" / CONFIG_FILENAME,
        {"extends": "../c/scaffold.yaml", "rigor": "standard"},
    )
    project = _write(
        tmp_path / "a" / CONFIG_FILENAME,
        {"extends": "../b/scaffold.yaml", "profile": "semi_autonomous"},
    )

    config = load_config(project)

    assert config.rigor == "standard"  # from B (overrides C)
    assert config.profile == "semi_autonomous"  # from A (overrides C's default)


def test_extends_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``extends: home`` resolves against $AGENTSCAFFOLD_HOME."""
    home = tmp_path / "home"
    _write(home / CONFIG_FILENAME, {"rigor": "strict", "domains": ["org-standard"]})
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(home))

    project = _write(
        tmp_path / "proj" / CONFIG_FILENAME,
        {"extends": "home", "framework": {"project_name": "UsesHome"}},
    )

    config = load_config(project)

    assert config.rigor == "strict"
    assert config.domains == ["org-standard"]
    assert config.framework.project_name == "UsesHome"


def test_extends_home_absent_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``extends: home`` with no home config behaves as if there were no extends."""
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "nonexistent-home"))
    project = _write(
        tmp_path / "proj" / CONFIG_FILENAME,
        {"extends": "home", "rigor": "minimal"},
    )

    config = load_config(project)

    assert config.rigor == "minimal"  # project value preserved, no crash


def test_extends_missing_explicit_base_raises(tmp_path: Path) -> None:
    """An explicit (non-home) base that does not exist is an error, not silent."""
    project = _write(
        tmp_path / "proj" / CONFIG_FILENAME,
        {"extends": "../does-not-exist/scaffold.yaml"},
    )

    with pytest.raises(ConfigError, match="was not found"):
        load_config(project)


def test_extends_cycle_raises(tmp_path: Path) -> None:
    """A -> B -> A cycle is detected and reported."""
    _write(
        tmp_path / "a" / CONFIG_FILENAME,
        {"extends": "../b/scaffold.yaml"},
    )
    _write(
        tmp_path / "b" / CONFIG_FILENAME,
        {"extends": "../a/scaffold.yaml"},
    )

    with pytest.raises(ConfigError, match="Circular 'extends'"):
        load_config(tmp_path / "a" / CONFIG_FILENAME)


def test_extends_non_string_raises(tmp_path: Path) -> None:
    """A non-string ``extends`` is a clear error."""
    project = _write(tmp_path / CONFIG_FILENAME, {"extends": ["a", "b"]})

    with pytest.raises(ConfigError, match="must be a string"):
        load_config(project)


def test_extends_directory_resolves_to_scaffold_yaml(tmp_path: Path) -> None:
    """An ``extends`` pointing at a directory uses that dir's scaffold.yaml."""
    _write(tmp_path / "shared" / CONFIG_FILENAME, {"rigor": "strict"})
    project = _write(
        tmp_path / "proj" / CONFIG_FILENAME,
        {"extends": "../shared"},
    )

    config = load_config(project)
    assert config.rigor == "strict"


def test_resolve_config_chain_order(tmp_path: Path) -> None:
    """resolve_config_chain returns base-first, project-last."""
    base = _write(tmp_path / "base" / CONFIG_FILENAME, {"rigor": "strict"}).resolve()
    project = _write(
        tmp_path / "p" / CONFIG_FILENAME,
        {"extends": "../base/scaffold.yaml"},
    ).resolve()

    chain = resolve_config_chain(project)

    assert chain == [base, project]


def test_resolve_config_chain_single(tmp_path: Path) -> None:
    """A config with no extends yields a single-element chain."""
    project = _write(tmp_path / CONFIG_FILENAME, {"rigor": "standard"}).resolve()
    assert resolve_config_chain(project) == [project]
