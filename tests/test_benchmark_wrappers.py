"""Offline tests that equipped-arm wrappers match the current CLI."""

from __future__ import annotations

from agentscaffold.benchmark.arms import get_arm
from agentscaffold.benchmark.tool_wrappers import SCAFFOLD_TOOL_SCRIPTS, render_install_command
from agentscaffold.cli import app


def test_wrapper_scripts_call_current_scaffold_cli() -> None:
    scripts = SCAFFOLD_TOOL_SCRIPTS

    assert "scaffold graph orient" in scripts["scaffold-orient"]
    assert "scaffold graph search" in scripts["scaffold-search"]
    assert "scaffold review prepare" in scripts["scaffold-review"]
    assert "scaffold graph impact" in scripts["scaffold-impact"]

    assert "scaffold review brief" not in scripts["scaffold-review"]
    assert "scaffold graph search" not in scripts["scaffold-impact"]
    for script in scripts.values():
        assert "cd /testbed" in script


def test_wrapper_install_command_writes_all_scripts() -> None:
    install = render_install_command()

    for name in ("scaffold-orient", "scaffold-search", "scaffold-review", "scaffold-impact"):
        assert f"/usr/local/bin/{name}" in install
        assert f"chmod +x /usr/local/bin/{name}" in install


def test_equipped_arm_generates_routing_before_index() -> None:
    arm = get_arm("equipped")

    assert arm.setup_commands == (
        "scaffold init --non-interactive",
        "scaffold agents generate-all",
        "scaffold index",
    )
    assert "Match the job to the first AgentScaffold tool" in arm.prompt_guidance
    assert "count is not the metric" in arm.prompt_guidance


def test_graph_impact_help_is_wired(cli_runner) -> None:
    result = cli_runner.invoke(app, ["graph", "impact", "--help"])

    assert result.exit_code == 0
    output = result.output.lower()
    assert "blast radius" in output or "importers" in output
    assert "file path or symbol" in output or "file-or-symbol" in output or "target" in output


def test_graph_impact_fails_closed_without_graph(cli_runner, monkeypatch) -> None:
    monkeypatch.setattr("agentscaffold.graph.graph_available", lambda _config: False)
    result = cli_runner.invoke(app, ["graph", "impact", "router.py"])

    assert result.exit_code == 1
    assert "No knowledge graph found" in result.output
