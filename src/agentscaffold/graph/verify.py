"""Graph verification and health checking.

Spot-checks graph accuracy against the filesystem to detect
staleness, missing files, and definition drift.
"""

from __future__ import annotations

import hashlib
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)
console = Console()


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except (OSError, PermissionError):
        return ""
    return h.hexdigest()


def verify_graph(
    store: GraphStore,
    root: Path,
    *,
    deep: bool = False,
    sample_ratio: float = 0.1,
) -> dict[str, Any]:
    """Verify graph accuracy against the filesystem.

    Args:
        store: Open graph store to verify.
        root: Project root directory.
        deep: If True, re-parse a sample of files and compare definitions.
        sample_ratio: Fraction of files to sample in deep mode (default 10%).

    Returns:
        Verification report dict.
    """
    root = root.resolve()
    report: dict[str, Any] = {
        "file_existence": {"total": 0, "exists": 0, "missing": 0},
        "hash_freshness": {"total": 0, "fresh": 0, "stale": 0},
        "stale_files": [],
        "missing_files": [],
        "health": "UNKNOWN",
    }

    # File existence and hash check
    file_rows = store.query("MATCH (f:File) RETURN f.id, f.path, f.contentHash")

    for row in file_rows:
        file_path = row["f.path"]
        stored_hash = row["f.contentHash"]
        full_path = root / file_path

        report["file_existence"]["total"] += 1
        report["hash_freshness"]["total"] += 1

        if not full_path.is_file():
            report["file_existence"]["missing"] += 1
            report["missing_files"].append(file_path)
        else:
            report["file_existence"]["exists"] += 1
            current_hash = _file_hash(full_path)
            if current_hash == stored_hash:
                report["hash_freshness"]["fresh"] += 1
            else:
                report["hash_freshness"]["stale"] += 1
                report["stale_files"].append(file_path)

    # Governance sync check
    report["governance"] = _check_governance_sync(store)

    # Deep verification (optional)
    if deep and file_rows:
        report["deep_check"] = _deep_verify(store, root, file_rows, sample_ratio)

    # Compute health score
    total = report["file_existence"]["total"]
    if total == 0:
        report["health"] = "EMPTY"
    else:
        existence_rate = report["file_existence"]["exists"] / total
        freshness_rate = report["hash_freshness"]["fresh"] / total
        if existence_rate == 1.0 and freshness_rate >= 0.95:
            report["health"] = "GOOD"
        elif existence_rate >= 0.9 and freshness_rate >= 0.8:
            report["health"] = "FAIR"
        else:
            report["health"] = "STALE"

    return report


def _check_governance_sync(store: GraphStore) -> dict[str, Any]:
    """Check if governance node counts are non-zero."""
    return {
        "plans": store.node_count("Plan"),
        "contracts": store.node_count("Contract"),
        "learnings": store.node_count("Learning"),
        "review_findings": store.node_count("ReviewFinding"),
    }


def _deep_verify(
    store: GraphStore,
    root: Path,
    file_rows: list[dict[str, Any]],
    sample_ratio: float,
) -> dict[str, Any]:
    """Re-parse a sample of files and compare against stored definitions."""
    sample_size = max(1, int(len(file_rows) * sample_ratio))
    sample = random.sample(file_rows, min(sample_size, len(file_rows)))

    checked = 0
    matches = 0
    mismatches: list[dict[str, str]] = []

    for row in sample:
        file_path = row["f.path"]
        full_path = root / file_path

        if not full_path.is_file():
            continue

        stored_funcs = store.query(
            "MATCH (f:File)-[:DEFINES_FUNCTION]->(fn:Function) "
            f"WHERE f.path = '{file_path}' "
            "RETURN fn.name, fn.startLine"
        )

        if not stored_funcs:
            continue

        checked += 1

        try:
            source = full_path.read_text(errors="replace")
            lines = source.splitlines()
        except (OSError, PermissionError):
            continue

        all_match = True
        for func in stored_funcs:
            name = func["fn.name"]
            line_num = int(func["fn.startLine"]) - 1
            if 0 <= line_num < len(lines):
                if name not in lines[line_num]:
                    all_match = False
                    mismatches.append(
                        {
                            "file": file_path,
                            "function": name,
                            "expected_line": str(func["fn.startLine"]),
                            "issue": "Function name not found at stored line",
                        }
                    )

        if all_match:
            matches += 1

    return {
        "files_sampled": checked,
        "matches": matches,
        "mismatches": mismatches,
    }


