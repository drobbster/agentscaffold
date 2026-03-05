"""Community detection for module clustering.

Uses the Leiden algorithm (via graspologic) to detect tightly coupled
clusters of files based on import and call edges. Communities are stored
as Community nodes with MEMBER_OF_COMMUNITY edges.

Requires: pip install agentscaffold[communities]
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)

try:
    import numpy as np
    from graspologic.partition import leiden

    _leiden_available = True
except ImportError:
    _leiden_available = False


def detect_communities(
    store: GraphStore,
    *,
    resolution: float = 1.0,
    min_community_size: int = 2,
) -> dict[str, Any]:
    """Run Leiden community detection on the file import graph.

    Returns summary dict with community count and membership stats.
    """
    if not _leiden_available:
        raise ImportError(
            "Community detection requires graspologic: " "pip install agentscaffold[communities]"
        )

    # Build adjacency from import and call edges
    import_edges = store.query("MATCH (a:File)-[:IMPORTS]->(b:File) RETURN a.id, b.id")
    call_edges = store.query(
        "MATCH (a:Function)-[:CALLS]->(b:Function) "
        "MATCH (fa:File)-[:DEFINES_FUNCTION]->(a) "
        "MATCH (fb:File)-[:DEFINES_FUNCTION]->(b) "
        "WHERE fa.id <> fb.id "
        "RETURN DISTINCT fa.id, fb.id"
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
    store.execute("MATCH (n:Community) DETACH DELETE n")

    files_assigned = 0
    for comm_id, members in valid_communities.items():
        # Derive a label from common path prefixes
        paths = []
        for fid in members:
            rows = store.query(f"MATCH (f:File) WHERE f.id = '{fid}' RETURN f.path")
            if rows:
                paths.append(rows[0]["f.path"])

        label = _derive_label(paths)

        func_count = 0
        for fid in members:
            fc = store.query_scalar(
                f"MATCH (f:File)-[:DEFINES_FUNCTION]->(fn:Function) "
                f"WHERE f.id = '{fid}' RETURN count(fn)"
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


def get_communities(store: GraphStore) -> list[dict[str, Any]]:
    """Return all communities with their member files."""
    communities = store.query(
        "MATCH (c:Community) "
        "RETURN c.id, c.name, c.label, c.fileCount, c.functionCount "
        "ORDER BY c.fileCount DESC"
    )

    for comm in communities:
        members = store.query(
            f"MATCH (f:File)-[:MEMBER_OF_COMMUNITY]->(c:Community) "
            f"WHERE c.id = '{comm['c.id']}' "
            f"RETURN f.path ORDER BY f.path"
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
