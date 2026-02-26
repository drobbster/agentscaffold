"""Integration verification checks."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config

console = Console()

REQUIRED_CONTRACT_SECTIONS = [
    "Version",
    "Provider",
    "Consumers",
]

REQUIRED_CONTRACT_CONTENT_SECTIONS = [
    "Public Classes",
    "Public Functions",
]


def _find_project_root() -> Path | None:
    """Find the project root by locating scaffold.yaml."""
    cfg_path = find_config()
    if cfg_path is not None:
        return cfg_path.parent
    return None


def _parse_registry_contracts(readme_path: Path) -> list[str]:
    """Extract contract file references from the contracts/README.md registry table."""
    if not readme_path.is_file():
        return []

    text = readme_path.read_text(encoding="utf-8")
    contracts: list[str] = []

    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        for cell in cells:
            md_links = re.findall(r"\[.*?\]\((.*?\.md)\)", cell)
            contracts.extend(md_links)

    return contracts


def check_integration() -> list[str]:
    """Run integration verification and return list of issues."""
    issues: list[str] = []

    root = _find_project_root()
    if root is None:
        issues.append("Could not find project root (no scaffold.yaml found)")
        return issues

    contracts_dir = root / "docs" / "ai" / "contracts"
    if not contracts_dir.is_dir():
        issues.append(f"Contracts directory not found: {contracts_dir}")
        return issues

    readme_path = contracts_dir / "README.md"
    if not readme_path.is_file():
        issues.append(f"Contract registry not found: {readme_path}")
        return issues

    referenced = _parse_registry_contracts(readme_path)
    if not referenced:
        console.print("[dim]No contract references found in registry table[/dim]")
        return issues

    for ref in referenced:
        contract_path = contracts_dir / ref
        if not contract_path.is_file():
            issues.append(f"Contract referenced in registry but file missing: {ref}")
            continue

        content = contract_path.read_text(encoding="utf-8")
        headings = {m.group(1).strip() for m in re.finditer(r"^#+\s+(.+)$", content, re.MULTILINE)}

        for section in REQUIRED_CONTRACT_SECTIONS:
            if not any(section.lower() in h.lower() for h in headings):
                issues.append(f"{ref}: missing required section '{section}'")

        has_content_section = any(
            any(s.lower() in h.lower() for h in headings)
            for s in REQUIRED_CONTRACT_CONTENT_SECTIONS
        )
        if not has_content_section:
            issues.append(
                f"{ref}: missing at least one of: "
                + ", ".join(f"'{s}'" for s in REQUIRED_CONTRACT_CONTENT_SECTIONS)
            )

    return issues
