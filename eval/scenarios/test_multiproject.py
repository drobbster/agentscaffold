"""Multi-project correctness scenarios for the shared workspace graph."""

from __future__ import annotations

from eval.runner import (
    EvalResult,
    MultiProjectResult,
    collect_multi_project,
    collect_result,
)


def _normalize(vec: list[float]) -> list[float]:
    total = sum(v * v for v in vec) ** 0.5
    return [v / total for v in vec]


class TestMultiProjectCorrectness:
    """Plan 225 workspace invariants at indexed-pipeline level."""

    def test_scoped_default_search_stays_in_current_project(self, indexed_two_project_workspace):
        workspace, project_a, project_b, store, config = indexed_two_project_workspace
        from agentscaffold.graph.search import hybrid_search

        results = hybrid_search(
            store,
            "DataRouter",
            mode="keyword",
            top_k=10,
            tables=["Class"],
            start=project_a,
        )
        ids = [r.node_id for r in results]
        passed = bool(ids) and all(node_id.startswith("sim_project::") for node_id in ids)

        collect_multi_project(
            MultiProjectResult(
                scenario="scoped_default_search",
                passed=passed,
                scoped_count=len(ids),
                federated_count=0,
                projects_seen=["sim_project"],
                observations=ids,
            )
        )
        collect_result(
            EvalResult(
                scenario="multiproject_scoped_default_search",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Default scoped search from project A returns only project A nodes",
                actual=f"{len(ids)} hits: {ids}",
                category="multi_project",
            )
        )

        assert passed

    def test_federated_read_includes_project_provenance(self, indexed_two_project_workspace):
        workspace, project_a, project_b, store, config = indexed_two_project_workspace

        rows = store.query(
            "SELECT id, project, filePath FROM Class WHERE name = 'DataRouter' ORDER BY project",
            {},
        )
        projects = sorted({row["project"] for row in rows})
        passed = projects == ["sim_project", "sim_project_b"] and all(
            row.get("project") for row in rows
        )

        collect_multi_project(
            MultiProjectResult(
                scenario="federated_provenance",
                passed=passed,
                scoped_count=0,
                federated_count=len(rows),
                projects_seen=projects,
                observations=[f"{row['project']}:{row['filePath']}" for row in rows],
            )
        )
        collect_result(
            EvalResult(
                scenario="multiproject_federated_provenance",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Federated read returns both projects with project provenance",
                actual=f"projects={projects}, rows={len(rows)}",
                category="multi_project",
            )
        )

        assert passed

    def test_cross_project_duplicates_surface_seeded_pair(self, indexed_two_project_workspace):
        workspace, project_a, project_b, store, config = indexed_two_project_workspace
        from agentscaffold.graph.embeddings import find_duplicates
        from agentscaffold.graph.scoping import unqualify_id

        rows = store.query(
            "SELECT id, project FROM Class WHERE name = 'DataRouter' ORDER BY project",
            {},
        )
        assert {row["project"] for row in rows} == {"sim_project", "sim_project_b"}

        for row in rows:
            project = row["project"]
            _, raw_id = unqualify_id(row["id"], {"sim_project", "sim_project_b"})
            store.set_write_project(project)
            store.store_embedding(
                raw_id,
                "Class",
                _normalize([1.0, 0.0, 0.0]),
                model="all-MiniLM-L6-v2",
                text_hash=f"eval-{project}",
            )
        store.set_write_project(None)

        pairs = find_duplicates(store, table="Class", threshold=0.99, top_n=10, start=project_a)
        matched = [p for p in pairs if "DataRouter" in p["id_a"] and "DataRouter" in p["id_b"]]
        passed = bool(matched)

        collect_multi_project(
            MultiProjectResult(
                scenario="cross_project_duplicates",
                passed=passed,
                scoped_count=0,
                federated_count=len(pairs),
                projects_seen=sorted(
                    {p["project_a"] for p in pairs} | {p["project_b"] for p in pairs}
                ),
                observations=[str(p) for p in pairs[:5]],
            )
        )
        collect_result(
            EvalResult(
                scenario="multiproject_cross_project_duplicates",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Seeded near-duplicate DataRouter pair is reported",
                actual=f"{len(pairs)} duplicate pairs",
                observations=[str(p) for p in pairs[:5]],
                category="multi_project",
            )
        )

        assert passed

    def test_migrate_to_multi_project_round_trip_integrity(self, indexed_sim_duckdb):
        root, store, config = indexed_sim_duckdb

        counts = store.migrate_to_multi_project("sim_project")
        problems = store.verify_integrity()
        migrated_anything = counts["nodes"] > 0
        passed = migrated_anything and problems == []

        collect_multi_project(
            MultiProjectResult(
                scenario="migrate_verify_integrity",
                passed=passed,
                scoped_count=counts["nodes"],
                federated_count=0,
                projects_seen=["sim_project"],
                observations=[f"counts={counts}", f"problems={problems}"],
            )
        )
        collect_result(
            EvalResult(
                scenario="multiproject_migrate_verify_integrity",
                passed=passed,
                score=1.0 if passed else 0.0,
                expected="Single-project graph migrates and verifies with zero integrity problems",
                actual=f"counts={counts}, problems={problems}",
                category="multi_project",
            )
        )

        assert passed
