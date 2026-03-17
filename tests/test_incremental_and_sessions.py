"""Tests for Phase 6: Incremental indexing, cross-session memory, language support.

Tests cover:
- Changeset computation (added/modified/deleted detection)
- File node removal cascading (functions, classes, methods, edges)
- Incremental pipeline (re-index only changed files)
- Session start/end/list/context lifecycle
- Session modification tracking
- Extended language grammar registration
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def graph_with_repo(tmp_path):
    """Create a mutable copy of sample_repo and index it."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)

    db_path = tmp_path / "graph.db"

    from agentscaffold.config import GraphConfig, ScaffoldConfig

    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path))

    run_pipeline(repo, config)
    store = DuckPGQBackend(db_path)
    yield store, config, repo
    store.close()


# ---------------------------------------------------------------------------
# Incremental indexing tests
# ---------------------------------------------------------------------------


class TestComputeChangeset:
    """Test changeset computation between disk and graph."""

    def test_no_changes(self, graph_with_repo):
        store, config, repo = graph_with_repo

        from agentscaffold.graph.incremental import compute_changeset

        cs = compute_changeset(store, repo, config.graph)
        assert cs["added"] == []
        assert cs["modified"] == []
        assert cs["deleted"] == []
        assert cs["unchanged"] > 0

    def test_detects_new_file(self, graph_with_repo):
        store, config, repo = graph_with_repo

        (repo / "new_module.py").write_text("def hello(): pass\n")

        from agentscaffold.graph.incremental import compute_changeset

        cs = compute_changeset(store, repo, config.graph)
        assert "new_module.py" in cs["added"]

    def test_detects_modified_file(self, graph_with_repo):
        store, config, repo = graph_with_repo

        # Modify an existing file
        target = next(repo.rglob("*.py"))
        original = target.read_text()
        target.write_text(original + "\n# modified\n")

        from agentscaffold.graph.incremental import compute_changeset

        cs = compute_changeset(store, repo, config.graph)
        rel = str(target.relative_to(repo))
        assert rel in cs["modified"]

    def test_detects_deleted_file(self, graph_with_repo):
        store, config, repo = graph_with_repo

        # Delete a file that's in the graph
        target = next(repo.rglob("*.py"))
        rel = str(target.relative_to(repo))
        target.unlink()

        from agentscaffold.graph.incremental import compute_changeset

        cs = compute_changeset(store, repo, config.graph)
        assert rel in cs["deleted"]


