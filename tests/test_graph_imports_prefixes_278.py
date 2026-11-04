"""Plan 278: monorepo-absolute Python imports resolve inside the project.

A project folder at ``<git>/company/team_x/`` is imported as
``company.team_x.foo``. The resolver probed ``company/team_x/foo.py`` under the
project root, which does not exist, so every such import was unresolved and
impact and caller queries came back empty. The project's path from its VCS
root is now inferred as a module prefix and stripped before probing. The
strategy that resolved each import is recorded on its IMPORTS edge, so the
coverage report can show the prefix doing work.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.imports import _python_module_to_path
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.graph.source_roots import effective_module_prefixes, infer_module_prefix
from agentscaffold.mcp.coverage import repo_coverage

PREFIX = {"company.team_x": "."}


def _write(path: Path, text: str = "def f():\n    return 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture()
def monorepo(tmp_path: Path) -> Path:
    """``<git>/company/team_x`` with a module, a package and a namespace dir.

    team_x/foo.py
    team_x/pkg/__init__.py
    team_x/ns/mod.py          <- no __init__.py in ns
    team_x/bar.py             <- imports all three by their monorepo name
    """
    repo = tmp_path / "mono"
    (repo / ".git").mkdir(parents=True)
    project = repo / "company" / "team_x"
    _write(project / "foo.py", "def foo():\n    return 1\n")
    _write(project / "pkg" / "__init__.py", "def pkg_fn():\n    return 1\n")
    _write(project / "ns" / "mod.py", "def mod_fn():\n    return 1\n")
    _write(
        project / "bar.py",
        "from company.team_x.foo import foo\n"
        "import company.team_x.pkg\n"
        "from company.team_x.ns.mod import mod_fn\n\n\n"
        "def use():\n    return foo() + mod_fn()\n",
    )
    return project


def _config(tmp_path: Path, **graph: object) -> ScaffoldConfig:
    config = ScaffoldConfig()
    config.graph = GraphConfig(db_path=str(tmp_path / "graph.duckdb"), **graph)
    return config


def _imports(db: Path) -> dict[tuple[str, str], str]:
    store = DuckPGQBackend(db)
    try:
        rows = store.query("SELECT src, dst, strategy FROM IMPORTS")
    finally:
        store.close()
    return {(r["src"], r["dst"]): r["strategy"] for r in rows}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def test_project_below_its_vcs_root_infers_its_dotted_path(monorepo: Path):
    assert infer_module_prefix(monorepo) == "company.team_x"


def test_project_at_its_vcs_root_infers_nothing(tmp_path: Path):
    (tmp_path / "solo" / ".git").mkdir(parents=True)
    assert infer_module_prefix(tmp_path / "solo") is None


def test_no_vcs_root_infers_nothing(tmp_path: Path):
    (tmp_path / "plain" / "team_x").mkdir(parents=True)
    assert infer_module_prefix(tmp_path / "plain" / "team_x") is None


@pytest.mark.parametrize("segment", ["team-x", "class", "2fast"])
def test_a_segment_that_is_not_an_identifier_disables_inference(tmp_path: Path, segment: str):
    repo = tmp_path / "mono"
    (repo / ".git").mkdir(parents=True)
    (repo / "company" / segment).mkdir(parents=True)
    assert infer_module_prefix(repo / "company" / segment) is None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_default_config_uses_the_inferred_prefix(monorepo: Path):
    assert effective_module_prefixes(monorepo, GraphConfig()) == {"company.team_x": "."}


def test_explicit_entries_are_added_to_the_inferred_one(monorepo: Path):
    config = GraphConfig(module_prefixes={"team_x": "."})
    assert effective_module_prefixes(monorepo, config) == {"company.team_x": ".", "team_x": "."}


def test_inference_can_be_turned_off(monorepo: Path):
    config = GraphConfig(infer_module_prefix=False, module_prefixes={"team_x": "."})
    assert effective_module_prefixes(monorepo, config) == {"team_x": "."}


def test_an_explicit_entry_wins_over_the_inferred_one(monorepo: Path):
    config = GraphConfig(module_prefixes={"company.team_x": "src"})
    assert effective_module_prefixes(monorepo, config) == {"company.team_x": "src"}


@pytest.mark.parametrize(
    "mapping",
    [{"team-x": "."}, {"team_x.": "."}, {"team_x": "../other"}, {"team_x": "/abs"}],
)
def test_invalid_prefix_mappings_are_rejected(mapping: dict[str, str]):
    with pytest.raises(ValidationError):
        GraphConfig(module_prefixes=mapping)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_a_module_under_the_prefix_resolves(monorepo: Path):
    assert _python_module_to_path("company.team_x.foo", "bar.py", monorepo, prefixes=PREFIX) == (
        "foo.py"
    )


def test_a_package_under_the_prefix_resolves_to_its_init(monorepo: Path):
    assert _python_module_to_path("company.team_x.pkg", "bar.py", monorepo, prefixes=PREFIX) == (
        "pkg/__init__.py"
    )


def test_a_namespace_directory_without_init_still_resolves(monorepo: Path):
    assert (
        _python_module_to_path("company.team_x.ns.mod", "bar.py", monorepo, prefixes=PREFIX)
        == "ns/mod.py"
    )


def test_the_prefix_itself_resolves_to_the_root_package(monorepo: Path):
    assert _python_module_to_path("company.team_x", "bar.py", monorepo, prefixes=PREFIX) is None
    _write(monorepo / "__init__.py", "")
    assert _python_module_to_path("company.team_x", "bar.py", monorepo, prefixes=PREFIX) == (
        "__init__.py"
    )


def test_without_prefixes_the_import_stays_unresolved(monorepo: Path):
    assert _python_module_to_path("company.team_x.foo", "bar.py", monorepo) is None


def test_a_prefix_mapped_to_a_subdirectory(monorepo: Path):
    _write(monorepo / "src" / "core.py")
    assert _python_module_to_path(
        "team_x.core", "bar.py", monorepo, prefixes={"team_x": "src"}
    ) == ("src/core.py")


def test_the_longest_matching_prefix_wins(monorepo: Path):
    prefixes = {"company": "vendor", "company.team_x": "."}
    assert _python_module_to_path("company.team_x.foo", "bar.py", monorepo, prefixes=prefixes) == (
        "foo.py"
    )


def test_a_prefix_only_matches_whole_segments(monorepo: Path):
    _write(monorepo / "x" / "foo.py")
    assert (
        _python_module_to_path("company.team_xx.foo", "bar.py", monorepo, prefixes=PREFIX) is None
    )


def test_an_existing_direct_match_is_not_displaced(monorepo: Path):
    """A file that really sits at company/team_x/foo.py under the root keeps winning."""
    _write(monorepo / "company" / "team_x" / "foo.py")
    assert _python_module_to_path("company.team_x.foo", "bar.py", monorepo, prefixes=PREFIX) == (
        "company/team_x/foo.py"
    )


# ---------------------------------------------------------------------------
# Pipeline: edges, strategy, both paths
# ---------------------------------------------------------------------------


def test_full_index_creates_prefix_edges(monorepo: Path, tmp_path: Path):
    config = _config(tmp_path)
    run_pipeline(monorepo, config, quiet=True)

    edges = _imports(tmp_path / "graph.duckdb")
    assert edges[("file::bar.py", "file::foo.py")] == "prefix"
    assert edges[("file::bar.py", "file::pkg/__init__.py")] == "prefix"
    assert edges[("file::bar.py", "file::ns/mod.py")] == "prefix"


def test_inference_off_creates_no_prefix_edges(monorepo: Path, tmp_path: Path):
    config = _config(tmp_path, infer_module_prefix=False)
    run_pipeline(monorepo, config, quiet=True)

    assert ("file::bar.py", "file::foo.py") not in _imports(tmp_path / "graph.duckdb")


def test_incremental_reindex_keeps_prefix_edges(monorepo: Path, tmp_path: Path):
    """The incremental path deletes the file's edges first; it must re-resolve with prefixes."""
    config = _config(tmp_path)
    run_pipeline(monorepo, config, quiet=True)

    bar = monorepo / "bar.py"
    bar.write_text(bar.read_text() + "\n\ndef more():\n    return 2\n")
    run_pipeline(monorepo, config, incremental=True, quiet=True)

    edges = _imports(tmp_path / "graph.duckdb")
    assert edges[("file::bar.py", "file::foo.py")] == "prefix"


