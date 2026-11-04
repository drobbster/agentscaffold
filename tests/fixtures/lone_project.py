"""A registered, indexed single-project repository for dispatch-level tests.

Built from ``sample_repo`` with an optional ``workflow_state.md`` and extra plan
files, so tests can drive real tool calls through ``_dispatch_tool`` without a
workspace.yaml.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SAMPLE_REPO = Path(__file__).parent / "sample_repo"

DRAFT_PLAN_NUMBER = 90
DRAFT_PLAN_TITLE = "Add retry budget"

DRAFT_PLAN = f"""# Plan {DRAFT_PLAN_NUMBER:03d}: {DRAFT_PLAN_TITLE}

## 0. Metadata
- Plan: {DRAFT_PLAN_NUMBER}
- Status: Draft
- Created: 2026-03-02
- Last Updated: 2026-03-02

## 6. Execution Steps
- [ ] Step 1: Write the failing test.
- [ ] Step 2: Implement the budget.
"""

#: Lists Plan 042 as in progress although its file says Complete.
STALE_WORKFLOW = """# Workflow State

**Last Updated**: 2026-01-05 (sample)

## Blockers

- Plan 090 waits on a design note.

## Current Implementation

- Plan 042 -- In Progress: data router refactor.

## Next Steps

- None
"""


def build_lone_project(
    tmp_path: Path,
    *,
    name: str = "lone",
    workflow: str | None = None,
    draft_plan: bool = False,
    extra_config: str = "",
) -> Path:
    """Copy, index and register a lone repository; return its root."""
    from agentscaffold.config import load_config
    from agentscaffold.graph.pipeline import run_pipeline
    from agentscaffold.workspace_registry import register_workspace

    repo = tmp_path / name
    shutil.copytree(SAMPLE_REPO, repo)
    (repo / "scaffold.yaml").write_text(
        f"project:\n  name: {name}\ngraph:\n  db_path: {tmp_path / f'{name}.duckdb'}\n"
        + extra_config
    )
    if workflow is not None:
        (repo / "docs" / "ai" / "state" / "workflow_state.md").write_text(workflow)
    if draft_plan:
        plan = repo / "docs" / "ai" / "plans" / f"plan_{DRAFT_PLAN_NUMBER:03d}_retry_budget.md"
        plan.write_text(DRAFT_PLAN)
    run_pipeline(root=repo, config=load_config(repo / "scaffold.yaml"))
    register_workspace(repo, name=name)
    return repo
