"""System inventory in the graph: Component nodes, edges, impact and context (Plan 282)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentscaffold.config import load_config
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.inventory import (
    components_for_paths,
    components_owned_by,
    process_inventory,
)
from agentscaffold.graph.pipeline import run_pipeline

pytest.importorskip("duckdb", reason="duckdb not installed")

FIXTURE = Path(__file__).parent / "fixtures" / "system_inventory" / "project"
INVENTORY = Path("docs/ai/system_inventory.yaml")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    config = yaml.safe_load((root / "scaffold.yaml").read_text())
    config["graph"] = {"db_path": str(tmp_path / "graph.duckdb"), "embeddings": False}
    (root / "scaffold.yaml").write_text(yaml.safe_dump(config))
    _write(root / "flows" / "weekly.py", "def weekly_training():\n    return 1\n")
    _write(root / "flows" / "ingest.py", "def nightly_ingest():\n    return 2\n")
    _write(root / "configs" / "training" / "lr.py", "RATE = 0.1\n")
    _write(root / "configs" / "ingest" / "sources.py", "SOURCES = []\n")
    _write(root / "scripts" / "sync" / "run.py", "def main():\n    return 0\n")
    return root


def _index(root: Path, **kwargs: Any) -> DuckPGQBackend:
    config = load_config(root / "scaffold.yaml")
    run_pipeline(root, config, quiet=True, **kwargs)
    return DuckPGQBackend(Path(str(config.graph.db_path)), read_only=True)


def _edges(store: DuckPGQBackend, table: str) -> set[tuple[str, str]]:
    return {(r["src"], r["dst"]) for r in store.query(f"SELECT src, dst FROM {table}")}


def test_full_index_writes_components_and_edges(project: Path) -> None:
    store = _index(project)
    try:
        rows = store.query("SELECT componentId, lifecycle, project FROM Component")
        ids = sorted(r["componentId"] for r in rows)
        # Ten entries, one duplicated id: the first wins.
        assert len(ids) == 9
        assert "prefect:weekly-training" in ids
        assert {r["project"] for r in rows} == {""}

        owned = _edges(store, "OWNED_BY")
        assert ("component::prefect:weekly-training", "plan::80") in owned
        assert not any(src == "component::prefect:backfill" for src, _ in owned)

        assert ("component::prefect:weekly-training", "file::flows/weekly.py") in _edges(
            store, "ENTRYPOINT"
        )
        reads = _edges(store, "READS")
        assert ("component::prefect:weekly-training", "file::configs/training/lr.py") in reads
        assert ("component::prefect:retired-sync", "file::scripts/sync/run.py") in reads
        assert ("component::prefect:weekly-training", "file::configs/ingest/sources.py") not in (
            reads
        )
    finally:
        store.close()


def test_components_for_paths_handles_files_and_directories(project: Path) -> None:
    store = _index(project)
    try:
        by_file = components_for_paths(store, ["configs/training/lr.py"], root=project)
        assert [c["component"] for c in by_file] == ["prefect:weekly-training"]
        assert by_file[0]["lifecycle"] == "paused"
        assert by_file[0]["via"] == ["reads"]

        by_dir = components_for_paths(store, ["configs/"], root=project)
        assert {c["component"] for c in by_dir} == {
            "config:risk-limits",
            "prefect:nightly-ingest",
            "prefect:weekly-training",
        }
        by_entry = components_for_paths(store, ["flows/weekly.py"], root=project)
        assert {c["component"] for c in by_entry} == {
            "prefect:weekly-training",
            "prefect:weekly-training-copy",
        }
        assert components_for_paths(store, ["README.md"], root=project) == []
    finally:
        store.close()


def test_components_owned_by_a_plan(project: Path) -> None:
    store = _index(project)
    try:
        owned = {c["component"] for c in components_owned_by(store, 150)}
        assert owned == {"compose:api", "compose:worker", "config:risk-limits"}
    finally:
        store.close()


def test_incremental_index_after_an_inventory_edit(project: Path) -> None:
    _index(project).close()
    path = project / INVENTORY
    path.write_text(
        path.read_text().replace(
            "    lifecycle: experimental\n", "    lifecycle: active\n    # promoted\n"
        )
    )
    store = _index(project, incremental=True)
    try:
        row = store.query("SELECT lifecycle FROM Component WHERE componentId = 'compose:worker'")
        assert row[0]["lifecycle"] == "active"
        # Plan nodes were re-created by the governance refresh; ownership survives.
        assert ("component::compose:worker", "plan::150") in _edges(store, "OWNED_BY")
    finally:
        store.close()


def test_incremental_code_edit_keeps_component_edges(project: Path) -> None:
    _index(project).close()
    (project / "flows" / "weekly.py").write_text("def weekly_training():\n    return 3\n")
    store = _index(project, incremental=True)
    try:
        assert ("component::prefect:weekly-training", "file::flows/weekly.py") in _edges(
            store, "ENTRYPOINT"
        )
    finally:
        store.close()


def test_disabled_inventory_leaves_no_components(project: Path) -> None:
    config = yaml.safe_load((project / "scaffold.yaml").read_text())
    config["inventory"]["enabled"] = False
    (project / "scaffold.yaml").write_text(yaml.safe_dump(config))
    store = _index(project)
    try:
        assert store.query("SELECT COUNT(*) AS n FROM Component")[0]["n"] == 0
    finally:
        store.close()


def test_malformed_inventory_does_not_break_indexing(project: Path) -> None:
    (project / INVENTORY).write_text("schema_version: 9\n")
    store = _index(project)
    try:
        assert store.query("SELECT COUNT(*) AS n FROM Component")[0]["n"] == 0
        assert store.query("SELECT COUNT(*) AS n FROM File")[0]["n"] > 0
    finally:
        store.close()


def test_components_are_not_exported(project: Path) -> None:
    store = _index(project)
    try:
        exported = store.export_governance()
        assert "Component" not in exported.get("nodes", {})
        assert not {"OWNED_BY", "ENTRYPOINT", "READS"} & set(exported.get("edges", {}))
    finally:
        store.close()


def test_multi_project_ids_and_stamp(project: Path) -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    try:
        store.set_write_project("alpha")
        store.create_node("File", {"id": "file::flows/weekly.py", "path": "flows/weekly.py"})
        store.create_node("Plan", {"id": "plan::80", "number": 80})
        config = load_config(project / "scaffold.yaml")
        result = process_inventory(store, project, config)
        assert result["components"] == 9
        row = store.query(
            "SELECT id, project FROM Component WHERE componentId = 'prefect:weekly-training'"
        )[0]
        assert row["id"] == "alpha::component::prefect:weekly-training"
        assert row["project"] == "alpha"
        assert ("alpha::component::prefect:weekly-training", "alpha::plan::80") in _edges(
            store, "OWNED_BY"
        )
        scoped = components_for_paths(
            store, ["flows/weekly.py"], root=project, scope=("project = ?", {"project": "beta"})
        )
        assert scoped == []

        # A second run replaces this project's rows rather than adding to them.
        process_inventory(store, project, config)
        assert store.query("SELECT COUNT(*) AS n FROM Component")[0]["n"] == 9
    finally:
        store.close()


def test_impact_and_context_report_components(project: Path) -> None:
    from agentscaffold.mcp.server import _tool_context, _tool_impact

    config = load_config(project / "scaffold.yaml")
    store = _index(project)
    try:
        impact = _tool_impact(
            store, {"file_or_symbol": "configs/training/lr.py"}, {}, project, config
        )
        components = impact["governance_impact"]["components"]
        assert [c["component"] for c in components] == ["prefect:weekly-training"]
        assert "component prefect:weekly-training (paused, Plan 080" in impact["markdown"]

        quiet = _tool_impact(
            store,
            {"file_or_symbol": "configs/training/lr.py", "include_precedent": False},
            {},
            project,
            config,
        )
        assert "governance_impact" not in quiet

        context = _tool_context(store, {"symbol": "weekly_training"}, {}, project, config)
        assert {c["component"] for c in context["components"]} == {
            "prefect:weekly-training",
            "prefect:weekly-training-copy",
        }
        assert "### Components" in context["markdown"]
    finally:
        store.close()
