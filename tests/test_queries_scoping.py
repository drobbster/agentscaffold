"""Multi-project read-scoping tests for review/queries.py (Plan 225, Step 6).

File paths and plan numbers are NOT unique across the projects sharing one
graph cache, so governance reads must default to the *current* project (resolved
from the working directory) and only widen on explicit ``project=`` /
``all_projects=``. These tests stand up a real two-project workspace, populate
colliding plans / file-keyed findings / learnings for both, then assert the
default read returns only the current project, a targeted read returns the
sibling, and federation returns both. Single-project repos are covered by the
no-op assertions in test_graph_scoping / the unchanged single-project suite.
"""

from __future__ import annotations

import pytest

from agentscaffold.review import queries as q

pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402


def _make_workspace(tmp_path, names):
    """Create ws/workspace.yaml listing *names*, each a project dir."""
    ws = tmp_path / "ws"
    ws.mkdir()
    lines = ["projects:"]
    for name in names:
        d = ws / name
        d.mkdir()
        (d / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
        (d / ".git").mkdir()
        lines.append(f"  - name: {name}")
        lines.append(f"    path: {name}")
    (ws / "workspace.yaml").write_text("\n".join(lines) + "\n")
    return ws


@pytest.fixture
def two_project_store(tmp_path, monkeypatch):
    """A backend holding alpha+beta governance data, cwd parked in alpha."""
    ws = _make_workspace(tmp_path, ["alpha", "beta"])
    try:
        store = DuckPGQBackend(":memory:")
    except RuntimeError as exc:  # duckpgq extension unavailable
        pytest.skip(f"duckpgq unavailable: {exc}")
    store.init_schema()

    for proj, suffix in (("alpha", "A"), ("beta", "B")):
        store.set_write_project(proj)
        # Colliding plan number across projects.
        store.create_node("Plan", {"id": "plan::1", "number": 1, "title": f"Plan-{suffix}"})
        # Colliding file path across projects.
        store.create_node("File", {"id": "file::shared.py", "path": "shared.py"})
        store.create_node(
            "ReviewFinding",
            {"id": "rf::1", "finding": f"Finding-{suffix}", "category": "x", "severity": "low"},
        )
        store.create_edge("FINDING_ABOUT_FILE", "ReviewFinding", "rf::1", "File", "file::shared.py")
        store.create_node(
            "Learning",
            {"id": "lr::1", "learningId": f"L-{suffix}", "description": f"Learning-{suffix}"},
        )
        store.create_edge(
            "LEARNING_RELATES_TO_FILE", "Learning", "lr::1", "File", "file::shared.py"
        )

    monkeypatch.chdir(ws / "alpha")
    yield store
    store.close()


# ---------------------------------------------------------------------------
# Plain-SELECT reads (plans)
# ---------------------------------------------------------------------------


def test_get_all_plans_defaults_to_current_project(two_project_store):
    titles = [p["p.title"] for p in q.get_all_plans(two_project_store)]
    assert titles == ["Plan-A"]


def test_get_all_plans_targets_sibling(two_project_store):
    titles = [p["p.title"] for p in q.get_all_plans(two_project_store, project="beta")]
    assert titles == ["Plan-B"]


def test_get_all_plans_federated(two_project_store):
    titles = sorted(p["p.title"] for p in q.get_all_plans(two_project_store, all_projects=True))
    assert titles == ["Plan-A", "Plan-B"]


def test_get_plan_by_number_scoped(two_project_store):
    assert q.get_plan_by_number(two_project_store, 1)["p.title"] == "Plan-A"
    assert q.get_plan_by_number(two_project_store, 1, project="beta")["p.title"] == "Plan-B"


# ---------------------------------------------------------------------------
# File-keyed governance reads (findings / learnings) -- the misorientation risk
# ---------------------------------------------------------------------------


def test_findings_for_shared_path_scoped(two_project_store):
    cur = [r["rf.finding"] for r in q.get_findings_for_file(two_project_store, "shared.py")]
    assert cur == ["Finding-A"]
    sib = [
        r["rf.finding"]
        for r in q.get_findings_for_file(two_project_store, "shared.py", project="beta")
    ]
    assert sib == ["Finding-B"]


def test_findings_for_shared_path_federated(two_project_store):
    both = sorted(
        r["rf.finding"]
        for r in q.get_findings_for_file(two_project_store, "shared.py", all_projects=True)
    )
    assert both == ["Finding-A", "Finding-B"]


def test_learnings_for_shared_path_scoped(two_project_store):
    cur = [r["lr.description"] for r in q.get_learnings_for_file(two_project_store, "shared.py")]
    assert cur == ["Learning-A"]
    sib = [
        r["lr.description"]
        for r in q.get_learnings_for_file(two_project_store, "shared.py", project="beta")
    ]
    assert sib == ["Learning-B"]