class TestRemoveFileNodes:
    """Test cascading removal of file nodes."""

    def test_removes_file_and_definitions(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        files = store.query(
            'SELECT DISTINCT t.f_path AS "f.path" '
            "FROM GRAPH_TABLE(agentscaffold_graph "
            "MATCH (f:File)-[e:DEFINES_FUNCTION]->(fn:Function) "
            "COLUMNS (f.path AS f_path)) t LIMIT 1"
        )
        if not files:
            pytest.skip("No files with functions in fixture")

        target_path = files[0]["f.path"]
        file_id = f"file::{target_path}"

        func_count_before = store.query_scalar(
            f"SELECT COUNT(*) FROM GRAPH_TABLE(agentscaffold_graph "
            f"MATCH (f:File)-[e:DEFINES_FUNCTION]->(fn:Function) "
            f"WHERE f.id = '{file_id}' "
            f"COLUMNS (fn.id AS fn_id)) t"
        )

        from agentscaffold.graph.incremental import remove_file_nodes

        removed = remove_file_nodes(store, [target_path])
        assert removed == 1

        # File should be gone
        remaining = store.query_scalar(f"SELECT COUNT(*) FROM File WHERE id = '{file_id}'")
        assert int(remaining) == 0

        # Functions should also be gone
        func_count_after = store.query_scalar(
            f"SELECT COUNT(*) FROM Function WHERE filePath = '{target_path}'"
        )
        assert int(func_count_after) == 0
        assert int(func_count_before) > 0


class TestAddFileNode:
    """Test adding new file nodes."""

    def test_add_new_file(self, graph_with_repo):
        store, _config, repo = graph_with_repo

        new_file = repo / "brand_new.py"
        new_file.write_text("def fresh(): return True\n")

        from agentscaffold.graph.incremental import add_file_node

        result = add_file_node(store, repo, "brand_new.py")
        assert result is True

        rows = store.query("SELECT id AS \"f.id\" FROM File WHERE path = 'brand_new.py'")
        assert len(rows) == 1

    def test_add_nonexistent_file(self, graph_with_repo):
        store, _config, repo = graph_with_repo

        from agentscaffold.graph.incremental import add_file_node

        result = add_file_node(store, repo, "does_not_exist.py")
        assert result is False


class TestIncrementalPipeline:
    """Test incremental pipeline end-to-end."""

    def test_incremental_no_changes(self, graph_with_repo):
        store, config, repo = graph_with_repo
        store.close()

        summary = run_pipeline(repo, config, incremental=True)
        assert "changeset" in summary
        cs = summary["changeset"]
        assert cs["added"] == []
        assert cs["modified"] == []

    def test_incremental_with_new_file(self, graph_with_repo):
        store, config, repo = graph_with_repo
        store.close()

        (repo / "incremental_new.py").write_text("def inc(): return 1\n")

        summary = run_pipeline(repo, config, incremental=True)
        cs = summary["changeset"]
        assert "incremental_new.py" in cs["added"]


# ---------------------------------------------------------------------------
# Session memory tests
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Test session start/end/list lifecycle."""

    def test_start_session(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import start_session

        session_id = start_session(store, plan_numbers=[42], summary="test session")
        assert session_id.startswith("session::")

    def test_get_session(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import get_session, start_session

        sid = start_session(store, plan_numbers=[1, 2], summary="hello")
        data = get_session(store, sid)

        assert data["id"] == sid
        assert data["plan_numbers"] == [1, 2]
        assert data["summary"] == "hello"
        assert data["date"]

    def test_end_session(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import end_session, start_session

        sid = start_session(store)
        result = end_session(store, sid, summary="completed work")

        assert result["summary"] == "completed work"

    def test_list_sessions(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import list_sessions, start_session

        start_session(store, summary="session A")
        start_session(store, summary="session B")

        sessions = list_sessions(store, limit=5)
        assert len(sessions) >= 2

    def test_record_modification(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import (
            get_session,
            record_modification,
            start_session,
        )

        sid = start_session(store)

        # Get a file that exists in the graph
        files = store.query('SELECT path AS "f.path" FROM File LIMIT 1')
        if not files:
            pytest.skip("No files in graph")

        file_path = files[0]["f.path"]
        record_modification(store, sid, file_path)

        data = get_session(store, sid)
        assert file_path in data["files_modified"]

    def test_record_modification_idempotent(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import (
            get_session,
            record_modification,
            start_session,
        )

        sid = start_session(store)
        files = store.query('SELECT path AS "f.path" FROM File LIMIT 1')
        if not files:
            pytest.skip("No files in graph")

        file_path = files[0]["f.path"]
        record_modification(store, sid, file_path)
        record_modification(store, sid, file_path)

        data = get_session(store, sid)
        assert data["files_modified"].count(file_path) == 1


class TestSessionContext:
    """Test cross-session context generation."""

    def test_session_context(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import (
            get_session_context,
            record_modification,
            start_session,
        )

        sid = start_session(store, plan_numbers=[10], summary="working on plan 10")
        files = store.query('SELECT path AS "f.path" FROM File LIMIT 2')
        for f in files:
            record_modification(store, sid, f["f.path"])

        ctx = get_session_context(store)
        assert "recent_sessions" in ctx
        assert ctx["session_count"] >= 1
        assert 10 in ctx["recent_plan_numbers"]

    def test_session_context_empty(self, tmp_path):
        db_path = tmp_path / "empty.db"
        store = DuckPGQBackend(db_path)
        store.init_schema()

        from agentscaffold.graph.sessions import get_session_context

        ctx = get_session_context(store)
        assert ctx == {}
        store.close()

    def test_format_session_markdown(self, graph_with_repo):
        store, _config, _repo = graph_with_repo

        from agentscaffold.graph.sessions import (
            format_session_context_markdown,
            get_session_context,
            start_session,
        )

        start_session(store, plan_numbers=[5], summary="test md")
        ctx = get_session_context(store)
        md = format_session_context_markdown(ctx)
        assert "Recent Session Context" in md

    def test_format_empty_context(self):
        from agentscaffold.graph.sessions import format_session_context_markdown

        assert format_session_context_markdown({}) == ""


# ---------------------------------------------------------------------------
# Language support tests
# ---------------------------------------------------------------------------


class TestLanguageSupport:
    """Test that all expected languages are registered."""

    def test_supported_languages(self):
        from agentscaffold.graph.queries import supported_languages

        langs = supported_languages()
        assert "python" in langs
        assert "typescript" in langs
        assert "javascript" in langs
        assert "go" in langs
        assert "rust" in langs
        assert "java" in langs
        assert "c" in langs
        assert "cpp" in langs

    def test_go_queries_registered(self):
        from agentscaffold.graph.queries import get_queries

        q = get_queries("go")
        assert q is not None
        assert "functions" in q
        assert "classes" in q
        assert "methods" in q
        assert "interfaces" in q

    def test_rust_queries_registered(self):
        from agentscaffold.graph.queries import get_queries

        q = get_queries("rust")
        assert q is not None
        assert "functions" in q
        assert "classes" in q
        assert "methods" in q
        assert "interfaces" in q

    def test_java_queries_registered(self):
        from agentscaffold.graph.queries import get_queries

        q = get_queries("java")
        assert q is not None
        assert "classes" in q
        assert "methods" in q
        assert "interfaces" in q

    def test_c_queries_registered(self):
        from agentscaffold.graph.queries import get_queries

        q = get_queries("c")
        assert q is not None
        assert "functions" in q
        assert "classes" in q

    def test_cpp_queries_registered(self):
        from agentscaffold.graph.queries import get_queries

        q = get_queries("cpp")
        assert q is not None
        assert "functions" in q
        assert "classes" in q
        assert "methods" in q

    def test_grammar_module_registry(self):
        from agentscaffold.graph.parsing import _GRAMMAR_MODULES

        assert "go" in _GRAMMAR_MODULES
        assert "rust" in _GRAMMAR_MODULES
        assert "java" in _GRAMMAR_MODULES
        assert "c" in _GRAMMAR_MODULES
        assert "cpp" in _GRAMMAR_MODULES
