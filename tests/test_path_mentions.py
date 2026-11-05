"""Findings and learnings keep the paths they are about.

``record_finding`` used to keep a path only as a FINDING_ABOUT_FILE edge, and
only when a File node for it existed in the same project. In a split setup
(governance in one repository, code in another) that dropped every path, so
nothing could later find the findings about a file. Paths are now normalized
to project-relative form and stored in a ``paths`` column whether or not a
File node exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.findings import record_finding, record_findings_batch
from agentscaffold.graph.governance import process_governance
from agentscaffold.review.path_mentions import collect_paths, extract_paths, to_project_relative

pytest.importorskip("duckdb", reason="duckdb not installed")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "see `src/agentscaffold/mcp/server.py:1870` for the gate",
            ["src/agentscaffold/mcp/server.py"],
        ),
        ("column at src/agentscaffold/mcp/server.py:1870:5.", ["src/agentscaffold/mcp/server.py"]),
        ("run ./tests/test_gate.py first", ["tests/test_gate.py"]),
        ("(see docs/ai/plans/281-x.md)", ["docs/ai/plans/281-x.md"]),
        ("the whole src/agentscaffold/graph/ package", ["src/agentscaffold/graph"]),
        ("update CHANGELOG.md and scaffold.yaml", ["CHANGELOG.md", "scaffold.yaml"]),
        ("a.py then b.py then a.py", ["a.py", "b.py"]),
    ],
)
def test_extract_paths_finds_path_mentions(text: str, expected: list[str]):
    assert extract_paths(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "see https://github.com/org/repo/blob/main/src/x.py for details",
        "e.g. the ratio is 3.5 and i.e. it holds",
        "agentscaffold.graph.findings is a module name, not a path",
        "read and/or write; 1/2 of the cases",
        "",
    ],
)
def test_extract_paths_ignores_urls_and_prose(text: str):
    assert extract_paths(text) == []


def test_extract_paths_is_capped():
    text = " ".join(f"src/m{i}.py" for i in range(30))
    assert len(extract_paths(text)) == 20


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.fixture()
def monorepo(tmp_path: Path) -> tuple[Path, Path]:
    """A git root with the project at ``company/team_x`` and a sibling ``team_y``."""
    vcs = tmp_path / "mono"
    (vcs / ".git").mkdir(parents=True)
    project = vcs / "company" / "team_x"
    (project / "src").mkdir(parents=True)
    (vcs / "company" / "team_y").mkdir(parents=True)
    return project, vcs


def test_project_relative_paths_are_kept(monorepo):
    project, vcs = monorepo
    assert to_project_relative("foo.py", project, vcs) == ("foo.py", False)
    assert to_project_relative("./src/foo.py", project, vcs) == ("src/foo.py", False)


def test_vcs_root_relative_paths_lose_the_project_prefix(monorepo):
    project, vcs = monorepo
    assert to_project_relative("company/team_x/foo.py", project, vcs) == ("foo.py", False)


def test_absolute_paths_under_the_project_become_relative(monorepo):
    project, vcs = monorepo
    assert to_project_relative(str(project / "src" / "foo.py"), project, vcs) == (
        "src/foo.py",
        False,
    )


def test_sibling_folder_paths_are_foreign(monorepo):
    project, vcs = monorepo
    assert to_project_relative("company/team_y/bar.py", project, vcs) == (
        "company/team_y/bar.py",
        True,
    )
    outside = str(vcs.parent / "elsewhere" / "x.py")
    assert to_project_relative(outside, project, vcs) == (outside, True)


def test_project_at_vcs_root_keeps_relative_paths(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert to_project_relative("company/x.py", tmp_path, tmp_path) == ("company/x.py", False)
    assert to_project_relative("src/x.py", tmp_path, None) == ("src/x.py", False)


def test_collect_paths_merges_explicit_and_mentioned_paths(monorepo):
    project, _vcs = monorepo
    out = collect_paths(
        ["company/team_x/src/a.py", "src/a.py"],
        ["touches `src/b.py:12`", None, "and src/a.py again"],
        project_root=project,
    )
    assert out == ["src/a.py", "src/b.py"]


def test_collect_paths_without_a_root_only_cleans():
    assert collect_paths(["./src/a.py"], ["`src/b.py:3`"]) == ["src/a.py", "src/b.py"]


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph():
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    yield store
    store.close()


def _make_file(store: DuckPGQBackend, path: str) -> None:
    store.create_node(
        "File",
        {
            "id": f"file::{path}",
            "path": path,
            "language": "python",
            "size": 1,
            "lastModified": "0",
            "lineCount": 1,
            "contentHash": "h",
        },
    )


def _paths(store: DuckPGQBackend, table: str, node_id: str) -> list[str]:
    rows = store.query(f"SELECT paths FROM {table} WHERE id = '{node_id}'")
    return json.loads(rows[0]["paths"])


def _edges(store: DuckPGQBackend, finding_id: str) -> list[str]:
    rows = store.query(f"SELECT dst FROM FINDING_ABOUT_FILE WHERE src = '{finding_id}'")
    return sorted(r["dst"] for r in rows)


def test_a_path_without_a_file_node_is_stored_without_an_edge(graph):
    result = record_finding(
        graph,
        plan_number=281,
        review_type="devils_advocate",
        category="RISK",
        finding="The stamp is lost on reindex.",
        file_paths=["src/agentscaffold/review/queries.py"],
    )
    assert _paths(graph, "ReviewFinding", result["id"]) == ["src/agentscaffold/review/queries.py"]
    assert _edges(graph, result["id"]) == []


def test_a_path_with_a_file_node_is_stored_and_linked(graph):
    _make_file(graph, "src/a.py")
    result = record_finding(
        graph,
        plan_number=281,
        review_type="devils_advocate",
        category="RISK",
        finding="a.py is fragile.",
        file_paths=["src/a.py"],
    )
    assert _paths(graph, "ReviewFinding", result["id"]) == ["src/a.py"]
    assert _edges(graph, result["id"]) == ["file::src/a.py"]


def test_paths_mentioned_in_the_finding_and_evidence_are_captured(graph):
    _make_file(graph, "src/gate.py")
    result = record_finding(
        graph,
        plan_number=281,
        review_type="devils_advocate",
        category="RISK",
        finding="The strict gate in `src/gate.py:2062` reads the wrong column.",
        evidence="rg reviewedAt src/queries.py",
        evidence_kind="command",
    )
    assert _paths(graph, "ReviewFinding", result["id"]) == ["src/gate.py", "src/queries.py"]
    assert _edges(graph, result["id"]) == ["file::src/gate.py"]


def test_record_finding_normalizes_against_the_project_root(graph, monorepo):
    project, _vcs = monorepo
    result = record_finding(
        graph,
        plan_number=281,
        review_type="devils_advocate",
        category="RISK",
        finding="Monorepo path.",
        file_paths=["company/team_x/src/a.py", str(project / "src" / "b.py")],
        project_root=project,
    )
    assert _paths(graph, "ReviewFinding", result["id"]) == ["src/a.py", "src/b.py"]


def test_batch_findings_store_paths(graph):
    result = record_findings_batch(
        graph,
        plan_number=281,
        review_type="pre_review",
        findings=[
            {"category": "DEPENDENCY", "finding": "x", "file_paths": ["src/x.py"]},
            {"category": "RISK", "finding": "Touches `tests/test_y.py`."},
            {"category": "RISK", "finding": "No paths here."},
        ],
    )
    first, second, third = result["ids"]
    assert _paths(graph, "ReviewFinding", first) == ["src/x.py"]
    assert _paths(graph, "ReviewFinding", second) == ["tests/test_y.py"]
    assert _paths(graph, "ReviewFinding", third) == []


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_learnings_store_the_paths_they_mention(tmp_path: Path, graph):
    _write(
        tmp_path,
        "docs/ai/state/learnings_tracker.md",
        "| ID | Plan | Description | Target | Status |\n"
        "|----|------|-------------|--------|--------|\n"
        "| L281-1 | 281 | Edges keep first-insert properties in `src/graph/backend.py` | "
        "docs/ai/standards/testing.md | Pending |\n",
    )
    process_governance(graph, tmp_path)
    assert _paths(graph, "Learning", "learning::L281-1") == [
        "src/graph/backend.py",
        "docs/ai/standards/testing.md",
    ]


def test_plan_appendix_findings_store_the_paths_they_mention(tmp_path: Path, graph):
    _write(
        tmp_path,
        "docs/ai/plans/281-fixture.md",
        "# Plan 281\n\n## Appendix\n- [RISK] The gate in `src/server.py:2062` reads lost data.\n",
    )
    process_governance(graph, tmp_path)
    rows = graph.query("SELECT paths FROM ReviewFinding WHERE planNumber = 281")
    assert [json.loads(r["paths"]) for r in rows] == [["src/server.py"]]


def test_paths_travel_with_the_governance_export(graph):
    result = record_finding(
        graph,
        plan_number=281,
        review_type="devils_advocate",
        category="RISK",
        finding="Exported.",
        file_paths=["src/a.py"],
    )
    exported = graph.export_governance()["nodes"]["ReviewFinding"]
    row = next(r for r in exported["rows"] if r["id"] == result["id"])
    assert json.loads(row["paths"]) == ["src/a.py"]


def test_paths_column_defaults_to_an_empty_list(graph):
    graph.execute(
        "INSERT INTO ReviewFinding (id, reviewType, planNumber, severity, category, finding,"
        " resolution, status) VALUES ('rf::legacy', 'x', 1, 'low', 'RISK', 'f', '', 'open')"
    )
    assert _paths(graph, "ReviewFinding", "rf::legacy") == []
