"""Tests for collaboration ergonomics: sharding + advisory claims (Plan 226)."""

from __future__ import annotations

import re

import pytest

from agentscaffold import collab

WORKFLOW_SAMPLE = """# Workflow State

Preamble text that precedes the first entry.

### Plan 224 COMPLETE

Did the config inheritance work.

### Plan 225 COMPLETE

Did the namespacing work.

### Plan 226 IN PROGRESS

Sharding and claims.
"""


def test_split_text_preamble_and_entries() -> None:
    chunks = collab.split_text(WORKFLOW_SAMPLE, collab.WORKFLOW_STATE_BOUNDARY)
    slugs = [slug for slug, _ in chunks]
    assert slugs[0] == "preamble"
    assert len(chunks) == 4  # preamble + 3 entries
    # Concatenation is lossless.
    assert "".join(chunk for _, chunk in chunks) == WORKFLOW_SAMPLE


def test_split_render_round_trip_is_exact(tmp_path) -> None:
    source = tmp_path / "workflow_state.md"
    source.write_text(WORKFLOW_SAMPLE, encoding="utf-8")
    frag_dir = tmp_path / "fragments"

    written = collab.split_file(source, frag_dir, collab.WORKFLOW_STATE_BOUNDARY)
    assert len(written) == 4
    assert all(re.match(r"^\d{5}_.*\.md$", p.name) for p in written)

    rendered = collab.render_fragments(frag_dir)
    assert rendered == WORKFLOW_SAMPLE


def test_render_is_deterministic(tmp_path) -> None:
    source = tmp_path / "workflow_state.md"
    source.write_text(WORKFLOW_SAMPLE, encoding="utf-8")
    frag_dir = tmp_path / "fragments"
    collab.split_file(source, frag_dir, collab.WORKFLOW_STATE_BOUNDARY)

    assert collab.render_fragments(frag_dir) == collab.render_fragments(frag_dir)


def test_split_is_idempotent(tmp_path) -> None:
    source = tmp_path / "workflow_state.md"
    source.write_text(WORKFLOW_SAMPLE, encoding="utf-8")
    frag_dir = tmp_path / "fragments"

    first = collab.split_file(source, frag_dir, collab.WORKFLOW_STATE_BOUNDARY)
    second = collab.split_file(source, frag_dir, collab.WORKFLOW_STATE_BOUNDARY)
    assert [p.name for p in first] == [p.name for p in second]
    # No stale fragments accumulate.
    assert len(list(frag_dir.glob("*.md"))) == len(first)


def test_render_to_file_only_writes_on_change(tmp_path) -> None:
    frag_dir = tmp_path / "fragments"
    frag_dir.mkdir()
    (frag_dir / "00000_preamble.md").write_text("hello\n", encoding="utf-8")
    target = tmp_path / "out.md"

    assert collab.render_to_file(frag_dir, target) is True
    assert target.read_text(encoding="utf-8") == "hello\n"
    # Second render is a no-op (content unchanged).
    assert collab.render_to_file(frag_dir, target) is False


def test_split_missing_source_raises(tmp_path) -> None:
    with pytest.raises(collab.CollabError):
        collab.split_file(tmp_path / "nope.md", tmp_path / "frags", collab.WORKFLOW_STATE_BOUNDARY)


def test_render_empty_dir_is_empty_string(tmp_path) -> None:
    assert collab.render_fragments(tmp_path / "does-not-exist") == ""


# ---------------------------------------------------------------------------
# Advisory claims
# ---------------------------------------------------------------------------


def test_claim_release_lifecycle(tmp_path) -> None:
    claims_dir = tmp_path / "claims"
    assert collab.get_claim(claims_dir, "225") is None

    record = collab.claim_plan(claims_dir, "225", "agent-a")
    assert record["owner"] == "agent-a"
    assert record["plan"] == "225"
    assert collab.get_claim(claims_dir, "225") == record

    assert collab.release_plan(claims_dir, "225") is True
    assert collab.get_claim(claims_dir, "225") is None
    # Releasing again is a no-op.
    assert collab.release_plan(claims_dir, "225") is False


def test_claim_same_owner_refreshes(tmp_path) -> None:
    claims_dir = tmp_path / "claims"
    collab.claim_plan(claims_dir, "225", "agent-a")
    # Same owner re-claiming is allowed (refresh timestamp).
    again = collab.claim_plan(claims_dir, "225", "agent-a")
    assert again["owner"] == "agent-a"


def test_claim_conflicting_owner_raises(tmp_path) -> None:
    claims_dir = tmp_path / "claims"
    collab.claim_plan(claims_dir, "225", "agent-a")
    with pytest.raises(collab.CollabError):
        collab.claim_plan(claims_dir, "225", "agent-b")


def test_list_claims_sorted(tmp_path) -> None:
    claims_dir = tmp_path / "claims"
    collab.claim_plan(claims_dir, "226", "agent-b")
    collab.claim_plan(claims_dir, "225", "agent-a")
    claims = collab.list_claims(claims_dir)
    assert [c["plan"] for c in claims] == ["225", "226"]


def test_sharded_config_defaults_off() -> None:
    from agentscaffold.config import ScaffoldConfig

    config = ScaffoldConfig()
    assert config.collab.sharded is False
