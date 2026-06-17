"""Ingestion pipeline orchestrator.

Runs indexing phases in sequence with transaction-per-phase safety.
Reports a quality summary on completion.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.duckpgq_schema import SCHEMA_VERSION
from agentscaffold.graph.symbol_table import SymbolTable


def _open_store_for_pipeline(db_path: Path, backend_name: str) -> GraphBackend:
    """Instantiate the backend for pipeline writes."""
    return DuckPGQBackend(db_path)


def _migrate_on_version_change(
    store: GraphBackend,
    db_path: Path,
    stored_version: int,
    *,
    force: bool = False,
) -> None:
    """Preserve governance across a schema-version rebuild (fail-closed).

    Exports preserved governance (review findings, backlog items, sessions and
    their edges) to ``.scaffold/graph_export_v{old}.json`` BEFORE the
    destructive rebuild. If the export fails, the rebuild is aborted and the
    existing graph is left intact so user/agent knowledge is never lost. After a
    successful export + rebuild, compatible governance is re-imported; if the
    columns are schema-incompatible the export file is kept and the user is
    warned rather than silently dropping data.

    If ``force`` is True (``scaffold index --force-rebuild``), an export failure
    no longer aborts: a prominent warning is emitted and the rebuild proceeds,
    discarding the preserved governance. This is the explicit, opt-in escape
    hatch for an unrecoverable export error.
    """
    console.print(
        f"[yellow]Graph schema changed (v{stored_version} -> v{SCHEMA_VERSION}). "
        "Rebuilding...[/yellow]"
    )

    # Backends without governance export/import fall back to the legacy rebuild.
    if not (hasattr(store, "export_governance") and hasattr(store, "import_governance")):
        store.clear_all()
        return

    export_path = db_path.parent / f"graph_export_v{stored_version}.json"

    # Fail-closed by default: the export must succeed before we destroy anything.
    try:
        data = store.export_governance()
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Governance export failed before schema rebuild: %s", exc, exc_info=True)
        if force:
            logger.warning("Proceeding with forced rebuild despite export failure: %s", exc)
            console.print(
                f"[red]WARNING: governance export failed ({exc}), but --force-rebuild was "
                "given. Rebuilding anyway -- preserved findings, sessions, and backlog items "
                "will be permanently discarded.[/red]"
            )
            store.clear_all()
            return
        raise RuntimeError(
            f"Aborting schema rebuild (v{stored_version} -> v{SCHEMA_VERSION}): failed to "
            "export preserved governance. The existing graph was left intact -- no data was "
            f"deleted.\n"
            f"  Graph file:       {db_path}\n"
            f"  Underlying error: {exc}\n"
            "How to resolve:\n"
            "  1. This is usually a transient I/O problem: the disk is full, "
            f"'{db_path.parent}' is read-only, or the graph file is open in another process. "
            "Fix the underlying cause (see the full traceback in the logs) and re-run "
            "'scaffold index'.\n"
            "  2. If you do not need the existing findings, sessions, and backlog items, "
            "re-run with 'scaffold index --force-rebuild' to rebuild anyway (this discards "
            f"that preserved governance), or delete the graph file ('{db_path}') manually."
        ) from exc

    # Knowledge is safely on disk -- now rebuild from scratch.
    store.clear_all()

    try:
        result = store.import_governance(data)
    except Exception as exc:
        logger.error("Governance re-import failed after rebuild: %s", exc)
        console.print(
            f"[yellow]Rebuilt the graph, but governance re-import failed ({exc}). "
            f"Preserved data kept at {export_path}.[/yellow]"
        )
        return

    if result.get("compatible", True):
        restored = sum(result.get("imported", {}).values())
        console.print(f"[green]Preserved {restored} governance records across the rebuild.[/green]")
    else:
        console.print(
            "[yellow]Some governance was schema-incompatible and was not re-imported; "
            f"export kept at {export_path}. Skipped: {result.get('skipped')}[/yellow]"
        )


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
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Execute the full indexing pipeline.

    Returns a summary dict with quality metrics.
    """
    root = root.resolve()
    graph_config = config.graph if config else None

    # Resolve the DB path against the project root (Plan 221) so the index-time
    # location matches what open_graph uses at query time. A relative db_path
    # anchors to the nearest scaffold.yaml/.git (falling back to the scan root)
    # rather than the bare working directory; an absolute db_path is honored.
    from agentscaffold.paths import resolve_db_path

    db_path = resolve_db_path(config, start=root)

    # Plan 223: note whether the cache exists before we build. On an ephemeral
    # box (no cache) the governance phase restores findings/sessions/backlog from
    # the committed artifact; we surface that so the operator sees the rebuild
    # reconstructed durable knowledge from git rather than starting empty.
    cache_existed = db_path.is_file()

    backend_name = (graph_config.backend if graph_config else None) or "duckpgq"
    t0 = time.monotonic()

    store = _open_store_for_pipeline(db_path, backend_name)

    # Schema version check (backend-agnostic via schema_current())
    if not store.schema_current():
        stored_version = store.schema_version()
        if stored_version is not None:
            _migrate_on_version_change(store, db_path, stored_version, force=force_rebuild)

    store.init_schema()
    phases_completed: list[str] = []
    summary: dict[str, Any] = {}

    # Plan 225: in a multi-project workspace, tag every write with this project
    # and scope clears to it so re-indexing one project never touches siblings.
    # Single-project repos resolve to None -- the choke point is a no-op.
    from agentscaffold.paths import load_workspace as _load_workspace

    _workspace = _load_workspace(root)
    write_project: str | None = None
    if _workspace.is_multi_project:
        from agentscaffold.graph.scoping import current_project_name

        write_project = current_project_name(root)
    store.set_write_project(write_project)

    # Incremental mode: compute changeset and only process changed files
    if incremental and store.schema_current():
        return _run_incremental(store, root, graph_config, t0, embeddings, config=config)

    # Check for resumable state or failed prior run
    if not incremental:
        pipeline_state = store.get_pipeline_state()
        if pipeline_state["state"].startswith("failed"):
            failed_phase = pipeline_state["state"].split(":", 1)[-1]
            console.print(
                f"[yellow]Previous index failed during '{failed_phase}'. "
                "Clearing derived data and starting fresh "
                "(review findings and sessions preserved)...[/yellow]"
            )
            store.clear_derived(project=write_project)
        elif pipeline_state["state"] == "complete":
            console.print(
                "[dim]Full re-index: clearing derived data "
                "(review findings and sessions preserved)...[/dim]"
            )
            store.clear_derived(project=write_project)
        elif pipeline_state["state"] == "partial":
            phases_completed = pipeline_state["phases_completed"]
            console.print(
                f"[yellow]Resuming from partial index. "
                f"Completed phases: {phases_completed}[/yellow]"
            )

    symbol_table = SymbolTable()

    # Compute total phases
    total_phases = 4  # structure, parsing, resolution, governance
    if embeddings:
        total_phases += 1
    total_phases += 1  # communities phase is always included

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
            f"[bold]Phase 3/{total_phases}: Resolution[/bold] -- resolving imports and calls..."
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

            from agentscaffold.graph.config_refs import process_config_references

            config_ref_result = process_config_references(store, root)
            summary["config_refs"] = config_ref_result

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
            console.print(
                f"  Config refs: {config_ref_result['edges']} edges "
                f"from {config_ref_result['config_files']} config file(s)"
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

    # Phase 4: Governance (plans, contracts, learnings, studies, ADRs, spikes)
    if "governance" not in phases_completed:
        console.print(
            f"[bold]Phase 4/{total_phases}: Governance[/bold] "
            "-- ingesting plans, contracts, learnings, studies, ADRs, spikes..."
        )
        try:
            from agentscaffold.graph.governance import process_governance

            gov_result = process_governance(store, root, config=config)
            summary["governance"] = gov_result
            phases_completed.append("governance")
            store.update_pipeline_state("complete", phases_completed)
            _write_governance_fingerprint(store, root, config)
            console.print(
                f"  {gov_result['plans']} plans, "
                f"{gov_result['contracts']} contracts, "
                f"{gov_result['learnings']} learnings, "
                f"{gov_result.get('studies', 0)} studies, "
                f"{gov_result.get('adrs', 0)} ADRs, "
                f"{gov_result.get('spikes', 0)} spikes, "
                f"{gov_result.get('findings', 0)} findings, "
                f"{gov_result['impact_edges']} impact edges, "
                f"{gov_result.get('dependency_edges', 0)} dep edges"
            )
        except Exception as exc:
            logger.error("Phase 4 (governance) failed: %s", exc)
            store.add_parsing_warning(
                "pw::pipeline::governance", "", "governance", str(exc), "error"
            )
            # Governance failure is non-fatal; code graph is still usable

    # Phase 5 (optional): Community detection
    if "communities" not in phases_completed:
        phase_num = len(phases_completed) + 1
        console.print(
            f"[bold]Phase {phase_num}/{total_phases}: Communities[/bold] "
            "-- detecting module clusters..."
        )
        try:
            from agentscaffold.graph.communities import detect_communities

            comm_result = detect_communities(store)
            summary["communities"] = comm_result
            phases_completed.append("communities")
            console.print(
                f"  {comm_result['communities']} communities detected, "
                f"{comm_result['files_assigned']} files assigned"
            )
        except Exception as exc:
            logger.error("Community detection failed: %s", exc)
            store.add_parsing_warning(
                "pw::pipeline::communities",
                "",
                "communities",
                str(exc),
                "warning",
            )

    # Phase 6 (optional): Embeddings
    if embeddings and "embeddings" not in phases_completed:
        phase_num = len(phases_completed) + 1
        console.print(
            f"[bold]Phase {phase_num}/{total_phases}: Embeddings[/bold] "
            "-- generating code vectors..."
        )
        try:
            from agentscaffold.graph.embeddings import generate_embeddings

            emb_result = generate_embeddings(store, root=root)
            summary["embeddings"] = emb_result
            phases_completed.append("embeddings")
            total = sum(emb_result.values())
            console.print(f"  {total} nodes embedded across {len(emb_result)} tables")
        except Exception as exc:
            logger.error("Embedding generation failed: %s", exc)
            store.add_parsing_warning(
                "pw::pipeline::embeddings",
                "",
                "embeddings",
                str(exc),
                "warning",
            )

    store.update_pipeline_state("complete", phases_completed)

    elapsed = time.monotonic() - t0
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["phases_completed"] = phases_completed

    # Plan 223: report governance restored from the committed artifact on a fresh
    # build (e.g. ephemeral devbox or after a deleted cache).
    restored = summary.get("governance", {}).get("governance_restored", 0)
    summary["restored_from_artifact"] = (not cache_existed) and restored > 0
    if summary["restored_from_artifact"]:
        console.print(
            f"[green]Restored {restored} governance record(s) "
            "(findings/sessions/backlog) from the committed artifact.[/green]"
        )

    # Print final summary
    _print_summary(summary, store)

    store.close()
    return summary


def _governance_fp_path(store: GraphBackend) -> Path | None:
    """Return the path to the governance fingerprint sidecar, or None.

    The sidecar lives alongside the graph DB file. Returns None for in-memory
    backends or backends that do not expose a DB path, in which case the caller
    treats governance as always-changed (safe default).
    """
    db_path = getattr(store, "_db_path", None)
    if db_path is None or str(db_path) == ":memory:":
        return None
    return Path(db_path).parent / "governance.fingerprint"


def _write_governance_fingerprint(
    store: GraphBackend, root: Path, config: ScaffoldConfig | None
) -> None:
    """Persist the current governance fingerprint to the sidecar (best-effort)."""
    fp_path = _governance_fp_path(store)
    if fp_path is None:
        return
    try:
        from agentscaffold.graph.governance import governance_source_files
        from agentscaffold.graph.incremental import governance_fingerprint

        fp_path.write_text(governance_fingerprint(governance_source_files(root, config)))
    except OSError as exc:
        logger.warning("Could not write governance fingerprint: %s", exc)


def _run_incremental(
    store: GraphBackend,
    root: Path,
    graph_config: Any,
    t0: float,
    embeddings: bool = False,
    config: ScaffoldConfig | None = None,
) -> dict[str, Any]:
    """Run incremental index: only process changed files."""
    from agentscaffold.graph.incremental import (
        add_file_node,
        compute_changeset,
        remove_file_nodes,
    )

    console.print("[bold]Incremental index[/bold] -- computing changeset...")

    changeset = compute_changeset(store, root, graph_config)
    added = changeset["added"]
    modified = changeset["modified"]
    deleted = changeset["deleted"]
    unchanged = changeset["unchanged"]

    console.print(
        f"  {len(added)} added, {len(modified)} modified, "
        f"{len(deleted)} deleted, {unchanged} unchanged"
    )

    summary: dict[str, Any] = {"changeset": changeset}

    # Governance freshness gate. Governance documents (plans, contracts,
    # learnings, etc.) are markdown that the code changeset cannot see, so we
    # fingerprint them separately. A doc-only edit changes the fingerprint and
    # forces a governance refresh; a code-only edit leaves it unchanged and
    # skips the ~2.7s governance reingest.
    from agentscaffold.graph.governance import governance_source_files
    from agentscaffold.graph.incremental import governance_fingerprint

    gov_files = governance_source_files(root, config)
    current_gov_fp = governance_fingerprint(gov_files)
    fp_path = _governance_fp_path(store)
    prior_gov_fp = None
    if fp_path is not None and fp_path.exists():
        try:
            prior_gov_fp = fp_path.read_text().strip()
        except OSError:
            prior_gov_fp = None
    gov_changed = prior_gov_fp != current_gov_fp

    if not added and not modified and not deleted and not gov_changed:
        console.print("[green]Graph is up to date. Nothing to do.[/green]")
        elapsed = time.monotonic() - t0
        summary["elapsed_seconds"] = round(elapsed, 1)
        summary["phases_completed"] = ["incremental"]
        store.close()
        return summary

    # Remove deleted files
    if deleted:
        removed = remove_file_nodes(store, deleted)
        console.print(f"  Removed {removed} deleted file(s)")

    # Remove and re-add modified files (to refresh definitions)
    if modified:
        remove_file_nodes(store, modified)
        for path in modified:
            add_file_node(store, root, path)
        console.print(f"  Refreshed {len(modified)} modified file(s)")

    # Add new files
    if added:
        for path in added:
            add_file_node(store, root, path)
        console.print(f"  Added {len(added)} new file(s)")

    # Re-parse only changed files
    changed_files = set(added) | set(modified)
    if changed_files:
        console.print(f"  Re-parsing {len(changed_files)} file(s)...")
        symbol_table = SymbolTable()
        _rebuild_symbol_table(store, symbol_table)

        from agentscaffold.graph.parsing import process_parsing

        parse_result = process_parsing(store, root, symbol_table, file_paths=changed_files)
        summary["parsing"] = parse_result

        from agentscaffold.graph.calls import process_calls
        from agentscaffold.graph.imports import process_imports

        import_result = process_imports(store, root, symbol_table)
        summary["imports"] = import_result

        call_result = process_calls(store, root, symbol_table)
        summary["calls"] = call_result

        # Config references can change when a config file is edited or when a
        # referenced code file is refreshed (its incoming edges were dropped with
        # the file node). Reprocessing is cheap and idempotent, so re-run whenever
        # any file changed.
        from agentscaffold.graph.config_refs import process_config_references

        config_ref_result = process_config_references(store, root)
        summary["config_refs"] = config_ref_result
        console.print(
            f"  Config refs: {config_ref_result['edges']} edges "
            f"from {config_ref_result['config_files']} config file(s)"
        )

    # Refresh governance artifacts (plans, contracts, learnings, studies, ADRs,
    # spikes) only when they actually changed, or when files were added/deleted
    # (which can rewire plan-impact / learning-relates-to edges). A pure code
    # content edit that touches no governance doc skips this ~2.7s reingest.
    # We clear governance first so stale edges do not linger when a document
    # changes, then re-ingest. Edges are idempotent on (src, dst), governance
    # nodes use deterministic ids, and clear_governance preserves ReviewFinding
    # and its file/func links, so this is safe to repeat.
    if gov_changed or added or deleted:
        try:
            from agentscaffold.graph.governance import process_governance

            store.clear_governance(project=store.write_project)
            gov_result = process_governance(store, root, config=config)
            summary["governance"] = gov_result
            console.print(
                f"  Governance: {gov_result['plans']} plans, "
                f"{gov_result['contracts']} contracts, "
                f"{gov_result['learnings']} learnings, "
                f"{gov_result.get('findings', 0)} findings, "
                f"{gov_result['impact_edges']} impact edges"
            )
            if fp_path is not None:
                try:
                    fp_path.write_text(current_gov_fp)
                except OSError as exc:
                    logger.warning("Could not write governance fingerprint: %s", exc)
        except Exception as exc:
            logger.error("Incremental governance refresh failed: %s", exc)
            store.add_parsing_warning(
                "pw::pipeline::governance", "", "governance", str(exc), "warning"
            )
    else:
        console.print("  Governance unchanged; skipping refresh")

    # Re-run communities
    from agentscaffold.graph.communities import detect_communities

    comm_result = detect_communities(store)
    summary["communities"] = comm_result

    # Re-run embeddings if requested
    if embeddings:
        try:
            from agentscaffold.graph.embeddings import generate_embeddings

            emb_result = generate_embeddings(store, root=root)
            summary["embeddings"] = emb_result
        except ImportError:
            pass

    store.update_pipeline_state("complete", ["incremental"])

    elapsed = time.monotonic() - t0
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["phases_completed"] = ["incremental"]

    _print_summary(summary, store)
    store.close()
    return summary


def _rebuild_symbol_table(store: GraphBackend, symbol_table: SymbolTable) -> None:
    """Rebuild symbol table from existing graph data (for pipeline resumption)."""
    from agentscaffold.graph.query_compat import ql  # noqa: PLC0415
    from agentscaffold.graph.symbol_table import SymbolEntry  # noqa: PLC0415

    for row in ql(
        store,
        sql=(
            'SELECT t.f_id AS "f.id", t.f_path AS "f.path",'
            ' t.fn_id AS "fn.id", t.fn_name AS "fn.name",'
            ' t.fn_isExported AS "fn.isExported", t.fn_startLine AS "fn.startLine"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (f:File)-[e:DEFINES_FUNCTION]->(fn:Function)"
            " COLUMNS (f.id AS f_id, f.path AS f_path,"
            " fn.id AS fn_id, fn.name AS fn_name,"
            " fn.isExported AS fn_isExported, fn.startLine AS fn_startLine)) t"
        ),
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

    for row in ql(
        store,
        sql=(
            'SELECT t.f_id AS "f.id", t.f_path AS "f.path",'
            ' t.c_id AS "c.id", t.c_name AS "c.name",'
            ' t.c_isExported AS "c.isExported", t.c_startLine AS "c.startLine"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (f:File)-[e:DEFINES_CLASS]->(c:Class)"
            " COLUMNS (f.id AS f_id, f.path AS f_path,"
            " c.id AS c_id, c.name AS c_name,"
            " c.isExported AS c_isExported, c.startLine AS c_startLine)) t"
        ),
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

    for row in ql(
        store,
        sql=(
            'SELECT t.m_id AS "m.id", t.m_name AS "m.name",'
            ' t.m_className AS "m.className", t.m_filePath AS "m.filePath",'
            ' t.m_isExported AS "m.isExported", t.m_startLine AS "m.startLine"'
            " FROM GRAPH_TABLE(agentscaffold_graph"
            " MATCH (c:Class)-[e:HAS_METHOD]->(m:Method)"
            " COLUMNS (m.id AS m_id, m.name AS m_name,"
            " m.className AS m_className, m.filePath AS m_filePath,"
            " m.isExported AS m_isExported, m.startLine AS m_startLine)) t"
        ),
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
    store: GraphBackend,
) -> dict[str, Any]:
    """Build summary dict even for partial/failed runs."""
    summary["elapsed_seconds"] = round(time.monotonic() - t0, 1)
    summary["phases_completed"] = phases_completed
    _print_summary(summary, store)
    store.close()
    return summary


def _print_summary(summary: dict[str, Any], store: GraphBackend) -> None:
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

    config_refs = summary.get("config_refs", {})
    if config_refs:
        table.add_row("Config reference edges", str(config_refs.get("edges", 0)))

    gov = summary.get("governance", {})
    if gov:
        table.add_row("Plans ingested", str(gov.get("plans", 0)))
        table.add_row("Contracts ingested", str(gov.get("contracts", 0)))
        table.add_row("Learnings ingested", str(gov.get("learnings", 0)))
        table.add_row("Studies ingested", str(gov.get("studies", 0)))
        table.add_row("ADRs ingested", str(gov.get("adrs", 0)))
        table.add_row("Spikes ingested", str(gov.get("spikes", 0)))
        table.add_row("Impact edges", str(gov.get("impact_edges", 0)))
        table.add_row("Dependency edges", str(gov.get("dependency_edges", 0)))

    comm = summary.get("communities", {})
    if comm:
        table.add_row("Communities", str(comm.get("communities", 0)))
        table.add_row("Files in communities", str(comm.get("files_assigned", 0)))
        sizes = comm.get("sizes", [])
        if sizes:
            table.add_row("Largest community", str(sizes[0]))

    emb = summary.get("embeddings", {})
    if emb:
        total_emb = sum(emb.values())
        table.add_row("Nodes embedded", str(total_emb))

    warnings = store.node_count("ParsingWarning")
    table.add_row("Parsing warnings", str(warnings))
    table.add_row("Duration", f"{summary.get('elapsed_seconds', 0)}s")
    table.add_row("Phases", ", ".join(summary.get("phases_completed", [])))

    console.print(table)
    console.print()
