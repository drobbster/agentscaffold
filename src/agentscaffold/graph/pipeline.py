"""Ingestion pipeline orchestrator.

Runs indexing phases in sequence with transaction-per-phase safety.
Reports a quality summary on completion.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

from agentscaffold.graph.schema import SCHEMA_VERSION
from agentscaffold.graph.store import GraphStore
from agentscaffold.graph.symbol_table import SymbolTable

if TYPE_CHECKING:
    from agentscaffold.config import ScaffoldConfig

logger = logging.getLogger(__name__)
console = Console()


def run_pipeline(
    root: Path,
    config: ScaffoldConfig | None = None,
    *,
    incremental: bool = False,
    embeddings: bool = False,
    audit: bool = False,
) -> dict[str, Any]:
    """Execute the full indexing pipeline.

    Returns a summary dict with quality metrics.
    """
    root = root.resolve()
    graph_config = config.graph if config else None
    db_path = Path(graph_config.db_path) if graph_config else Path(".scaffold/graph.db")

    if not db_path.is_absolute():
        db_path = root / db_path

    t0 = time.monotonic()

    store = GraphStore(db_path)

    # Schema version check
    stored_version = store.schema_version()
    if stored_version is not None and stored_version != SCHEMA_VERSION:
        console.print(
            f"[yellow]Graph schema changed (v{stored_version} -> v{SCHEMA_VERSION}). "
            "Rebuilding...[/yellow]"
        )
        store.clear_all()

    store.init_schema()
    phases_completed: list[str] = []
    summary: dict[str, Any] = {}

    # Check for resumable state
    if not incremental:
        pipeline_state = store.get_pipeline_state()
        if pipeline_state["state"] == "partial":
            phases_completed = pipeline_state["phases_completed"]
            console.print(
                f"[yellow]Resuming from partial index. "
                f"Completed phases: {phases_completed}[/yellow]"
            )

    symbol_table = SymbolTable()

    # Compute total phases
    total_phases = 4  # structure, parsing, resolution, governance

    # Phase 1: Structure
    if "structure" not in phases_completed:
        console.print(
            f"[bold]Phase 1/{total_phases}: Structure[/bold] -- scanning directory tree..."
        )
        try:
            from agentscaffold.graph.structure import process_structure

            struct_result = process_structure(store, root, graph_config)
            summary["structure"] = struct_result
            phases_completed.append("structure")
            store.update_pipeline_state("partial", phases_completed)
            console.print(
                f"  {struct_result['files']} files, "
                f"{struct_result['folders']} folders, "
                f"{struct_result['skipped']} skipped"
            )
        except Exception as exc:
            logger.error("Phase 1 (structure) failed: %s", exc)
            store.update_pipeline_state("failed:structure", phases_completed)
            store.add_parsing_warning("pw::pipeline::structure", "", "structure", str(exc), "error")
            return _build_summary(summary, phases_completed, t0, store)

    # Phase 2: Parsing
    if "parsing" not in phases_completed:
        console.print(f"[bold]Phase 2/{total_phases}: Parsing[/bold] -- extracting definitions...")
        try:
            from agentscaffold.graph.parsing import process_parsing

            parse_result = process_parsing(store, root, symbol_table)
            summary["parsing"] = parse_result
            phases_completed.append("parsing")
            store.update_pipeline_state("partial", phases_completed)
            console.print(
                f"  {parse_result['functions']} functions, "
                f"{parse_result['classes']} classes, "
                f"{parse_result['methods']} methods, "
                f"{parse_result['interfaces']} interfaces "
                f"({parse_result['files_parsed']} files parsed, "
                f"{parse_result['files_skipped']} skipped)"
            )
        except Exception as exc:
            logger.error("Phase 2 (parsing) failed: %s", exc)
            store.update_pipeline_state("failed:parsing", phases_completed)
            store.add_parsing_warning("pw::pipeline::parsing", "", "parsing", str(exc), "error")
            return _build_summary(summary, phases_completed, t0, store)
    else:
        # If resuming, we need to rebuild the symbol table from existing graph data
        _rebuild_symbol_table(store, symbol_table)

    # Phase 3: Resolution (imports + calls)
    if "resolution" not in phases_completed:
        console.print(
            f"[bold]Phase 3/{total_phases}: Resolution[/bold] " "-- resolving imports and calls..."
        )
        try:
            from agentscaffold.graph.calls import process_calls
            from agentscaffold.graph.imports import process_imports

            import_result = process_imports(store, root, symbol_table)
            summary["imports"] = import_result

            total_imports = import_result["resolved"] + import_result["unresolved"]
            import_rate = import_result["resolved"] / total_imports * 100 if total_imports else 0

            call_result = process_calls(store, root, symbol_table)
            summary["calls"] = call_result

            phases_completed.append("resolution")
            store.update_pipeline_state("partial", phases_completed)

            console.print(
                f"  Imports: {import_result['resolved']} resolved, "
                f"{import_result['unresolved']} unresolved "
                f"({import_rate:.1f}%)"
            )
            console.print(
                f"  Calls: {call_result['total']} resolved -- "
                f"{call_result['high_confidence']} high, "
                f"{call_result['medium_confidence']} medium, "
                f"{call_result['low_confidence']} low"
            )

            # Quality warnings
            if total_imports > 0 and import_rate < 85:
                console.print(
                    "[yellow]  WARNING: Low import resolution rate. "
                    "Check for dynamic imports or unsupported patterns.[/yellow]"
                )
            if call_result["total"] > 0:
                high_rate = call_result["high_confidence"] / call_result["total"] * 100
                if high_rate < 50:
                    console.print(
                        "[yellow]  WARNING: Low call resolution confidence. "
                        "Blast radius analysis may undercount consumers.[/yellow]"
                    )

        except Exception as exc:
            logger.error("Phase 3 (resolution) failed: %s", exc)
            store.update_pipeline_state("failed:resolution", phases_completed)
            store.add_parsing_warning(
                "pw::pipeline::resolution", "", "resolution", str(exc), "error"
            )
            return _build_summary(summary, phases_completed, t0, store)

    # Phase 4: Governance (plans, contracts, learnings)
    if "governance" not in phases_completed:
        console.print(
            f"[bold]Phase 4/{total_phases}: Governance[/bold] "
            "-- ingesting plans, contracts, learnings..."
        )
        try:
            from agentscaffold.graph.governance import process_governance

            gov_result = process_governance(store, root)
            summary["governance"] = gov_result
            phases_completed.append("governance")
            store.update_pipeline_state("complete", phases_completed)
            console.print(
                f"  {gov_result['plans']} plans, "
                f"{gov_result['contracts']} contracts, "
                f"{gov_result['learnings']} learnings, "
                f"{gov_result['impact_edges']} impact edges"
            )
        except Exception as exc:
            logger.error("Phase 4 (governance) failed: %s", exc)
            store.add_parsing_warning(
                "pw::pipeline::governance", "", "governance", str(exc), "error"
            )
            # Governance failure is non-fatal; code graph is still usable

    elapsed = time.monotonic() - t0
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["phases_completed"] = phases_completed

    # Print final summary
    _print_summary(summary, store)

    store.close()
    return summary


def _rebuild_symbol_table(store: GraphStore, symbol_table: SymbolTable) -> None:
    """Rebuild symbol table from existing graph data (for pipeline resumption)."""
    from agentscaffold.graph.symbol_table import SymbolEntry

    for row in store.query(
        "MATCH (f:File)-[:DEFINES_FUNCTION]->(fn:Function) "
        "RETURN f.id, f.path, fn.id, fn.name, fn.isExported, fn.startLine"
    ):
        module = row["f.path"].replace("/", ".").removesuffix(".py")
        symbol_table.add(
            SymbolEntry(
                name=row["fn.name"],
                qualified_name=f"{module}.{row['fn.name']}",
                file_path=row["f.path"],
                file_id=row["f.id"],
                node_id=row["fn.id"],
                node_type="function",
                is_exported=bool(row["fn.isExported"]),
                start_line=int(row["fn.startLine"]),
            )
        )

    for row in store.query(
        "MATCH (f:File)-[:DEFINES_CLASS]->(c:Class) "
        "RETURN f.id, f.path, c.id, c.name, c.isExported, c.startLine"
    ):
        module = row["f.path"].replace("/", ".").removesuffix(".py")
        symbol_table.add(
            SymbolEntry(
                name=row["c.name"],
                qualified_name=f"{module}.{row['c.name']}",
                file_path=row["f.path"],
                file_id=row["f.id"],
                node_id=row["c.id"],
                node_type="class",
                is_exported=bool(row["c.isExported"]),
                start_line=int(row["c.startLine"]),
            )
        )

    for row in store.query(
        "MATCH (c:Class)-[:HAS_METHOD]->(m:Method) "
        "RETURN m.id, m.name, m.className, m.filePath, m.isExported, m.startLine"
    ):
        file_path = row["m.filePath"]
        module = file_path.replace("/", ".").removesuffix(".py")
        symbol_table.add(
            SymbolEntry(
                name=row["m.name"],
                qualified_name=f"{module}.{row['m.className']}.{row['m.name']}",
                file_path=file_path,
                file_id=f"file::{file_path}",
                node_id=row["m.id"],
                node_type="method",
                is_exported=bool(row["m.isExported"]),
                class_name=row["m.className"],
                start_line=int(row["m.startLine"]),
            )
        )


def _build_summary(
    summary: dict[str, Any],
    phases_completed: list[str],
    t0: float,
    store: GraphStore,
) -> dict[str, Any]:
    """Build summary dict even for partial/failed runs."""
    summary["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    summary["phases_completed"] = phases_completed
    _print_summary(summary, store)
    store.close()
    return summary


def _print_summary(summary: dict[str, Any], store: GraphStore) -> None:
    """Print a formatted index summary with quality metrics."""
    console.print()

    table = Table(title="Index Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    struct = summary.get("structure", {})
    parse = summary.get("parsing", {})
    imports = summary.get("imports", {})
    calls = summary.get("calls", {})

    table.add_row("Files indexed", str(struct.get("files", 0)))
    table.add_row("Files skipped (structure)", str(struct.get("skipped", 0)))
    table.add_row("Folders", str(struct.get("folders", 0)))
    table.add_row("Functions extracted", str(parse.get("functions", 0)))
    table.add_row("Classes extracted", str(parse.get("classes", 0)))
    table.add_row("Methods extracted", str(parse.get("methods", 0)))
    table.add_row("Interfaces extracted", str(parse.get("interfaces", 0)))
    table.add_row("Files parsed", str(parse.get("files_parsed", 0)))
    table.add_row("Files skipped (parse)", str(parse.get("files_skipped", 0)))

    total_imp = imports.get("resolved", 0) + imports.get("unresolved", 0)
    imp_rate = imports.get("resolved", 0) / total_imp * 100 if total_imp else 0
    table.add_row(
        "Imports resolved",
        f"{imports.get('resolved', 0)}/{total_imp} ({imp_rate:.1f}%)",
    )

    table.add_row(
        "Calls resolved",
        f"{calls.get('total', 0)} "
        f"(H:{calls.get('high_confidence', 0)} "
        f"M:{calls.get('medium_confidence', 0)} "
        f"L:{calls.get('low_confidence', 0)})",
    )

    gov = summary.get("governance", {})
    if gov:
        table.add_row("Plans ingested", str(gov.get("plans", 0)))
        table.add_row("Contracts ingested", str(gov.get("contracts", 0)))
        table.add_row("Learnings ingested", str(gov.get("learnings", 0)))
        table.add_row("Impact edges", str(gov.get("impact_edges", 0)))

    warnings = store.node_count("ParsingWarning")
    table.add_row("Parsing warnings", str(warnings))
    table.add_row("Duration", f"{summary.get('elapsed_seconds', 0)}s")
    table.add_row("Phases", ", ".join(summary.get("phases_completed", [])))

    console.print(table)
    console.print()
