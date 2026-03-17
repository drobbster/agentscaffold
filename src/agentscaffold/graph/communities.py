"""Community detection for module clustering.

Uses the Leiden algorithm (via graspologic) to detect tightly coupled
clusters of files based on import and call edges. Communities are stored
as Community nodes with MEMBER_OF_COMMUNITY edges.

graspologic (Leiden algorithm) is a core dependency.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import numpy as np
from graspologic.partition import leiden

from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.query_compat import ql, ql_execute, ql_scalar

logger = logging.getLogger(__name__)


def detect_communities(
    store: GraphBackend,
    *,
    resolution: float = 1.0,
    min_community_size: int = 2,
) -> dict[str, Any]:
    """Run Leiden community detection on the file import graph.

    Returns summary dict with community count and membership stats.
    """
    # Build adjacency from import and call edges
    import_edges = ql(
        store,
        cypher="MATCH (a:File)-[:IMPORTS]->(b:File) RETURN a.id, b.id",
        sql=(
            'SELECT t.a_id AS "a.id", t.b_id AS "b.id"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (a:File)-[e:IMPORTS]->(b:File)"
            " COLUMNS (a.id AS a_id, b.id AS b_id)) t"
        ),
    )
    call_edges = ql(
        store,
        cypher=(
            "MATCH (a:Function)-[:CALLS]->(b:Function) "
            "MATCH (fa:File)-[:DEFINES_FUNCTION]->(a) "
            "MATCH (fb:File)-[:DEFINES_FUNCTION]->(b) "
            "WHERE fa.id <> fb.id "
            "RETURN DISTINCT fa.id, fb.id"
        ),
        sql=(
            'SELECT DISTINCT t.fa_id AS "fa.id", t.fb_id AS "fb.id"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (fa:File)-[e1:DEFINES_FUNCTION]->(a:Function)"
            "-[e2:CALLS]->(b:Function)<-[e3:DEFINES_FUNCTION]-(fb:File)"
            " WHERE fa.id <> fb.id"
            " COLUMNS (fa.id AS fa_id, fb.id AS fb_id)) t"
        ),
    )

    node_set: set[str] = set()
    edge_list: list[tuple[str, str]] = []

    for row in import_edges:
        src, dst = row["a.id"], row["b.id"]
        node_set.add(src)
        node_set.add(dst)
        edge_list.append((src, dst))

    for row in call_edges:
        src, dst = row["fa.id"], row["fb.id"]
        node_set.add(src)
        node_set.add(dst)
        edge_list.append((src, dst))

    if len(node_set) < min_community_size:
        logger.info("Not enough connected files for community detection")
        return {"communities": 0, "files_assigned": 0, "largest": 0}

    nodes = sorted(node_set)
    node_idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)

    adjacency = np.zeros((n, n), dtype=np.float64)
    for src, dst in edge_list:
        i, j = node_idx[src], node_idx[dst]
        adjacency[i][j] += 1.0
        adjacency[j][i] += 1.0

    partition = leiden(adjacency, resolution=resolution)

    # partition is a dict-like: index -> community_id
    community_map: dict[str, int] = {}
    for idx, comm_id in partition.items():
        community_map[nodes[idx]] = int(comm_id)

    # Group by community
    comm_members: dict[int, list[str]] = {}
    for node_id, comm_id in community_map.items():
        comm_members.setdefault(comm_id, []).append(node_id)

    # Filter by min size
    valid_communities = {
        cid: members for cid, members in comm_members.items() if len(members) >= min_community_size
    }

    # Clear old communities
    ql_execute(
        store,
        cypher="MATCH (n:Community) DETACH DELETE n",
        sql="DELETE FROM Community",
    )

    files_assigned = 0
    for comm_id, members in valid_communities.items():
        # Derive a label from common path prefixes
        paths = []
        for fid in members:
            rows = ql(
                store,
                cypher=f"MATCH (f:File) WHERE f.id = '{fid}' RETURN f.path",
                sql=f"SELECT path AS \"f.path\" FROM File WHERE id = '{fid}'",
            )
            if rows:
                paths.append(rows[0]["f.path"])

        label = _derive_label(paths)

        func_count = 0
        for fid in members:
            fc = ql_scalar(
                store,
                cypher=(
                    f"MATCH (f:File)-[:DEFINES_FUNCTION]->(fn:Function) "
                    f"WHERE f.id = '{fid}' RETURN count(fn)"
                ),
                sql=(
                    f"SELECT COUNT(*) FROM GRAPH_TABLE(agentscaffold_graph"
                    f" MATCH (f:File)-[e:DEFINES_FUNCTION]->(fn:Function)"
                    f" WHERE f.id = '{fid}'"
                    f" COLUMNS (fn.id AS fn_id)) t"
                ),
            )
            func_count += int(fc) if fc else 0

        community_node_id = f"community::{comm_id}"
        store.create_node(
            "Community",
            {
                "id": community_node_id,
                "name": f"Community {comm_id}",
                "label": label,
                "fileCount": len(members),
                "functionCount": func_count,
            },
        )

        for fid in members:
            store.create_edge("MEMBER_OF_COMMUNITY", "File", fid, "Community", community_node_id)
            files_assigned += 1

    result = {
        "communities": len(valid_communities),
        "files_assigned": files_assigned,
        "largest": max((len(m) for m in valid_communities.values()), default=0),
        "sizes": sorted([len(m) for m in valid_communities.values()], reverse=True),
    }

    logger.info(
        "Detected %d communities (%d files assigned)",
        result["communities"],
        result["files_assigned"],
    )

    return result


def get_communities(store: GraphBackend) -> list[dict[str, Any]]:
    """Return all communities with their member files."""
    communities = ql(
        store,
        cypher=(
            "MATCH (c:Community) "
            "RETURN c.id, c.name, c.label, c.fileCount, c.functionCount "
            "ORDER BY c.fileCount DESC"
        ),
        sql=(
            'SELECT id AS "c.id", name AS "c.name", label AS "c.label",'
            ' fileCount AS "c.fileCount", functionCount AS "c.functionCount"'
            " FROM Community ORDER BY fileCount DESC"
        ),
    )

    for comm in communities:
        cid = comm["c.id"]
        members = ql(
            store,
            cypher=(
                f"MATCH (f:File)-[:MEMBER_OF_COMMUNITY]->(c:Community) "
                f"WHERE c.id = '{cid}' "
                f"RETURN f.path ORDER BY f.path"
            ),
            sql=(
                f'SELECT t.f_path AS "f.path"'
                f" FROM GRAPH_TABLE(agentscaffold_graph"
                f" MATCH (f:File)-[e:MEMBER_OF_COMMUNITY]->(c:Community)"
                f" WHERE c.id = '{cid}'"
                f" COLUMNS (f.path AS f_path)) t"
                f" ORDER BY t.f_path"
            ),
        )
        comm["files"] = [m["f.path"] for m in members]

    return communities


def _derive_label(paths: list[str]) -> str:
    """Derive a human-readable label from a set of file paths."""
    if not paths:
        return "unknown"

    parts_list = [p.split("/") for p in paths]
    if len(parts_list) == 1:
        return "/".join(parts_list[0][:-1]) or parts_list[0][0]

    # Find deepest common directory
    dir_counts: Counter[str] = Counter()
    for parts in parts_list:
        for i in range(1, len(parts)):
            dir_path = "/".join(parts[:i])
            dir_counts[dir_path] += 1

    if not dir_counts:
        return "root"

    # Most common directory that covers at least half the files
    threshold = len(paths) / 2
    best = ""
    for d, count in dir_counts.most_common():
        if count >= threshold and len(d) > len(best):
            best = d

    return best or "root"
