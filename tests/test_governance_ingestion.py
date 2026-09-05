"""Plan 261: governance ingestion must not parse a populated source to zero rows in silence.

The durable half is a declared artifact registry plus a zero-row wrapper. The
convenient half (bold-bullet learnings, prose-layout layers) is covered here
and in ``test_layer_ingestion.py``.

Evidence and working environment:
``docs/ai/graph_population_evidence_261-265.md`` in the governance repo.
"""

from __future__ import annotations

from pathlib import Path

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.governance import (
    ARTIFACT_REGISTRY,
    REGISTERED_PARSERS,
    _parse_learnings,
    process_governance,
)

FIXTURES = Path(__file__).parent / "fixtures"
BOLD_BULLET = FIXTURES / "learnings_bold_bullet.md"
SAMPLE_LEARNINGS = FIXTURES / "sample_repo" / "docs" / "ai" / "state" / "learnings_tracker.md"


def _store() -> DuckPGQBackend:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    return store


def _warnings(store: DuckPGQBackend, *, phase: str | None = None) -> list[dict]:
    rows = store.query(
        "SELECT id, filePath, phase, message, severity FROM ParsingWarning ORDER BY phase, filePath"
    )
    if phase is None:
        return list(rows or [])
    return [r for r in (rows or []) if r["phase"] == phase]


def _write_plan(root: Path, name: str, body: str) -> Path:
    plans = root / "docs" / "ai" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / name
    path.write_text(body)
    return path


# ---------------------------------------------------------------------------
# Whole-file shape
# ---------------------------------------------------------------------------


def test_nonempty_learnings_file_that_parses_to_zero_rows_warns(tmp_path: Path):
    """Format-drift case: L-ids are present, none of the four table/list regexes match."""
    tracker = tmp_path / "docs" / "ai" / "state" / "learnings_tracker.md"
    tracker.parent.mkdir(parents=True)
    tracker.write_text(
        "# Learnings\n\n"
        "The tracker drifted to prose.\n\n"
        "- **L249-17 (2026-08-06, Plan 249 Step F6): a real learning id is here.**\n"
        "  Narrative that none of the original parsers can read.\n"
    )

    store = _store()
    try:
        process_governance(store, tmp_path)
        warns = _warnings(store, phase="governance:learnings")
        # Before the fifth format lands this is the defect; after it, rows exist
        # and this file should produce learnings rather than a warning. Either
        # outcome is asserted by the paired tests below -- this test documents
        # the warning contract when rows are zero *and* L-ids are visible.
        learnings = store.query("SELECT learningId FROM Learning")
        if learnings:
            assert warns == []
            assert any(r["learningId"] == "L249-17" for r in learnings)
        else:
            assert len(warns) == 1
            assert warns[0]["filePath"] == str(tracker)
            assert "expected format" in warns[0]["message"].lower()
    finally:
        store.close()


def test_absent_learnings_file_produces_no_warning(tmp_path: Path):
    store = _store()
    try:
        process_governance(store, tmp_path)
        assert _warnings(store, phase="governance:learnings") == []
    finally:
        store.close()


def test_empty_learnings_file_produces_no_warning(tmp_path: Path):
    tracker = tmp_path / "docs" / "ai" / "state" / "learnings_tracker.md"
    tracker.parent.mkdir(parents=True)
    tracker.write_text("")

    store = _store()
    try:
        process_governance(store, tmp_path)
        assert _warnings(store, phase="governance:learnings") == []
    finally:
        store.close()


def test_template_learnings_file_without_ids_produces_no_warning(tmp_path: Path):
    """Fresh ``scaffold init`` tracker: instructions, no L-ids. Silence is correct."""
    tracker = tmp_path / "docs" / "ai" / "state" / "learnings_tracker.md"
    tracker.parent.mkdir(parents=True)
    tracker.write_text(
        "# Learnings Tracker\n\n## Pending Review\n\n"
        "<!-- Format: - [Plan XXX] Learning description -->\n\n(empty)\n"
    )

    store = _store()
    try:
        process_governance(store, tmp_path)
        assert _warnings(store, phase="governance:learnings") == []
        assert store.query("SELECT id FROM Learning") == []
    finally:
        store.close()


def test_populated_table_learnings_produce_rows_and_no_warning(tmp_path: Path):
    tracker = tmp_path / "docs" / "ai" / "state" / "learnings_tracker.md"
    tracker.parent.mkdir(parents=True)
    tracker.write_text(SAMPLE_LEARNINGS.read_text())

    store = _store()
    try:
        result = process_governance(store, tmp_path)
        assert result["learnings"] >= 4
        assert _warnings(store, phase="governance:learnings") == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Per-file shape
# ---------------------------------------------------------------------------


def test_empty_plans_directory_produces_no_warning(tmp_path: Path):
    (tmp_path / "docs" / "ai" / "plans").mkdir(parents=True)
    store = _store()
    try:
        process_governance(store, tmp_path)
        assert _warnings(store, phase="governance:plans") == []
    finally:
        store.close()


