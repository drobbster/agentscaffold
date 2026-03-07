"""Domain pack registry and listing."""

from __future__ import annotations

from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from agentscaffold.config import find_config

console = Console()

_DOMAINS_DIR = Path(__file__).resolve().parent.parent / "domains"


def _load_installed_domains() -> list[str]:
    """Load the list of installed domains from scaffold.yaml."""
    config_path = find_config()
    if config_path is None or not config_path.is_file():
        return []
    with open(config_path) as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("domains", [])


def run_domain_list() -> None:
    """List available domain packs with installation status."""
    if not _DOMAINS_DIR.is_dir():
        console.print("[red]No domains directory found in package.[/red]")
        return

    packs = sorted(
        d.name for d in _DOMAINS_DIR.iterdir() if d.is_dir() and (d / "manifest.yaml").is_file()
    )

    if not packs:
        console.print("[yellow]No domain packs available.[/yellow]")
        return

    installed = _load_installed_domains()

    table = Table(title="Available Domain Packs", show_lines=True)
    table.add_column("Pack", style="cyan", no_wrap=True)
    table.add_column("Display Name", style="bold")
    table.add_column("Installed", justify="center")
    table.add_column("Description", style="dim")

    for pack_name in packs:
        manifest_path = _DOMAINS_DIR / pack_name / "manifest.yaml"
        try:
            with open(manifest_path) as fh:
                manifest = yaml.safe_load(fh) or {}
        except Exception:
            manifest = {}

        display_name = manifest.get("display_name", pack_name)
        description = manifest.get("description", "")
        is_installed = pack_name in installed
        marker = "[green]Yes[/green]" if is_installed else "[dim]No[/dim]"

        table.add_row(pack_name, display_name, marker, description)

    console.print()
    console.print(table)
    console.print()
    console.print("Install a pack with: [bold]scaffold domains add <pack>[/bold]")
