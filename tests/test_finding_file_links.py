"""Tests for finding-to-file linking (Plan 213, Item 1).

`begin_plan`/`complete_plan` auto-record review findings. For the [PATTERN]
recurring-finding detector (challenges._check_patterns) to ever fire, those
findings must be linked to File nodes via FINDING_ABOUT_FILE edges. This wires
file paths extracted from challenge/gap evidence into record_findings_batch.
"""

from __future__ import annotations

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.findings import record_findings_batch
from agentscaffold.mcp.server import _finding_file_paths


class TestFindingFilePathsExtractor:
    def test_single_file_key(self):
        assert _finding_file_paths({"file": "libs/a.py"}) == ["libs/a.py"]

    def test_dict_keyed_evidence(self):
        out = _finding_file_paths({"files": {"libs/a.py": ["x"], "libs/b.py": ["y"]}})
        assert set(out) == {"libs/a.py", "libs/b.py"}

    def test_missing_test_files_list(self):
        out = _finding_file_paths({"missing_test_files": ["libs/a.py", "libs/b.py"]})
        assert out == ["libs/a.py", "libs/b.py"]

    def test_unlisted_consumers(self):
        out = _finding_file_paths(
            {"unlisted_consumers": [{"path": "libs/a.py", "layer": 3}, {"path": "libs/b.py"}]}
        )
        assert out == ["libs/a.py", "libs/b.py"]

    def test_dedupe_and_cap(self):
        out = _finding_file_paths({"file": "libs/a.py", "files": {"libs/a.py": 1}})
        assert out == ["libs/a.py"]

    def test_non_dict_returns_empty(self):
        assert _finding_file_paths(None) == []
        assert _finding_file_paths("not a dict") == []
        assert _finding_file_paths({}) == []


@pytest.fixture()
def graph():
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    yield store
    store.close()


def _make_file(store, path: str) -> None:
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


class TestFindingFileLinking:
    def test_findings_create_finding_about_file_edges(self, graph):
        _make_file(graph, "libs/regime/router.py")

        result = record_findings_batch(
            graph,
            plan_number=700,
            review_type="pre_review",
            findings=[
                {
                    "category": "DEPENDENCY",
                    "finding": "router.py has many importers.",
                    "severity": "high",
                    "file_paths": ["libs/regime/router.py"],
                }
            ],
        )
        assert result["count"] == 1

        edge_rows = graph.query("SELECT count(*) AS c FROM FINDING_ABOUT_FILE")
        assert edge_rows[0]["c"] == 1

    def test_pattern_detector_query_sees_accumulated_findings(self, graph):
        """The exact traversal _check_patterns uses must return linked findings."""
        _make_file(graph, "libs/regime/router.py")

        for i in range(2):
            record_findings_batch(
                graph,
                plan_number=700 + i,
                review_type="pre_review",
                findings=[
                    {
                        "category": "DEPENDENCY",
                        "finding": f"finding number {i} about router.",
                        "severity": "medium",
                        "file_paths": ["libs/regime/router.py"],
                    }
                ],
            )

        rows = graph.query(
            "SELECT t.rf_category AS rf_category"
            " FROM GRAPH_TABLE(agentscaffold_graph"
            "   MATCH (rf:ReviewFinding)-[e:FINDING_ABOUT_FILE]->(f:File)"
            "   WHERE f.id = 'file::libs/regime/router.py'"
            "   COLUMNS (rf.category AS rf_category)) t"
        )
        # Two findings on the same file -> _check_patterns would emit a PATTERN.
        assert len(rows) >= 2
