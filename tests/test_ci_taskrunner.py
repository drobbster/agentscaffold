"""Tests for CI setup and task runner generation."""

from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from agentscaffold.cli import app


def test_ci_setup_github(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CI setup generates .github/workflows/ci.yml."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["ci"])
        assert result.exit_code == 0

        ci_yml = tmp_project / ".github" / "workflows" / "ci.yml"
        assert ci_yml.is_file()
        content = ci_yml.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_ci_setup_security(tmp_project: Path, cli_runner: CliRunner) -> None:
    """CI setup generates security.yml when security_scanning is enabled."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["ci"])
        assert result.exit_code == 0

        # security_scanning defaults to True
        sec_yml = tmp_project / ".github" / "workflows" / "security.yml"
        assert sec_yml.is_file()
        content = sec_yml.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_ci_setup_no_config(tmp_path: Path, cli_runner: CliRunner) -> None:
    """CI setup without scaffold.yaml fails gracefully."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["ci"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_justfile(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner generates justfile."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "justfile"])
        assert result.exit_code == 0

        justfile = tmp_project / "justfile"
        assert justfile.is_file()
        content = justfile.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_makefile(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner generates Makefile."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "makefile"])
        assert result.exit_code == 0

        makefile = tmp_project / "Makefile"
        assert makefile.is_file()
        content = makefile.read_text()
        assert len(content) > 0
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_both(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner with 'both' generates both justfile and Makefile."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "both"])
        assert result.exit_code == 0

        assert (tmp_project / "justfile").is_file()
        assert (tmp_project / "Makefile").is_file()
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_no_config(tmp_path: Path, cli_runner: CliRunner) -> None:
    """taskrunner without scaffold.yaml fails gracefully."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = cli_runner.invoke(app, ["taskrunner"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_taskrunner_invalid_format(tmp_project: Path, cli_runner: CliRunner) -> None:
    """taskrunner with invalid format fails."""
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["taskrunner", "-f", "invalid"])
        assert result.exit_code == 1
    finally:
        os.chdir(orig_cwd)


def test_ci_template_runs_the_inventory_check_when_enabled() -> None:
    """Inventory check, and INV-008 over a pull request's changed files."""
    import yaml

    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.rendering import get_default_context, render_template

    config = ScaffoldConfig()
    assert "inventory" not in render_template("ci/github_ci.yml.j2", get_default_context(config))

    config.inventory.enabled = True
    text = render_template("ci/github_ci.yml.j2", get_default_context(config))
    steps = {s["name"]: s for s in yaml.safe_load(text)["jobs"]["test"]["steps"] if "name" in s}
    assert steps["System inventory"]["run"] == "scaffold inventory check"
    changed = steps["Paused or deprecated components changed (INV-008)"]
    assert changed["if"] == "github.event_name == 'pull_request'"
    assert "origin/${{ github.base_ref }}" in changed["run"]
    assert "scaffold inventory check --changed-files -" in changed["run"]


def test_ci_template_renders_each_inventory_step_once() -> None:
    """A dict keyed by step name hides duplicates, so count the raw list."""
    import yaml

    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.rendering import get_default_context, render_template

    config = ScaffoldConfig()
    config.inventory.enabled = True
    text = render_template("ci/github_ci.yml.j2", get_default_context(config))
    steps = yaml.safe_load(text)["jobs"]["test"]["steps"]
    names = [s["name"] for s in steps if "name" in s]
    assert names.count("System inventory") == 1
    assert names.count("Paused or deprecated components changed (INV-008)") == 1
    assert len(names) == len(set(names))


def test_inventory_review_workflow_is_written_only_when_enabled_and_absent(
    tmp_path: Path,
) -> None:
    import yaml

    from agentscaffold import __version__
    from agentscaffold.ci.setup import write_inventory_review_workflow
    from agentscaffold.config import ScaffoldConfig

    config = ScaffoldConfig()
    assert write_inventory_review_workflow(tmp_path, config) is None

    config.inventory.enabled = True
    assert write_inventory_review_workflow(tmp_path, config, dry_run=True) is not None
    assert not (tmp_path / ".github").exists()

    path = write_inventory_review_workflow(tmp_path, config)
    assert path == tmp_path / ".github" / "workflows" / "inventory-review.yml"
    data = yaml.safe_load(path.read_text())
    on = data[True]  # YAML 1.1 reads the bare key `on` as a boolean
    assert on["schedule"] == [{"cron": "0 6 1 * *"}]
    assert "workflow_dispatch" in on
    assert data["permissions"] == {"contents": "read", "issues": "write"}
    assert data["concurrency"]["group"] == "inventory-review"

    steps = data["jobs"]["review"]["steps"]
    for step in steps:
        if "uses" in step:
            ref = step["uses"].split("@")[1]
            assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref)
    by_name = {s["name"]: s for s in steps}
    assert by_name["Checkout"]["with"]["fetch-depth"] == 0
    assert by_name["Install AgentScaffold"]["run"] == f'pip install "agentscaffold=={__version__}"'
    assert by_name["Derivation drift"]["continue-on-error"] is True
    assert "scaffold inventory refresh --dry-run" in by_name["Derivation drift"]["run"]
    packet = by_name["Review packet"]["run"]
    assert "scaffold inventory review --format markdown --exit-code" in packet
    issue = by_name["Open, update or close the review issue"]
    assert issue["env"]["DEBT"] == "${{ steps.review.outputs.code == '1' }}"
    for verb in ("gh issue create", "gh issue edit", "gh issue close"):
        assert verb in issue["run"]

    path.write_text("# edited by the project\n")
    assert write_inventory_review_workflow(tmp_path, config) is None
    assert path.read_text() == "# edited by the project\n"


def test_ci_setup_writes_the_review_workflow_when_inventory_is_enabled(
    tmp_project: Path, cli_runner: CliRunner
) -> None:
    assert "inventory:\n  enabled: true" in (tmp_project / "scaffold.yaml").read_text()
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        result = cli_runner.invoke(app, ["ci"])
        assert result.exit_code == 0, result.output
        assert (tmp_project / ".github" / "workflows" / "inventory-review.yml").is_file()
        assert "inventory-review.yml" in result.output
    finally:
        os.chdir(orig_cwd)