def check_contract_drift(store: GraphStore) -> dict[str, Any]:
    """Check for drift between contract declarations and actual code.

    Returns a report with:
    - declared_only: methods in contracts but not found in code
    - undocumented: methods in code linked to a contract but not declared
    - summary counts
    """
    contracts = store.query(
        "MATCH (c:Contract) RETURN c.id, c.name, c.declaredMethods, c.declaredClasses"
    )

    declared_only: list[dict[str, str]] = []
    linked_ok = 0
    total_declared = 0

    for c in contracts:
        contract_id = c["c.id"]
        contract_name = c["c.name"]
        raw_methods = c.get("c.declaredMethods", "") or ""
        raw_classes = c.get("c.declaredClasses", "") or ""

        declared_methods = [m for m in raw_methods.split(",") if m]
        declared_classes = [cl for cl in raw_classes.split(",") if cl]
        total_declared += len(declared_methods) + len(declared_classes)

        for method_name in declared_methods:
            # Check both Function and Method nodes
            fn_match = store.query(
                f"MATCH (fn:Function) WHERE fn.name = '{method_name}' RETURN fn.id LIMIT 1"
            )
            m_match = (
                store.query(f"MATCH (m:Method) WHERE m.name = '{method_name}' RETURN m.id LIMIT 1")
                if not fn_match
                else []
            )
            if fn_match or m_match:
                linked_ok += 1
            else:
                declared_only.append(
                    {
                        "contract": contract_name,
                        "type": "method",
                        "name": method_name,
                    }
                )

        for class_name in declared_classes:
            edges = store.query(
                f"MATCH (c:Contract)-[:CONTRACT_DECLARES_CLASS]->(n) "
                f"WHERE c.id = '{contract_id}' AND n.name = '{class_name}' "
                "RETURN n.id LIMIT 1"
            )
            if edges:
                linked_ok += 1
            else:
                declared_only.append(
                    {
                        "contract": contract_name,
                        "type": "class",
                        "name": class_name,
                    }
                )

    return {
        "total_declared": total_declared,
        "linked": linked_ok,
        "drift_items": declared_only,
        "drift_count": len(declared_only),
        "health": "CLEAN" if not declared_only else "DRIFT_DETECTED",
    }


def check_staleness(
    store: GraphStore,
    root: Path,
    file_paths: list[str],
) -> dict[str, str]:
    """Check specific files for staleness.

    Returns a dict of {file_path: "fresh"|"stale"|"missing"|"unknown"}.
    """
    root = root.resolve()
    result: dict[str, str] = {}

    for fp in file_paths:
        rows = store.query(f"MATCH (f:File) WHERE f.path = '{fp}' RETURN f.contentHash")
        if not rows:
            result[fp] = "unknown"
            continue

        stored_hash = rows[0]["f.contentHash"]
        full_path = root / fp
        if not full_path.is_file():
            result[fp] = "missing"
        else:
            current_hash = _file_hash(full_path)
            result[fp] = "fresh" if current_hash == stored_hash else "stale"

    return result


def print_verification_report(report: dict[str, Any]) -> None:
    """Print a formatted verification report to console."""
    table = Table(title="Graph Verification Report", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green", justify="right")

    fe = report["file_existence"]
    table.add_row(
        "File existence",
        (
            f"{fe['exists']}/{fe['total']} ({fe['exists'] / fe['total'] * 100:.0f}%)"
            if fe["total"]
            else "0/0"
        ),
    )

    hf = report["hash_freshness"]
    table.add_row(
        "Hash freshness",
        (
            f"{hf['fresh']}/{hf['total']} ({hf['fresh'] / hf['total'] * 100:.1f}%)"
            if hf["total"]
            else "0/0"
        ),
    )

    gov = report.get("governance", {})
    table.add_row(
        "Governance sync",
        f"{gov.get('plans', 0)} plans, {gov.get('contracts', 0)} contracts",
    )

    deep = report.get("deep_check")
    if deep:
        table.add_row(
            "Signature check",
            f"{deep['matches']}/{deep['files_sampled']} sampled files match",
        )

    console.print(table)

    health = report["health"]
    color = {"GOOD": "green", "FAIR": "yellow", "STALE": "red", "EMPTY": "red"}.get(health, "white")
    console.print(f"\nHealth: [{color}]{health}[/{color}]")

    stale_count = len(report.get("stale_files", []))
    if stale_count > 0:
        console.print(
            f"\n[yellow]{stale_count} files changed since last index. "
            "Run 'scaffold index --incremental' to refresh.[/yellow]"
        )

    missing_count = len(report.get("missing_files", []))
    if missing_count > 0:
        console.print(
            f"\n[red]{missing_count} indexed files no longer exist on disk. "
            "Run 'scaffold index' to rebuild.[/red]"
        )
