"""Index project files that live outside the project folder.

A team's Airflow DAGs live at ``<git>/airflow/dags/team_x/`` while the project
is ``<git>/company/team_x/``. ``graph.extra_paths`` lists globs, relative to
the VCS root, of such files. They are indexed as ``file::@repo/<vcs-relative
path>``, and every consumer turns that path into a file through
``paths.resolve_node_path``, so a consumer that joins ``root / path`` instead
finds nothing rather than reading outside the repository.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentscaffold.config import load_config
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.pipeline import run_pipeline
from agentscaffold.graph.source_roots import scan_extra_paths
from agentscaffold.paths import resolve_node_path
from agentscaffold.repo_paths import (
    REPO_PREFIX,
    compile_extra_glob,
    extra_glob_problem,
    path_spellings,
    repo_node_path,
)
from agentscaffold.workspace_registry import register_workspace

pytest.importorskip("duckdb", reason="duckdb not installed")

GLOB = "airflow/dags/team_x/**/*.py"
DAG = "@repo/airflow/dags/team_x/dag.py"
TASK = "@repo/airflow/dags/team_x/sub/task.py"


def _write(path: Path, text: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _config_text(db: Path, *, extra: list[str] | None = None, read_only: str = "") -> str:
    graph: dict[str, Any] = {"db_path": str(db), "embeddings": False}
    if extra is not None:
        graph["extra_paths"] = extra
    doc: dict[str, Any] = {"graph": graph}
    if read_only:
        doc["agents"] = {"agents_md": False, "protect_read_only_paths": True}
        doc["semi_autonomous"] = {"safety": {"read_only_paths": [read_only]}}
    return yaml.safe_dump(doc)


@pytest.fixture()
def mono(tmp_path: Path) -> Path:
    """``<git>/company/team_x`` plus DAGs at ``<git>/airflow/dags/team_x``.

    Returns the project root. ``ignored.py`` is ignored at the VCS root and
    ``team_y/other.py`` does not match the glob.
    """
    repo = (tmp_path / "mono").resolve()
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text("airflow/dags/team_x/ignored.py\n")
    project = repo / "company" / "team_x"
    _write(project / "scaffold.yaml", _config_text(tmp_path / "graph.duckdb", extra=[GLOB]))
    _write(project / "foo.py", "def helper():\n    return 1\n")
    _write(
        repo / "airflow" / "dags" / "team_x" / "dag.py",
        '"""Team X nightly DAG."""\n'
        "from company.team_x.foo import helper\n\n\n"
        "def run():\n    return helper()\n",
    )
    _write(repo / "airflow" / "dags" / "team_x" / "sub" / "task.py", "def task():\n    return 2\n")
    _write(repo / "airflow" / "dags" / "team_x" / "ignored.py")
    _write(repo / "airflow" / "dags" / "team_y" / "other.py")
    _write(repo / "company" / "team_y" / "scaffold.yaml", "agents:\n  agents_md: false\n")
    _write(repo / "company" / "team_y" / "main.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return project


def _repo(project: Path) -> Path:
    return project.parent.parent


def _register(project: Path) -> None:
    repo = _repo(project)
    (repo / "workspace.yaml").write_text("")
    register_workspace(
        repo, name="mono", projects=[("team_x", "company/team_x"), ("team_y", "company/team_y")]
    )


def _index(project: Path, **kwargs: Any) -> Path:
    config = load_config(project / "scaffold.yaml")
    run_pipeline(project, config, quiet=True, **kwargs)
    return Path(str(config.graph.db_path))


def _file_paths(db: Path) -> set[str]:
    store = DuckPGQBackend(db, read_only=True)
    try:
        return {r["path"] for r in store.query("SELECT path FROM File")}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Globs and the path helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "glob", ["**/*.py", "*/dags/*.py", "/abs/x.py", "airflow/../x.py", "@repo/x.py", ""]
)
def test_unbounded_or_escaping_globs_are_refused(glob: str) -> None:
    assert extra_glob_problem(glob)


def test_glob_matches_below_its_literal_directory_only() -> None:
    pattern = compile_extra_glob(GLOB)
    assert pattern.fullmatch("airflow/dags/team_x/dag.py")
    assert pattern.fullmatch("airflow/dags/team_x/sub/task.py")
    assert not pattern.fullmatch("airflow/dags/team_y/other.py")
    assert not pattern.fullmatch("airflow/dags/team_x/readme.md")
    assert extra_glob_problem(GLOB) is None


def test_spellings_map_between_node_and_vcs_relative_paths() -> None:
    assert repo_node_path("airflow/x.py") == f"{REPO_PREFIX}airflow/x.py"
    assert path_spellings("@repo/airflow/x.py") == ["@repo/airflow/x.py", "airflow/x.py"]
    assert path_spellings("src/x.py") == ["src/x.py"]


def test_resolver_maps_repo_paths_and_fails_closed(mono: Path, tmp_path: Path) -> None:
    repo = _repo(mono)
    assert resolve_node_path(mono, "foo.py") == mono / "foo.py"
    assert resolve_node_path(mono, DAG) == repo / "airflow/dags/team_x/dag.py"
    assert resolve_node_path(mono, "@repo/../outside.py") is None
    outside = tmp_path / "outside.py"
    outside.write_text("secret = 1\n")
    (repo / "airflow" / "escape.py").symlink_to(outside)
    assert resolve_node_path(mono, "@repo/airflow/escape.py") is None
    lone = tmp_path / "lone"
    lone.mkdir()
    assert resolve_node_path(lone, "@repo/x.py") is None


def test_a_plain_join_on_a_repo_path_finds_no_file(mono: Path) -> None:
    assert not (mono / DAG).is_file()


# ---------------------------------------------------------------------------
# Expansion and filtering
# ---------------------------------------------------------------------------


def test_scan_returns_matching_files_and_skips_ignored_ones(mono: Path) -> None:
    scan = scan_extra_paths(mono, load_config(mono / "scaffold.yaml").graph)
    assert scan.files == [DAG, TASK]
    assert scan.warnings == []


def test_unbounded_glob_is_refused_with_a_warning(mono: Path) -> None:
    graph = load_config(mono / "scaffold.yaml").graph
    graph.extra_paths = ["**/*.py"]
    scan = scan_extra_paths(mono, graph)
    assert scan.files == []
    assert "**/*.py" in scan.warnings[0]


def test_glob_into_a_registered_project_yields_no_files(mono: Path) -> None:
    _register(mono)
    graph = load_config(mono / "scaffold.yaml").graph
    graph.extra_paths = ["company/team_y/*.py"]
    scan = scan_extra_paths(mono, graph)
    assert scan.files == []
    assert any("team_y" in w for w in scan.warnings)


def test_glob_outside_the_vcs_root_or_through_a_symlink_yields_no_files(
    mono: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"
    _write(outside / "leak.py")
    (_repo(mono) / "airflow" / "linked").symlink_to(outside, target_is_directory=True)
    (_repo(mono) / "airflow" / "dags" / "team_x" / "leak.py").symlink_to(outside / "leak.py")
    graph = load_config(mono / "scaffold.yaml").graph
    graph.extra_paths = ["airflow/linked/*.py", GLOB]
    scan = scan_extra_paths(mono, graph)
    assert scan.files == [DAG, TASK]
    assert any("airflow/linked/*.py" in w for w in scan.warnings)
    assert any("leak.py" in w for w in scan.warnings)


def test_extra_paths_are_refused_while_a_real_repo_folder_exists(mono: Path) -> None:
    (mono / "@repo").mkdir()
    scan = scan_extra_paths(mono, load_config(mono / "scaffold.yaml").graph)
    assert scan.files == []
    assert "@repo" in scan.warnings[0]


def test_a_file_claimed_by_two_projects_is_indexed_by_neither(mono: Path) -> None:
    team_y = _repo(mono) / "company" / "team_y"
    (team_y / "scaffold.yaml").write_text(
        yaml.safe_dump({"graph": {"extra_paths": ["airflow/dags/team_x/dag.py"]}})
    )
    _register(mono)
    scan = scan_extra_paths(mono, load_config(mono / "scaffold.yaml").graph)
    assert scan.files == [TASK]
    assert any("team_y" in w and "dag.py" in w for w in scan.warnings)


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def test_dag_is_indexed_and_its_imports_resolve_into_the_project(mono: Path) -> None:
    db = _index(mono)
    store = DuckPGQBackend(db, read_only=True)
    try:
        paths = {r["path"] for r in store.query("SELECT path FROM File")}
        imports = {(r["src"], r["dst"]) for r in store.query("SELECT src, dst FROM IMPORTS")}
        functions = {r["name"] for r in store.query("SELECT name FROM Function")}
        folders = {r["path"] for r in store.query("SELECT path FROM Folder")}
    finally:
        store.close()
    assert {DAG, TASK, "foo.py"} <= paths
    assert not any("ignored.py" in p or "team_y" in p for p in paths)
    assert (f"file::{DAG}", "file::foo.py") in imports
    assert {"run", "task", "helper"} <= functions
    assert {"@repo", "@repo/airflow/dags/team_x/sub"} <= folders


def test_importers_and_search_include_the_dag(mono: Path) -> None:
    from agentscaffold.graph.incremental import direct_dependents
    from agentscaffold.graph.search import hybrid_search

    store = DuckPGQBackend(_index(mono), read_only=True)
    try:
        importers = direct_dependents(store, {"foo.py"})
        hits = hybrid_search(store, "run", mode="keyword", top_k=10, start=mono)
    finally:
        store.close()
    assert DAG in importers
    assert any(DAG in str(hit) for hit in hits)


def test_consumers_read_the_dag_source(mono: Path) -> None:
    from agentscaffold.graph.embeddings import _enrich_text
    from agentscaffold.graph.verify import check_staleness, verify_graph

    store = DuckPGQBackend(_index(mono), read_only=True)
    try:
        report = verify_graph(store, mono, deep=True, sample_ratio=1.0)
        staleness = check_staleness(store, mono, [DAG])
    finally:
        store.close()
    assert report["file_existence"]["missing"] == 0
    assert staleness == {DAG: "fresh"}
    assert "nightly DAG" in _enrich_text(mono, "File", {"n.path": DAG})


def test_incremental_run_updates_adds_and_removes_extra_path_files(mono: Path) -> None:
    db = _index(mono)
    dag = _repo(mono) / "airflow" / "dags" / "team_x" / "dag.py"
    dag.write_text(dag.read_text() + "\n\ndef extra():\n    return 3\n")
    _write(_repo(mono) / "airflow" / "dags" / "team_x" / "new.py", "def fresh():\n    return 4\n")
    _index(mono, incremental=True)
    store = DuckPGQBackend(db, read_only=True)
    try:
        functions = {r["name"] for r in store.query("SELECT name FROM Function")}
        paths = {r["path"] for r in store.query("SELECT path FROM File")}
    finally:
        store.close()
    assert {"extra", "fresh"} <= functions
    assert "@repo/airflow/dags/team_x/new.py" in paths

    config_path = mono / "scaffold.yaml"
    config_path.write_text(_config_text(Path(str(load_config(config_path).graph.db_path))))
    _index(mono, incremental=True)
    assert not any(p.startswith(REPO_PREFIX) for p in _file_paths(db))
    _index(mono, incremental=True)
    _index(mono)
    assert not any(p.startswith(REPO_PREFIX) for p in _file_paths(db))


def test_project_without_extra_paths_keeps_identical_ids(mono: Path, tmp_path: Path) -> None:
    from agentscaffold.graph.structure import collect_ignore_patterns, scan_indexable_files

    config_path = mono / "scaffold.yaml"
    config_path.write_text(_config_text(tmp_path / "plain.duckdb"))
    paths = _file_paths(_index(mono))
    assert paths == set(scan_indexable_files(mono, collect_ignore_patterns(mono)))


# ---------------------------------------------------------------------------
# Hook router and read-only guard
# ---------------------------------------------------------------------------


def _run_hook(event: str, payload: dict[str, Any]) -> str:
    from agentscaffold.hooks import router

    out = io.StringIO()
    assert router.main([event], stdin=io.StringIO(json.dumps(payload)), stdout=out) == 0
    return out.getvalue()


@pytest.fixture()
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from agentscaffold.hooks import router

    calls: list[Any] = []
    monkeypatch.setattr(router, "spawn_worker", lambda kind, project, event: calls.append(project))
    return calls


def test_router_routes_dag_edits_including_new_files(mono: Path, spawned: list[Any]) -> None:
    _register(mono)
    dags = _repo(mono) / "airflow" / "dags" / "team_x"
    _run_hook("cursor-after-edit", {"file_path": str(dags / "dag.py")})
    _write(dags / "brand_new.py")
    _run_hook("cursor-after-edit", {"file_path": str(dags / "brand_new.py")})
    _run_hook("cursor-after-edit", {"file_path": str(_repo(mono) / "airflow/dags/team_y/other.py")})
    assert [(p.name, p.root) for p in spawned] == [("team_x", mono), ("team_x", mono)]


def test_router_routes_nothing_for_a_file_two_projects_claim(
    mono: Path, spawned: list[Any]
) -> None:
    team_y = _repo(mono) / "company" / "team_y"
    (team_y / "scaffold.yaml").write_text(yaml.safe_dump({"graph": {"extra_paths": [GLOB]}}))
    _register(mono)
    _run_hook("cursor-after-edit", {"file_path": str(_repo(mono) / "airflow/dags/team_x/dag.py")})
    assert spawned == []


def test_read_only_entry_naming_repo_path_refuses_an_agent_edit(mono: Path) -> None:
    db = Path(str(load_config(mono / "scaffold.yaml").graph.db_path))
    (mono / "scaffold.yaml").write_text(_config_text(db, extra=[GLOB], read_only="@repo/airflow/"))
    _register(mono)
    payload = {"tool_input": {"file_path": str(_repo(mono) / "airflow/dags/team_x/dag.py")}}
    answer = json.loads(_run_hook("cursor-pre-edit", payload))
    assert answer["permission"] == "deny"
    assert DAG in json.dumps(answer)


# ---------------------------------------------------------------------------
# Review readers
# ---------------------------------------------------------------------------


def test_change_list_includes_an_edited_dag(mono: Path) -> None:
    from agentscaffold.review.changes import plan_changes

    repo = _repo(mono)
    _git(repo, "switch", "-q", "-c", "feature/283-dags")
    (repo / "airflow" / "dags" / "team_x" / "dag.py").write_text("y = 2\n")
    (mono / "foo.py").write_text("def helper():\n    return 5\n")
    _write(repo / "airflow" / "dags" / "team_x" / "untracked.py")
    _write(repo / "airflow" / "dags" / "team_y" / "noise.py")

    plain = plan_changes(mono, 283)
    changes = plan_changes(mono, 283, extra_paths=[GLOB])

    assert plain.files == ["foo.py"]
    assert changes.files == [DAG, "@repo/airflow/dags/team_x/untracked.py", "foo.py"]


def test_precedent_matches_either_spelling(tmp_path: Path) -> None:
    from agentscaffold.review.precedent import PrecedentSource, precedent_for

    store = DuckPGQBackend(":memory:")
    store.init_schema()
    try:
        store.create_node(
            "ReviewFinding",
            {
                "id": "rf::dag",
                "reviewType": "devils_advocate",
                "planNumber": 1,
                "severity": "high",
                "category": "RISK",
                "finding": "airflow/dags/team_x/dag.py retries forever",
                "resolution": "",
                "status": "open",
                "paths": json.dumps(["airflow/dags/team_x/dag.py"]),
            },
        )
        result = precedent_for([PrecedentSource("here", store)], [DAG], budget=None)
    finally:
        store.close()
    assert [item.id for item in result.items] == ["rf::dag"]


def test_file_impact_row_written_vcs_relative_resolves_to_the_dag(mono: Path) -> None:
    from agentscaffold.review.file_impact_resolve import _resolve_one

    row = _resolve_one(
        "airflow/dags/team_x/dag.py",
        "MODIFY",
        current_root=mono,
        current_name="team_x",
        current_store=None,
        sibling=None,
        sibling_store=None,
        impl_name=None,
        extra_paths=[GLOB],
    )
    assert (row["f.path"], row["resolution"]) == (DAG, "local")


def test_grep_fallback_searches_listed_dags_but_still_refuses_escapes(mono: Path) -> None:
    from agentscaffold.mcp.workspace_grep import workspace_grep

    found = workspace_grep(mono, "def run")
    assert DAG in {hit["path"] for hit in found["hits"]}
    scoped = workspace_grep(mono, "def task", path=TASK)
    assert [hit["path"] for hit in scoped["hits"]] == [TASK]
    assert workspace_grep(mono, "x", path="../team_y")["sandbox_rejected"] is True
    assert workspace_grep(mono, "x", path="@repo/airflow/dags/team_y/other.py")["sandbox_rejected"]


def test_hook_router_module_stays_free_of_heavy_imports() -> None:
    probe = (
        "import sys\n"
        "import agentscaffold.repo_paths\n"
        "heavy = [m for m in sys.modules if m.split('.')[0] == 'pydantic'"
        " or m == 'agentscaffold.config']\n"
        "print(','.join(heavy))\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