def test_one_unparseable_plan_file_warns_on_that_file_only(tmp_path: Path):
    _write_plan(tmp_path, "307-ok.md", "# Plan 307: Fine\n\n| Status | Draft |\n")
    bad = _write_plan(tmp_path, "notes-without-number.md", "# Not a plan\n\nProse only.\n")
    _write_plan(tmp_path, "308-also-ok.md", "# Plan 308: Also fine\n\n| Status | Draft |\n")

    store = _store()
    try:
        result = process_governance(store, tmp_path)
        assert result["plans"] == 2
        warns = _warnings(store, phase="governance:plans")
        assert len(warns) == 1
        assert warns[0]["filePath"] == str(bad)
        assert str(tmp_path / "docs" / "ai" / "plans") != warns[0]["filePath"]
    finally:
        store.close()


def test_all_parseable_plan_files_produce_no_warning(tmp_path: Path):
    _write_plan(tmp_path, "307-ok.md", "# Plan 307: Fine\n\n| Status | Draft |\n")
    store = _store()
    try:
        result = process_governance(store, tmp_path)
        assert result["plans"] == 1
        assert _warnings(store, phase="governance:plans") == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Opportunistic shape (section 4.6 counter-example)
# ---------------------------------------------------------------------------


def test_plan_without_category_markers_produces_no_findings_warning(tmp_path: Path):
    _write_plan(
        tmp_path,
        "261-prose-review.md",
        "# Plan 261: Prose review\n\n"
        "## Appendix A\n\n"
        "The review is written as prose per AGENTS.md and never uses [CATEGORY] markers.\n",
    )
    store = _store()
    try:
        result = process_governance(store, tmp_path)
        assert result["plans"] == 1
        assert result["findings"] == 0
        assert _warnings(store, phase="governance:findings") == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Coverage and noise guards
# ---------------------------------------------------------------------------


def test_every_ingested_parser_has_a_registry_row():
    expected = {
        "learnings",
        "layers",
        "plans",
        "contracts",
        "adrs",
        "studies",
        "spikes",
        "findings",
    }
    assert set(ARTIFACT_REGISTRY) == expected
    assert set(REGISTERED_PARSERS.values()) == expected
    for parser_name, artifact in REGISTERED_PARSERS.items():
        assert artifact in ARTIFACT_REGISTRY
        if parser_name == "parse_architecture_layers":
            from agentscaffold.graph import architecture

            assert hasattr(architecture, parser_name)
        else:
            from agentscaffold.graph import governance

            assert hasattr(governance, parser_name)


def test_fresh_project_layout_produces_zero_warnings(tmp_path: Path):
    """Noise guard: empty dirs plus init-shaped templates must stay silent."""
    (tmp_path / "docs" / "ai" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "ai" / "contracts").mkdir(parents=True)
    (tmp_path / "docs" / "ai" / "adrs").mkdir(parents=True)
    (tmp_path / "docs" / "ai" / "spikes").mkdir(parents=True)
    (tmp_path / "docs" / "studies").mkdir(parents=True)
    (tmp_path / "docs" / "ai" / "state").mkdir(parents=True)
    (tmp_path / "docs" / "ai" / "state" / "learnings_tracker.md").write_text(
        "# Learnings Tracker\n\n## Pending Review\n\n(empty)\n"
    )
    (tmp_path / "docs" / "ai" / "system_architecture.md").write_text(
        "# System Architecture\n\n## Layer 1: [Name]\n\n### Current State\n\n[x]\n"
    )

    store = _store()
    try:
        process_governance(store, tmp_path)
        assert _warnings(store) == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Bold-bullet learnings format (instance two)
# ---------------------------------------------------------------------------


def test_existing_table_formats_still_parse():
    learnings = _parse_learnings(SAMPLE_LEARNINGS)
    ids = {lr["learning_id"] for lr in learnings}
    assert {"L042-1", "L042-2", "L085-1", "L085-2"} <= ids
    by_id = {lr["learning_id"]: lr for lr in learnings}
    assert by_id["L042-1"]["status"] == "Incorporated"
    assert by_id["L042-1"]["plan_number"] == 42


def test_bold_bullet_fixture_yields_thirty_one_learnings():
    learnings = _parse_learnings(BOLD_BULLET)
    assert len(learnings) == 31
    ids = {lr["learning_id"] for lr in learnings}
    assert "L249-17" in ids
    assert "L252-9" in ids
    assert all(lr["plan_number"] == int(lr["learning_id"].split("-")[0][1:]) for lr in learnings)


def test_bold_bullet_status_comes_from_section_heading():
    learnings = _parse_learnings(BOLD_BULLET)
    by_id = {lr["learning_id"]: lr for lr in learnings}
    assert by_id["L249-17"]["status"] == "Pending"
    assert by_id["L252-1"]["status"] == "Incorporated"


def test_bold_bullet_wrapped_title_is_one_description():
    learnings = _parse_learnings(BOLD_BULLET)
    desc = next(lr["description"] for lr in learnings if lr["learning_id"] == "L249-17")
    assert "completion tooling" in desc
    assert "report it as passing" in desc


def test_indexing_bold_bullet_tracker_creates_learning_nodes(tmp_path: Path):
    dest = tmp_path / "docs" / "ai" / "state" / "learnings_tracker.md"
    dest.parent.mkdir(parents=True)
    dest.write_text(BOLD_BULLET.read_text())

    store = _store()
    try:
        result = process_governance(store, tmp_path)
        assert result["learnings"] == 31
        assert _warnings(store, phase="governance:learnings") == []
    finally:
        store.close()
