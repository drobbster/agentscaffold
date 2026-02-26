"""CI provider setup and configuration."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agentscaffold.config import find_config, load_config
from agentscaffold.rendering import get_default_context, render_template

console = Console()


def run_ci_setup(provider: str) -> None:
    """Set up CI configuration for the specified provider."""
    config_path = find_config()
    if config_path is None:
        console.print("[red]No scaffold.yaml found. Run 'scaffold init' first.[/red]")
        raise SystemExit(1)

    project_root = config_path.parent
    config = load_config(config_path)
    context = get_default_context(config)

    if provider != "github":
        console.print(f"[red]Unsupported CI provider: {provider}[/red]")
        console.print("Supported providers: github")
        raise SystemExit(1)

    _setup_github(project_root, config, context)


def _setup_github(
    project_root: Path,
    config: object,
    context: dict,  # type: ignore[type-arg]
) -> None:
    """Generate GitHub Actions workflow files."""
    workflows_dir = project_root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []

    ci_content = render_template("ci/github_ci.yml.j2", context)
    ci_path = workflows_dir / "ci.yml"
    ci_path.write_text(ci_content)
    written.append(str(ci_path.relative_to(project_root)))

    if config.ci.security_scanning:  # type: ignore[union-attr]
        sec_content = render_template("ci/github_security.yml.j2", context)
        sec_path = workflows_dir / "security.yml"
        sec_path.write_text(sec_content)
        written.append(str(sec_path.relative_to(project_root)))

    if config.semi_autonomous.enabled:  # type: ignore[union-attr]
        sa_content = render_template("ci/github_semi_autonomous.yml.j2", context)
        sa_path = workflows_dir / "semi-autonomous-pr.yml"
        sa_path.write_text(sa_content)
        written.append(str(sa_path.relative_to(project_root)))

        pr_content = render_template("pr/pull_request_template.md.j2", context)
        pr_path = project_root / ".github" / "pull_request_template.md"
        pr_path.parent.mkdir(parents=True, exist_ok=True)
        pr_path.write_text(pr_content)
        written.append(str(pr_path.relative_to(project_root)))

        notify_content = render_template("scripts/notify_script.py.j2", context)
        notify_path = project_root / "scripts" / "notify.py"
        notify_path.parent.mkdir(parents=True, exist_ok=True)
        notify_path.write_text(notify_content)
        written.append(str(notify_path.relative_to(project_root)))

    console.print("[bold]CI setup complete (GitHub Actions)[/bold]")
    for f in written:
        console.print(f"  [green]Wrote[/green] {f}")
