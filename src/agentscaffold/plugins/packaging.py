"""Plugin packaging tool — Step D.5.

Generates pip-installable packages from AgentScaffold domain packs.

Directory structure produced::

    <output_dir>/
      pyproject.toml
      plugin.json
      src/
        agentscaffold_<domain>/
          __init__.py
          domain_pack/          (copied from domains/<domain>/)
          skills/               (generated SKILL.md files)

Entry points are registered under the ``agentscaffold.plugins`` group so
AgentScaffold can auto-discover installed plugins.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.plugins.manifest import PluginManifest

console = Console()

_PYPROJECT_TOML_TEMPLATE = """\
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "{pkg_name}"
version = "{version}"
description = "{description}"
requires-python = ">=3.11"
dependencies = ["agentscaffold>=0.1"]

[project.entry-points."agentscaffold.plugins"]
{domain} = "{module_name}:plugin_manifest"

[tool.setuptools.packages.find]
where = ["src"]
"""

_INIT_PY_TEMPLATE = (
    '"""AgentScaffold plugin: {display_name}."""\n'
    "from pathlib import Path\n"
    "\n"
    "PLUGIN_DIR = Path(__file__).parent\n"
    "\n"
    "\n"
    "def plugin_manifest() -> str:\n"
    '    """Return path to plugin.json."""\n'
    '    return str(PLUGIN_DIR / "plugin.json")\n'
)


def package_domain_plugin(
    domain: str,
    output_dir: Path,
    version: str = "0.1.0",
    dry_run: bool = False,
) -> Path:
    """Generate a pip-installable plugin package from a domain pack.

    Args:
        domain: Domain pack name (e.g. "trading").
        output_dir: Directory to write the package into.
        version: Semver version string for the generated package.
        dry_run: If True, return path without writing files.

    Returns:
        Path to the output directory.
    """
    from agentscaffold.domain_packs.loader import (  # noqa: PLC0415
        _DOMAINS_DIR,
        _load_manifest,
    )

    domain_dir = _DOMAINS_DIR / domain
    if not domain_dir.is_dir():
        raise FileNotFoundError(f"Domain pack not found: {domain}")

    domain_manifest = _load_manifest(domain)
    display_name = domain_manifest.get("display_name", domain.replace("_", " ").title())
    description = domain_manifest.get("description", f"AgentScaffold {display_name} domain pack")

    pkg_name = f"agentscaffold-{domain.replace('_', '-')}"
    module_name = f"agentscaffold_{domain}"
    pkg_dir = output_dir / pkg_name

    if dry_run:
        console.print(f"[dim]dry-run[/dim] would create {pkg_dir}/")
        return pkg_dir

    # Create package structure
    src_dir = pkg_dir / "src" / module_name
    src_dir.mkdir(parents=True, exist_ok=True)

    # __init__.py
    (src_dir / "__init__.py").write_text(_INIT_PY_TEMPLATE.format(display_name=display_name))

    # Copy domain pack files
    import shutil  # noqa: PLC0415

    domain_dest = src_dir / "domain_pack"
    if domain_dest.exists():
        shutil.rmtree(domain_dest)
    shutil.copytree(domain_dir, domain_dest)

    # Generate skills from domain standards
    skills_dir = src_dir / "skills"
    skills_paths = _generate_domain_skills(domain_dir, skills_dir)

    # Build manifest
    skill_rel = [f"src/{module_name}/skills/{p.name}" for p in skills_paths]
    manifest = PluginManifest(
        name=pkg_name,
        version=version,
        description=description,
        skills=skill_rel,
        domain_pack=domain,
    )
    manifest.to_json(pkg_dir / "plugin.json")

    # pyproject.toml
    (pkg_dir / "pyproject.toml").write_text(
        _PYPROJECT_TOML_TEMPLATE.format(
            pkg_name=pkg_name,
            version=version,
            description=description,
            domain=domain,
            module_name=module_name,
        )
    )

    console.print(f"[green]Created[/green] {pkg_dir.relative_to(output_dir)}/")
    return pkg_dir


def _generate_domain_skills(domain_dir: Path, output_dir: Path) -> list[Path]:
    """Generate SKILL.md files from domain standards and return paths written."""
    from agentscaffold.skills.generator import (  # noqa: PLC0415
        generate_skills_from_standards_dir,
    )

    standards_dir = domain_dir / "standards"
    if not standards_dir.is_dir():
        return []
    return generate_skills_from_standards_dir(standards_dir, output_dir)
