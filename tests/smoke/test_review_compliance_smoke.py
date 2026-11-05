"""End-to-end smoke for Plan 281: review stamp, change, and post-implementation rules.

A governance repository whose ``implementation_project`` is a code repository,
both registered and under git, committing directly to ``main``. The
pre-implementation review records each repository's HEAD; the plan's changes
are then committed in both; the completion chain's rule rows must find those
changes from the recorded commits and judge them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.smoke]

PLAN = 101
IGNORE = ".scaffold/\ndocs/ai/state/governance.json\n"
PLAN_TEXT = f"""# Plan {PLAN}: Faster foo

## 0. Metadata
- Plan: {PLAN}
- Status: In Progress
- Breaking change: No

## 6. File Impact Map
| File | Change Type | Notes |
|------|-------------|-------|
| src/pkg/foo.py | Modify | in pkg |

## 8. Execution Steps
- [x] Step 1: Make foo faster.
"""


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _index_and_register(repo: Path, name: str) -> None:
    from agentscaffold.config import find_config, load_config
    from agentscaffold.graph.pipeline import run_pipeline
    from agentscaffold.workspace_registry import register_workspace

    run_pipeline(root=repo, config=load_config(find_config(start=repo)))
    register_workspace(repo, name=name)


@pytest.fixture()
def repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    pytest.importorskip("duckdb", reason="duckdb not installed")
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(tmp_path / "home"))
    gov = tmp_path / "gov"
    pkg = tmp_path / "pkg"
    _write(
        gov,
        {
            ".gitignore": IGNORE,
            "scaffold.yaml": "framework:\n  project_name: gov\nimplementation_project: pkg\n",
            f"docs/ai/plans/{PLAN}-faster-foo.md": PLAN_TEXT,
            "docs/ai/state/workflow_state.md": "# Workflow State\n",
        },
    )
    _write(
        pkg,
        {
            ".gitignore": IGNORE,
            "scaffold.yaml": "framework:\n  project_name: pkg\n",
            "src/pkg/__init__.py": "",
            "src/pkg/foo.py": "def foo():\n    return 1\n",
        },
    )
    for repo, name in ((pkg, "pkg"), (gov, "gov")):
        _index_and_register(repo, name)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
    return gov, pkg


def _dispatch(repo: Path, monkeypatch: pytest.MonkeyPatch, name: str, **args) -> dict:
    from agentscaffold.mcp import freshness
    from agentscaffold.mcp.server import _dispatch_tool

    monkeypatch.setattr(
        freshness, "evaluate_freshness", lambda *_a, **_k: {"freshness_status": "fresh"}
    )
    return _dispatch_tool(name, {"working_path": str(repo), **args})


def test_review_stamp_change_and_rules_across_two_projects(
    repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    gov, pkg = repos
    reviewed = {"gov": _git(gov, "rev-parse", "HEAD"), "pkg": _git(pkg, "rev-parse", "HEAD")}

    begun = _dispatch(gov, monkeypatch, "scaffold_begin_plan", plan_number=PLAN)
    assert begun.get("reviewed_at"), begun

    recorded = _dispatch(
        gov,
        monkeypatch,
        "scaffold_record_finding",
        plan_number=PLAN,
        review_type="devils_advocate",
        severity="high",
        category="RISK",
        finding="foo has no caller benchmark.",
    )
    finding_id = recorded["id"]

    _commit(pkg, {"src/pkg/foo.py": "def foo():\n    return 2\n"}, "Make foo faster")
    _commit(gov, {"docs/ai/state/workflow_state.md": "# Workflow State\nPlan 101 done.\n"}, "wf")

    first = _dispatch(gov, monkeypatch, "scaffold_complete_plan", plan_number=PLAN, dry_run=True)
    rows = {r["check"]: r for r in first["retro"]["verification"]}
    workflow = rows["workflow_state_updated"]
    assert workflow["status"] == "pass", workflow
    assert workflow["evidence"]["change_sources"] == {
        "gov": "reviewed_commits",
        "pkg": "reviewed_commits",
    }
    assert reviewed["pkg"][:12] in workflow["detail"]
    assert rows["pre_review_disposition"]["status"] == "warn"
    assert rows["pre_review_disposition"]["evidence"]["undisposed"] == [finding_id]
    assert rows["read_only_paths"]["status"] == "skip"

    resolved = _dispatch(
        gov,
        monkeypatch,
        "scaffold_resolve_finding",
        finding_id=finding_id,
        resolution="Benchmarked in the pull request.",
        disposition="resolved",
    )
    assert resolved["status"] == "resolved", resolved

    second = _dispatch(gov, monkeypatch, "scaffold_complete_plan", plan_number=PLAN, dry_run=True)
    rows = {r["check"]: r for r in second["retro"]["verification"]}
    assert rows["pre_review_disposition"]["status"] == "pass"
    assert not second.get("gate_blocked")
