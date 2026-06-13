"""Tests for Phase D: Plugin manifest and packaging (Steps D.4-D.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# PluginManifest tests (D.4)
# ---------------------------------------------------------------------------


def test_plugin_manifest_valid():
    from agentscaffold.plugins.manifest import PluginManifest

    m = PluginManifest(
        name="agentscaffold-trading",
        version="1.0.0",
        description="Trading domain pack",
    )
    assert m.name == "agentscaffold-trading"
    assert m.version == "1.0.0"


def test_plugin_manifest_invalid_semver():
    from pydantic import ValidationError

    from agentscaffold.plugins.manifest import PluginManifest

    with pytest.raises(ValidationError, match="semver"):
        PluginManifest(name="test", version="not-semver")


def test_plugin_manifest_semver_with_prerelease():
    from agentscaffold.plugins.manifest import PluginManifest

    m = PluginManifest(name="test", version="1.0.0-alpha.1")
    assert m.version == "1.0.0-alpha.1"


def test_plugin_manifest_fields():
    from agentscaffold.plugins.manifest import PluginManifest

    m = PluginManifest(
        name="test",
        version="0.1.0",
        description="desc",
        skills=["src/test/skills/foo.md"],
        agents=["src/test/agents/bar.md"],
        hooks=["src/test/hooks/baz.json"],
        mcp_servers={"agentscaffold": {"command": "scaffold"}},
        domain_pack="trading",
    )
    assert m.skills == ["src/test/skills/foo.md"]
    assert m.agents == ["src/test/agents/bar.md"]
    assert m.hooks == ["src/test/hooks/baz.json"]
    assert m.mcp_servers == {"agentscaffold": {"command": "scaffold"}}
    assert m.domain_pack == "trading"


def test_plugin_manifest_defaults():
    from agentscaffold.plugins.manifest import PluginManifest

    m = PluginManifest(name="test", version="0.1.0")
    assert m.skills == []
    assert m.agents == []
    assert m.hooks == []
    assert m.mcp_servers == {}
    assert m.domain_pack is None


def test_plugin_manifest_validate_files_exist(tmp_path: Path):
    from agentscaffold.plugins.manifest import PluginManifest

    (tmp_path / "existing.md").write_text("skill")
    m = PluginManifest(
        name="test",
        version="0.1.0",
        skills=["existing.md", "missing.md"],
    )
    missing = m.validate_files_exist(tmp_path)
    assert missing == ["missing.md"]


def test_plugin_manifest_validate_all_present(tmp_path: Path):
    from agentscaffold.plugins.manifest import PluginManifest

    (tmp_path / "a.md").write_text("skill")
    m = PluginManifest(name="test", version="0.1.0", skills=["a.md"])
    missing = m.validate_files_exist(tmp_path)
    assert missing == []


def test_plugin_manifest_roundtrip_json(tmp_path: Path):
    from agentscaffold.plugins.manifest import PluginManifest

    m = PluginManifest(
        name="agentscaffold-trading",
        version="1.2.3",
        description="Trading plugin",
        domain_pack="trading",
        skills=["src/skills/rl_patterns.md"],
    )
    path = tmp_path / "plugin.json"
    m.to_json(path)
    assert path.exists()
    loaded = PluginManifest.from_json(path)
    assert loaded.name == "agentscaffold-trading"
    assert loaded.version == "1.2.3"
    assert loaded.skills == ["src/skills/rl_patterns.md"]


# ---------------------------------------------------------------------------
# package_domain_plugin tests (D.5)
# ---------------------------------------------------------------------------


def test_package_domain_plugin_creates_structure(tmp_path: Path):
    from unittest.mock import patch

    from agentscaffold.plugins.packaging import package_domain_plugin

    # Create fake domain dir
    domain_dir = tmp_path / "domains" / "trading"
    domain_dir.mkdir(parents=True)
    (domain_dir / "manifest.yaml").write_text(
        "name: trading\ndisplay_name: Trading\ndescription: Quant trading pack\n"
    )
    std_dir = domain_dir / "standards"
    std_dir.mkdir()
    (std_dir / "rl_patterns.md").write_text("# RL Patterns\n\nDo this.\n")

    output_dir = tmp_path / "dist"

    with patch(
        "agentscaffold.domain_packs.loader._DOMAINS_DIR",
        tmp_path / "domains",
    ):
        pkg_dir = package_domain_plugin("trading", output_dir)

    assert (pkg_dir / "pyproject.toml").exists()
    assert (pkg_dir / "plugin.json").exists()
    assert (pkg_dir / "src" / "agentscaffold_trading" / "__init__.py").exists()
    assert (pkg_dir / "src" / "agentscaffold_trading" / "domain_pack").is_dir()


def test_package_domain_plugin_pyproject_content(tmp_path: Path):
    from unittest.mock import patch

    from agentscaffold.plugins.packaging import package_domain_plugin

    domain_dir = tmp_path / "domains" / "trading"
    domain_dir.mkdir(parents=True)
    (domain_dir / "manifest.yaml").write_text(
        "name: trading\ndisplay_name: Trading\ndescription: desc\n"
    )

    output_dir = tmp_path / "dist"
    with patch("agentscaffold.domain_packs.loader._DOMAINS_DIR", tmp_path / "domains"):
        pkg_dir = package_domain_plugin("trading", output_dir, version="2.0.0")

    pyproject = (pkg_dir / "pyproject.toml").read_text()
    assert 'version = "2.0.0"' in pyproject
    assert "agentscaffold-trading" in pyproject


def test_package_domain_plugin_dry_run(tmp_path: Path):
    from unittest.mock import patch

    from agentscaffold.plugins.packaging import package_domain_plugin

    domain_dir = tmp_path / "domains" / "trading"
    domain_dir.mkdir(parents=True)
    (domain_dir / "manifest.yaml").write_text(
        "name: trading\ndisplay_name: Trading\ndescription: desc\n"
    )

    output_dir = tmp_path / "dist"
    with patch("agentscaffold.domain_packs.loader._DOMAINS_DIR", tmp_path / "domains"):
        pkg_dir = package_domain_plugin("trading", output_dir, dry_run=True)

    assert not (pkg_dir / "pyproject.toml").exists()


def test_package_domain_plugin_missing_domain(tmp_path: Path):
    from unittest.mock import patch

    from agentscaffold.plugins.packaging import package_domain_plugin

    with patch("agentscaffold.domain_packs.loader._DOMAINS_DIR", tmp_path / "domains"):
        with pytest.raises(FileNotFoundError, match="not found"):
            package_domain_plugin("nonexistent", tmp_path / "dist")


def test_package_domain_plugin_skills_generated(tmp_path: Path):
    from unittest.mock import patch

    from agentscaffold.plugins.packaging import package_domain_plugin

    domain_dir = tmp_path / "domains" / "trading"
    domain_dir.mkdir(parents=True)
    (domain_dir / "manifest.yaml").write_text(
        "name: trading\ndisplay_name: Trading\ndescription: desc\n"
    )
    std_dir = domain_dir / "standards"
    std_dir.mkdir()
    (std_dir / "rl_patterns.md").write_text("# RL Patterns\n\nRL content.\n")
    (std_dir / "performance_patterns.md").write_text("# Performance\n\nPerf content.\n")

    output_dir = tmp_path / "dist"
    with patch("agentscaffold.domain_packs.loader._DOMAINS_DIR", tmp_path / "domains"):
        pkg_dir = package_domain_plugin("trading", output_dir)

    skills_dir = pkg_dir / "src" / "agentscaffold_trading" / "skills"
    assert (skills_dir / "rl_patterns.md").exists()
    assert (skills_dir / "performance_patterns.md").exists()


def test_package_domain_plugin_manifest_references_skills(tmp_path: Path):
    from unittest.mock import patch

    from agentscaffold.plugins.manifest import PluginManifest
    from agentscaffold.plugins.packaging import package_domain_plugin

    domain_dir = tmp_path / "domains" / "trading"
    domain_dir.mkdir(parents=True)
    (domain_dir / "manifest.yaml").write_text(
        "name: trading\ndisplay_name: Trading\ndescription: desc\n"
    )
    std_dir = domain_dir / "standards"
    std_dir.mkdir()
    (std_dir / "rl_patterns.md").write_text("# RL Patterns\nBody.\n")

    output_dir = tmp_path / "dist"
    with patch("agentscaffold.domain_packs.loader._DOMAINS_DIR", tmp_path / "domains"):
        pkg_dir = package_domain_plugin("trading", output_dir)

    manifest = PluginManifest.from_json(pkg_dir / "plugin.json")
    assert any("rl_patterns.md" in s for s in manifest.skills)
