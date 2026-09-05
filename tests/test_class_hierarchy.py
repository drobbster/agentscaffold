"""Plan 262: Python EXTENDS population, resolution, and context."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.mcp.render import format_context_markdown
from agentscaffold.mcp.server import _tool_context

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "hierarchy_repo"

try:
    import tree_sitter  # noqa: F401

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

pytestmark = pytest.mark.skipif(not HAS_TREE_SITTER, reason="tree-sitter required")


@pytest.fixture()
def hierarchy_graph(tmp_path: Path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    db_path = tmp_path / "graph.duckdb"
    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(db_path), backend="duckpgq")
    run_pipeline(root=repo, config=config)
    store = DuckPGQBackend(db_path)
    yield repo, store, config
    store.close()


def _class_id(store: DuckPGQBackend, name: str, file_path: str | None = None) -> str:
    if file_path is None:
        rows = store.query("SELECT id FROM Class WHERE name = ?", {"name": name})
    else:
        rows = store.query(
            "SELECT id FROM Class WHERE name = ? AND filePath = ?",
            {"name": name, "filePath": file_path},
        )
    assert rows, f"missing Class {name} {file_path or ''}"
    return rows[0]["id"]


def _bases(store: DuckPGQBackend, name: str, file_path: str | None = None) -> list[dict]:
    return store.query(
        "SELECT e.resolved AS resolved, e.baseName AS baseName, e.dst AS dst "
        "FROM EXTENDS e JOIN Class c ON c.id = e.src "
        "WHERE c.name = ?" + (" AND c.filePath = ?" if file_path else ""),
        {"name": name, "filePath": file_path} if file_path else {"name": name},
    )


class TestExtraction:
    def test_extends_nonzero_regression_guard(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        assert store.edge_count("EXTENDS") > 0

    def test_implements_stays_empty(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        assert store.edge_count("IMPLEMENTS") == 0

    def test_no_bases(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        assert _bases(store, "Lonely") == []
        assert _bases(store, "Alpha") == []

    def test_single_and_cross_module_resolution(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        rows = _bases(store, "Beta")
        assert len(rows) == 1
        assert rows[0]["dst"] == _class_id(store, "Alpha")
        assert rows[0]["baseName"] == "Alpha"
        assert bool(rows[0]["resolved"]) or "class::" in rows[0]["dst"]

    def test_multiple_inheritance(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        names = {row["baseName"] for row in _bases(store, "Both")}
        assert names == {"Left", "Right"}
        assert all("class::" in row["dst"] for row in _bases(store, "Both"))

    def test_external_base_unresolved(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        rows = _bases(store, "Model")
        assert len(rows) == 1
        assert rows[0]["resolved"] is False
        assert rows[0]["baseName"] == "pydantic.BaseModel"
        assert "external::" in rows[0]["dst"]

    def test_enum_unresolved(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        rows = _bases(store, "Enumish")
        assert len(rows) == 1
        assert rows[0]["resolved"] is False
        assert rows[0]["baseName"] == "Enum"

    def test_aliased_from_import(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        rows = _bases(store, "Aliased")
        assert len(rows) == 1
        assert rows[0]["dst"] == _class_id(store, "Alpha")

    def test_metaclass_is_not_a_base(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        rows = _bases(store, "Foo", "pkg/meta.py")
        assert {row["baseName"] for row in rows} == {"Bar"}
        assert "class::" in rows[0]["dst"]

    def test_generic_subscript_unresolved_bar_resolved(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        rows = _bases(store, "Foo", "pkg/generic.py")
        by_name = {row["baseName"]: row for row in rows}
        assert "Generic[T]" in by_name
        assert by_name["Generic[T]"]["resolved"] is False
        assert "class::" in by_name["Bar"]["dst"]
        assert by_name["Bar"]["dst"] != _class_id(store, "Bar", "pkg/meta.py")

    def test_dynamic_and_starred_unresolved(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        dyn = _bases(store, "Dynamic")
        assert len(dyn) == 1
        assert dyn[0]["resolved"] is False
        assert dyn[0]["baseName"] == "make_base()"
        star = _bases(store, "Starred")
        assert len(star) == 1
        assert star[0]["resolved"] is False
        assert star[0]["baseName"].startswith("*")

    def test_ambiguous_name_stays_unresolved(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        rows = _bases(store, "User")
        assert len(rows) == 1
        assert rows[0]["resolved"] is False
        assert rows[0]["baseName"] == "Config"


class TestTransitiveAndContext:
    def test_transitive_descendants(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        alpha = _class_id(store, "Alpha")
        subs = store.query_class_subclasses(alpha)
        names = {row["name"]: row["depth"] for row in subs}
        assert names["Beta"] == 1
        assert names["Gamma"] == 2
        assert "Aliased" in names

    def test_graph_table_omits_unresolved(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        sql_unresolved = store.query_scalar(
            "SELECT count(*) FROM EXTENDS WHERE dst LIKE '%external::%'"
        )
        assert int(sql_unresolved) > 0
        graph_rows = store.query(
            "SELECT count(*) AS n FROM GRAPH_TABLE(agentscaffold_graph "
            "MATCH (a:Class)-[e:EXTENDS]->(b:Class) "
            "COLUMNS (a.id AS id)) t"
        )
        sql_resolved = store.query_scalar("SELECT count(*) FROM EXTENDS WHERE dst LIKE '%class::%'")
        assert graph_rows[0]["n"] == sql_resolved

    def test_context_includes_bases_and_subclasses(self, hierarchy_graph):
        _repo, store, _config = hierarchy_graph
        result = _tool_context(store, {"symbol": "Alpha"}, {})
        assert result["bases"] == []
        names = {row["name"] for row in result["subclasses"]}
        assert {"Beta", "Gamma"} <= names
        assert "Bases" not in result["markdown"] or "### Bases (0)" not in result["markdown"]
        assert "Subclasses" in result["markdown"]

    def test_context_markdown_unresolved_base(self):
        md = format_context_markdown(
            {"name": "Model", "filePath": "pkg/external.py", "startLine": 1},
            callers=[],
            callees=[],
            bases=[
                {
                    "name": "pydantic.BaseModel",
                    "resolved": False,
                    "filePath": "",
                }
            ],
            subclasses=[],
        )
        assert "pydantic.BaseModel" in md
        assert "unresolved" in md