def test_a_lone_repo_records_the_direct_strategy(tmp_path: Path):
    repo = tmp_path / "solo"
    (repo / ".git").mkdir(parents=True)
    _write(repo / "core.py", "def core_fn():\n    return 1\n")
    _write(repo / "app.py", "from core import core_fn\n\n\ndef use():\n    return core_fn()\n")

    run_pipeline(repo, _config(tmp_path), quiet=True)

    edges = _imports(tmp_path / "graph.duckdb")
    assert edges == {("file::app.py", "file::core.py"): "direct"}


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_coverage_counts_imports_per_strategy(monorepo: Path, tmp_path: Path):
    run_pipeline(monorepo, _config(tmp_path), quiet=True)

    store = DuckPGQBackend(tmp_path / "graph.duckdb")
    try:
        cov = repo_coverage(store)
    finally:
        store.close()

    assert cov["import_strategies"]["prefix"] == 3
    assert "module prefix" in cov["summary"]


def test_an_upgraded_graph_reports_old_edges_as_unrecorded(tmp_path: Path):
    """A graph built before Plan 278 gains the column on open; its edges have no strategy."""
    db = tmp_path / "graph.duckdb"
    store = DuckPGQBackend(db)
    try:
        store.init_schema()
        store.execute("ALTER TABLE IMPORTS DROP COLUMN strategy")
        for name in ("a", "b"):
            store.create_node(
                "File", {"id": f"file::{name}.py", "path": f"{name}.py", "language": "python"}
            )
        store.create_edge(
            "IMPORTS", "File", "file::a.py", "File", "file::b.py", {"importedNames": "x"}
        )
    finally:
        store.close()

    store = DuckPGQBackend(db)
    try:
        cov = repo_coverage(store)
    finally:
        store.close()

    assert cov["import_strategies"] == {"unrecorded": 1}
    assert "module prefix" not in cov["summary"]
