"""Task runner setup (e.g., Makefile, Justfile)."""

from __future__ import annotations

from rich.console import Console

from agentscaffold.config import find_config, load_config
from agentscaffold.rendering import get_default_context, render_template

console = Console()

VALID_FORMATS = ("both", "justfile", "makefile")


def run_taskrunner_setup(fmt: str) -> None:
    """Set up task runner configuration in the specified format."""
    if fmt not in VALID_FORMATS:
        console.print(f"[red]Invalid format: {fmt}[/red]")
        console.print(f"Valid formats: {', '.join(VALID_FORMATS)}")
        raise SystemExit(1)

    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    config = load_config(config_path)
    context = get_default_context(config)

    written: list[str] = []

    if fmt in ("both", "justfile"):
        content = render_template("taskrunner/justfile.j2", context)
        dest = project_root / "justfile"
        dest.write_text(content)
        written.append(str(dest.relative_to(project_root)))

    if fmt in ("both", "makefile"):
        content = render_template("taskrunner/makefile.j2", context)
        dest = project_root / "Makefile"
        dest.write_text(content)
        written.append(str(dest.relative_to(project_root)))

    console.print("[bold]Task runner setup complete[/bold]")
    for f in written:
        console.print(f"  [green]Wrote[/green] {f}")
