"""Tests for Plan 237: architecture-layer and contract-to-file graph ingestion.

Covers the architecture-doc parser, the file->layer matcher, and the ingestion
that creates ArchitectureLayer nodes + BELONGS_TO_LAYER / CONTRACT_ABOUT_FILE
edges (including placeholder skipping and idempotent re-runs).
"""

from __future__ import annotations

from pathlib import Path

from agentscaffold.graph.architecture import (
    ArchitectureLayerDef,
    match_layer_for_file,
    parse_architecture_layers,
)

# ---------------------------------------------------------------------------
# parse_architecture_layers
# ---------------------------------------------------------------------------

_DOC = """# System Architecture

## Layer Framework

## Layer 1: Source Parsing

### Current State

Parses source into a graph. Second sentence.

### Components

| Component | Status | Plan(s) | Paths | Notes |
|-----------|--------|---------|-------|-------|
| Parser | Stable | 149 | `graph/parsing.py` | driver |
| Pipeline | Stable | 173 | `graph/pipeline.py`, `graph/incremental.py` | orchestration |

## Layer 2: Store

### Current State

Holds the graph.

### Components

| Component | Status | Plan(s) | Paths | Notes |
|-----------|--------|---------|-------|-------|
| Backend | Stable | 149 | `graph/` | duckdb backend |

## Layer 3: [Name]

### Current State

[Describe current implementation status]

### Components

| Component | Status | Plan(s) | Paths | Notes |
|-----------|--------|---------|-------|-------|
|           |        |         |       |       |
"""


def test_parse_extracts_populated_layers_and_skips_placeholder():
    layers = parse_architecture_layers(_DOC)
    numbers = [layer.number for layer in layers]
    assert numbers == [1, 2]  # Layer 3 ([Name]) skipped
    assert layers[0].name == "Source Parsing"
    assert layers[0].description.startswith("Parses source into a graph.")
    # Second paragraph sentence is included within the first paragraph run.
    assert "Second sentence." in layers[0].description


def test_parse_extracts_path_globs():
    layers = parse_architecture_layers(_DOC)
    assert layers[0].path_patterns == [
        "graph/parsing.py",
        "graph/pipeline.py",
        "graph/incremental.py",
    ]
    assert layers[1].path_patterns == ["graph/"]


def test_parse_prose_layout_yields_nonempty_patterns():
    """Plan 261: Components tables without a Paths column still extract paths."""
    fixture = Path(__file__).parent / "fixtures" / "architecture_prose_layout.md"
    layers = parse_architecture_layers(
        fixture.read_text(),
        known_top_level_dirs=["data", "libs", "pipeline", "apps"],
    )
    assert [layer.number for layer in layers] == [1, 2, 3, 4, 5, 6]
    for layer in layers:
        assert layer.path_patterns, f"layer {layer.number} produced no patterns"
    assert layers[2].provenance == "curated"  # **Location**:
    assert layers[3].provenance == "curated"  # **Paths**:
    assert layers[1].provenance == "inferred"


def test_parse_empty_or_placeholder_only_doc():
    assert parse_architecture_layers("# nothing here") == []
    placeholder = "## Layer 1: [Name]\n### Current State\n[x]\n"
    assert parse_architecture_layers(placeholder) == []


# ---------------------------------------------------------------------------
# match_layer_for_file
# ---------------------------------------------------------------------------


def _layers() -> list[ArchitectureLayerDef]:
    return [
        ArchitectureLayerDef(1, "Parse", path_patterns=["agentscaffold/graph/parsing.py"]),
        ArchitectureLayerDef(2, "Store", path_patterns=["agentscaffold/graph/"]),
    ]


def test_match_most_specific_wins():
    layers = _layers()
    # The exact file glob (Layer 1) is more specific than the dir glob (Layer 2).
    m = match_layer_for_file("src/agentscaffold/graph/parsing.py", layers)
    assert m is not None and m.number == 1


def test_match_directory_glob():
    layers = _layers()
    m = match_layer_for_file("src/agentscaffold/graph/duckpgq_backend.py", layers)
    assert m is not None and m.number == 2


def test_match_suffix_tolerates_src_prefix():
    layers = _layers()
    # Both with and without src/ prefix resolve to Layer 1.
    assert match_layer_for_file("agentscaffold/graph/parsing.py", layers).number == 1
    assert match_layer_for_file("src/agentscaffold/graph/parsing.py", layers).number == 1


def test_match_no_glob_returns_none():
    layers = _layers()
    assert match_layer_for_file("docs/readme.md", layers) is None
    assert match_layer_for_file("libs/other/thing.py", layers) is None


# ---------------------------------------------------------------------------
# _ingest_architecture_layers (integration on an in-memory store)
# ---------------------------------------------------------------------------


def _store():
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    s = DuckPGQBackend(":memory:")
    s.init_schema()
    return s


