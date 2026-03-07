"""Domain pack loading and installation."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from agentscaffold.config import CONFIG_FILENAME

console = Console()

_DOMAINS_DIR = Path(__file__).resolve().parent.parent / "domains"


def _get_available_packs() -> list[str]:
    """Return sorted list of available domain pack names."""
    if not _DOMAINS_DIR.is_dir():
        return []
    return sorted(
        d.name for d in _DOMAINS_DIR.iterdir() if d.is_dir() and (d / "manifest.yaml").is_file()
    )


def _load_manifest(pack: str) -> dict:
    """Load and return the manifest.yaml for a domain pack."""
    manifest_path = _DOMAINS_DIR / pack / "manifest.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"No manifest.yaml found for domain pack '{pack}'")
    with open(manifest_path) as fh:
        return yaml.safe_load(fh)


def _copy_pack_files(pack: str, project_dir: Path) -> list[str]:
    """Copy domain pack files into the project directory.

    Returns a list of relative paths that were written.
    """
    pack_dir = _DOMAINS_DIR / pack
    written: list[str] = []

    dir_map = {
        "prompts": "docs/ai/prompts",
        "standards": "docs/ai/standards",
        "security": "docs/security",
    }

    for src_subdir, dest_rel in dir_map.items():
        src_path = pack_dir / src_subdir
        if not src_path.is_dir():
            continue
        dest_path = project_dir / dest_rel
        dest_path.mkdir(parents=True, exist_ok=True)

        for src_file in sorted(src_path.iterdir()):
            if not src_file.is_file():
                continue
            out_name = src_file.name
            if out_name.endswith(".j2"):
                out_name = out_name[:-3]
            dest_file = dest_path / out_name
            if dest_file.exists():
                console.print(f"  [dim]skip (exists)[/dim] {dest_rel}/{out_name}")
            else:
                shutil.copy2(src_file, dest_file)
                written.append(f"{dest_rel}/{out_name}")
                console.print(f"  [green]wrote[/green] {dest_rel}/{out_name}")

    return written


def _update_scaffold_yaml(pack: str, manifest: dict, project_dir: Path) -> None:
    """Update scaffold.yaml to register the domain pack."""
    config_path = project_dir / CONFIG_FILENAME
    if not config_path.is_file():
        console.print(
            f"[yellow]Warning: {CONFIG_FILENAME} not found -- "
            "skipping config update. Run 'scaffold init' first.[/yellow]"
        )
        return

    with open(config_path) as fh:
        raw = yaml.safe_load(fh) or {}

    domains: list[str] = raw.get("domains", [])
    if pack not in domains:
        domains.append(pack)
        raw["domains"] = domains

    reviews: list[str] = raw.get("gates", {}).get("review_to_ready", {}).get("domain_reviews", [])
    for review in manifest.get("reviews", []):
        if review not in reviews:
            reviews.append(review)
    raw.setdefault("gates", {}).setdefault("review_to_ready", {})["domain_reviews"] = reviews

    standards: list[str] = raw.get("standards", {}).get("domain", [])
    for std in manifest.get("standards", []):
        if std not in standards:
            standards.append(std)
    raw.setdefault("standards", {})["domain"] = standards

    approval_gates = manifest.get("approval_gates", {})
    if approval_gates:
        existing_gates = raw.get("approval_required", {})
        for gate_name, gate_val in approval_gates.items():
            if gate_name not in existing_gates:
                existing_gates[gate_name] = gate_val
        raw["approval_required"] = existing_gates

    with open(config_path, "w") as fh:
        yaml.dump(raw, fh, default_flow_style=False, sort_keys=False)

    console.print(f"  [green]updated[/green] {CONFIG_FILENAME}")


def run_domain_add(pack: str) -> None:
    """Add a domain pack to the project."""
    available = _get_available_packs()
    if not available:
        console.print("[red]No domain packs found in package.[/red]")
        return

    if pack not in available:
        console.print(f"[red]Unknown domain pack '{pack}'.[/red]")
        console.print(f"Available packs: {', '.join(available)}")
        return

    manifest = _load_manifest(pack)
    display_name = manifest.get("display_name", pack)

    console.print(f"\nInstalling domain pack: [bold]{display_name}[/bold]")
    console.print(f"  {manifest.get('description', '')}\n")

    project_dir = Path.cwd()
    written = _copy_pack_files(pack, project_dir)
    _update_scaffold_yaml(pack, manifest, project_dir)

    console.print()
    table = Table(title="Installation Summary")
    table.add_column("Item", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Domain pack", display_name)
    table.add_row("Files installed", str(len(written)))
    table.add_row("Reviews added", ", ".join(manifest.get("reviews", [])) or "(none)")
    table.add_row("Standards added", ", ".join(manifest.get("standards", [])) or "(none)")
    console.print(table)
    console.print()
    console.print("[green]Domain pack installed.[/green]")
    console.print(
        "Run [bold]scaffold agents generate[/bold] to update AGENTS.md with domain rules."
    )
