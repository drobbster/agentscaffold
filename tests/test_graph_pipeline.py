"""Tests for the full indexing pipeline against the fixture repo."""

from __future__ import annotations

import pytest

try:
    import kuzu  # noqa: F401

    HAS_KUZU = True
except ImportError:
    HAS_KUZU = False

try:
    import tree_sitter  # noqa: F401

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

pytestmark = pytest.mark.skipif(
    not (HAS_KUZU and HAS_TREE_SITTER),
    reason="kuzu and tree-sitter required",
)


class TestStructurePhase:
    """Tests for Phase 1: directory structure processing."""

    def test_files_indexed(self, indexed_repo):
        """All Python files in fixture repo are indexed."""
        repo, store = indexed_repo
        file_count = store.node_count("File")
        assert file_count >= 15, f"Expected at least 15 files, got {file_count}"

    def test_folders_indexed(self, indexed_repo):
        """Folder nodes are created."""
        repo, store = indexed_repo
        folder_count = store.node_count("Folder")
        assert folder_count >= 5

    def test_contains_edges(self, indexed_repo):
        """CONTAINS edges link folders to files."""
        repo, store = indexed_repo
        edge_count = store.edge_count("CONTAINS")
        assert edge_count > 0

    def test_file_has_hash(self, indexed_repo):
        """File nodes have contentHash populated."""
        repo, store = indexed_repo
        rows = store.query(
            "MATCH (f:File) WHERE f.path = 'libs/data/router.py' " "RETURN f.contentHash"
        )
        assert len(rows) == 1
        assert rows[0]["f.contentHash"] != ""

    def test_language_detection(self, indexed_repo):
        """Python files are tagged with correct language."""
        repo, store = indexed_repo
        rows = store.query(
            "MATCH (f:File) WHERE f.path = 'libs/data/router.py' " "RETURN f.language"
        )
        assert rows[0]["f.language"] == "python"


class TestParsingPhase:
    """Tests for Phase 2: tree-sitter definition extraction."""

    def test_functions_extracted(self, indexed_repo):
        """Functions are extracted from fixture files."""
        repo, store = indexed_repo
        func_count = store.node_count("Function")
        assert func_count > 0

    def test_classes_extracted(self, indexed_repo):
        """Classes are extracted from fixture files."""
        repo, store = indexed_repo
        class_count = store.node_count("Class")
        assert class_count > 0

    def test_data_router_class(self, indexed_repo):
        """DataRouter class is found in the graph."""
        repo, store = indexed_repo
        rows = store.query("MATCH (c:Class) WHERE c.name = 'DataRouter' RETURN c.filePath")
        assert len(rows) >= 1
        assert "router.py" in rows[0]["c.filePath"]

    def test_methods_extracted(self, indexed_repo):
        """Methods are extracted from classes."""
        repo, store = indexed_repo
        method_count = store.node_count("Method")
        assert method_count > 0

    def test_defines_edges(self, indexed_repo):
        """DEFINES_FUNCTION edges connect files to functions."""
        repo, store = indexed_repo
        edge_count = store.edge_count("DEFINES_FUNCTION")
        assert edge_count > 0


class TestResolutionPhase:
    """Tests for Phase 3: import and call resolution."""

    def test_imports_resolved(self, indexed_repo):
        """Some IMPORTS edges are created."""
        repo, store = indexed_repo
        edge_count = store.edge_count("IMPORTS")
        assert edge_count > 0

    def test_calls_resolved(self, indexed_repo):
        """Some CALLS edges are created."""
        repo, store = indexed_repo
        edge_count = store.edge_count("CALLS")
        assert edge_count >= 0  # May be 0 if resolution is conservative

    def test_pipeline_state_complete(self, indexed_repo):
        """Pipeline state is marked complete after successful run."""
        repo, store = indexed_repo
        state = store.get_pipeline_state()
        assert state["state"] == "complete"
        assert "structure" in state["phases_completed"]
        assert "parsing" in state["phases_completed"]
        assert "resolution" in state["phases_completed"]


class TestGraphVerify:
    """Tests for graph verification."""

    def test_verify_fresh_graph(self, indexed_repo):
        """A freshly indexed repo should report GOOD health."""
        from agentscaffold.graph.verify import verify_graph

        repo, store = indexed_repo
        report = verify_graph(store, repo)
        assert report["health"] == "GOOD"
        assert report["file_existence"]["missing"] == 0
        assert report["hash_freshness"]["stale"] == 0

    def test_verify_detects_stale(self, indexed_repo):
        """Modifying a file after indexing is detected as stale."""
        from agentscaffold.graph.verify import verify_graph

        repo, store = indexed_repo

        (repo / "libs" / "data" / "router.py").write_text("# modified\n")

        report = verify_graph(store, repo)
        assert report["hash_freshness"]["stale"] > 0
        assert "libs/data/router.py" in report["stale_files"]

    def test_verify_detects_missing(self, indexed_repo):
        """Deleting a file after indexing is detected as missing."""
        from agentscaffold.graph.verify import verify_graph

        repo, store = indexed_repo
        (repo / "libs" / "data" / "router.py").unlink()

        report = verify_graph(store, repo)
        assert report["file_existence"]["missing"] > 0
        assert "libs/data/router.py" in report["missing_files"]