def _seed_files(store, paths):
    file_id_map = {}
    for i, p in enumerate(paths):
        fid = f"file::{i}"
        store.create_node("File", {"id": fid, "path": p, "language": "python"})
        file_id_map[p] = fid
    return file_id_map


def test_ingest_creates_layers_and_edges(tmp_path):
    from agentscaffold.graph.governance import _ingest_architecture_layers
    from agentscaffold.review.queries import get_file_layer

    doc = tmp_path / "system_architecture.md"
    doc.write_text(_DOC)

    store = _store()
    try:
        file_id_map = _seed_files(
            store,
            [
                "src/agentscaffold/graph/parsing.py",
                "src/agentscaffold/graph/duckpgq_backend.py",
                "docs/readme.md",
            ],
        )
        layer_count, edge_count = _ingest_architecture_layers(store, doc, file_id_map)
        assert layer_count == 2
        assert edge_count == 2  # parsing.py -> L1, backend.py -> L2; readme unmatched

        parsing_layer = get_file_layer(store, "src/agentscaffold/graph/parsing.py")
        assert parsing_layer is not None
        assert parsing_layer["l.number"] == 1

        backend_layer = get_file_layer(store, "src/agentscaffold/graph/duckpgq_backend.py")
        assert backend_layer is not None
        assert backend_layer["l.number"] == 2

        assert get_file_layer(store, "docs/readme.md") is None
    finally:
        store.close()


def test_ingest_prose_layout_creates_nonzero_edges(tmp_path):
    """Regression Plan 237 never made: layers defined => BELONGS_TO_LAYER > 0."""
    from agentscaffold.graph.governance import _ingest_architecture_layers

    fixture = Path(__file__).parent / "fixtures" / "architecture_prose_layout.md"
    doc = tmp_path / "system_architecture.md"
    doc.write_text(fixture.read_text())

    store = _store()
    try:
        file_id_map = _seed_files(
            store,
            [
                "data/adapters/polygon.py",
                "libs/strategies/momentum.py",
                "libs/selection/selector.py",
                "pipeline/portfolio_construction.py",
                "libs/risk/posture.py",
                "apps/execution/router.py",
                "docs/readme.md",
            ],
        )
        layer_count, edge_count = _ingest_architecture_layers(
            store,
            doc,
            file_id_map,
            known_top_level_dirs=["data", "libs", "pipeline", "apps"],
        )
        assert layer_count == 6
        assert edge_count > 0
        rows = store.query("SELECT src, dst FROM BELONGS_TO_LAYER")
        assert len(rows) == edge_count
        # At most one layer per file.
        srcs = [r["src"] for r in rows]
        assert len(srcs) == len(set(srcs))
    finally:
        store.close()


def test_layer_with_no_paths_emits_warning(tmp_path):
    from agentscaffold.graph.governance import _ingest_architecture_layers

    doc = tmp_path / "system_architecture.md"
    doc.write_text(
        "## Layer 1: Empty\n\n### Purpose\nNo paths here.\n\n"
        "## Layer 2: Has Paths\n\n**Paths**: `libs/foo/`\n"
    )
    store = _store()
    try:
        _ingest_architecture_layers(
            store, doc, _seed_files(store, ["libs/foo/bar.py"]), known_top_level_dirs=["libs"]
        )
        warns = store.query(
            "SELECT phase, message, severity FROM ParsingWarning WHERE phase = 'governance:layers'"
        )
        empty = [w for w in warns if "Layer 1" in w["message"] and "zero path" in w["message"]]
        inferred = [w for w in warns if w["severity"] == "info"]
        assert empty
        assert not inferred  # layer 2 is curated via **Paths**
    finally:
        store.close()


def test_ingest_missing_doc_is_noop(tmp_path):
    from agentscaffold.graph.governance import _ingest_architecture_layers

    store = _store()
    try:
        file_id_map = _seed_files(store, ["src/agentscaffold/graph/parsing.py"])
        assert _ingest_architecture_layers(store, tmp_path / "absent.md", file_id_map) == (0, 0)
    finally:
        store.close()


def test_ingest_is_idempotent(tmp_path):
    from agentscaffold.graph.governance import _ingest_architecture_layers

    doc = tmp_path / "system_architecture.md"
    doc.write_text(_DOC)

    store = _store()
    try:
        file_id_map = _seed_files(
            store,
            ["src/agentscaffold/graph/parsing.py", "src/agentscaffold/graph/backend.py"],
        )
        first = _ingest_architecture_layers(store, doc, file_id_map)
        second = _ingest_architecture_layers(store, doc, file_id_map)
        assert first == second

        layer_rows = store.query("SELECT id FROM ArchitectureLayer")
        assert len(layer_rows) == 2  # no duplicate layer nodes on re-run
    finally:
        store.close()
