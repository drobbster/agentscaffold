"""Regression: quiet incremental index must not write Rich progress to stdout.

Plan 242 -- MCP stdio hosts treat stdout as JSON-RPC. In-process incremental
refresh used to print ``Incremental index...`` / Index Summary tables to
stdout, which Cursor parsed as invalid JSON and then marked the transport
failed (``Not connected``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.graph import index
from agentscaffold.graph.pipeline import install_stdio_safe_console, run_pipeline

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def indexed_repo(tmp_path: Path) -> Path:
    """Copy sample_repo and full-index it (quiet to keep test output clean)."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(repo / ".scaffold" / "graph.db")))
    run_pipeline(repo, config=cfg, quiet=True)
    return repo


def _progress_leaked(stdout: str) -> list[str]:
    needles = (
        "Incremental index",
        "Graph is up to date",
        "Index Summary",
        "Refreshed",
        "Re-parsing",
    )
    return [n for n in needles if n in stdout]


def test_quiet_incremental_noop_keeps_stdout_clean(indexed_repo: Path, capsys) -> None:
    """Quiet no-op incremental must not emit progress to stdout."""
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(indexed_repo / ".scaffold" / "graph.db")))
    summary = index(path=indexed_repo, config=cfg, incremental=True, quiet=True)
    captured = capsys.readouterr()

    assert summary.get("noop") is True or "incremental" in summary.get("phases_completed", [])
    assert _progress_leaked(captured.out) == [], captured.out


def test_quiet_incremental_after_edit_keeps_stdout_clean(indexed_repo: Path, capsys) -> None:
    """Quiet incremental with real work must still keep stdout clean."""
    py = next(indexed_repo.rglob("*.py"))
    py.write_text(py.read_text() + "\n# plan-242 stdout guard\n")

    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(indexed_repo / ".scaffold" / "graph.db")))
    summary = index(path=indexed_repo, config=cfg, incremental=True, quiet=True)
    captured = capsys.readouterr()

    assert summary.get("noop") is not True
    assert _progress_leaked(captured.out) == [], captured.out


def test_non_quiet_incremental_still_prints(indexed_repo: Path, capsys) -> None:
    """CLI default (quiet=False) still shows progress on stdout."""
    cfg = ScaffoldConfig(graph=GraphConfig(db_path=str(indexed_repo / ".scaffold" / "graph.db")))
    index(path=indexed_repo, config=cfg, incremental=True, quiet=False)
    captured = capsys.readouterr()

    assert "Incremental index" in captured.out or "Graph is up to date" in captured.out


def test_install_stdio_safe_console_suppresses_prints(capsys) -> None:
    """MCP startup helper must silence subsequent pipeline console prints."""
    from agentscaffold.graph import pipeline as pipeline_mod

    previous = pipeline_mod.console
    try:
        install_stdio_safe_console()
        pipeline_mod.console.print("Incremental index -- should be silenced")
        captured = capsys.readouterr()
        assert "Incremental index" not in captured.out
    finally:
        pipeline_mod.console = previous
