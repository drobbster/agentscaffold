"""Plan 249 Step B1: canonical routing guidance, hash-stamped copies, MCP resource.

The routing policy is generated into several files per project (Cursor's
``.cursor/rules/agentscaffold.mdc``, ``CLAUDE.md``, ``.windsurfrules``). In a
workspace with N projects that is N copies of the same material, maintained
nowhere in particular and free to diverge silently.

Phase B makes one committed file at the workspace root the source those copies
are generated from, and stamps each copy with the canonical content hash so a
stale or hand-edited copy is detectable. The same content is served as the MCP
resource ``agentscaffold://guidance/routing`` for agents that would rather ask
than read a file.

**The copies keep their policy body inline.** ADR-025 Decision 6 originally
called for emptying them to a pointer at the canonical file; that decision was
amended on 2026-08-05 (see the ADR, and Plan 249 Section 1 goal 4). Editors
inject these files into agent context verbatim at session start, so a pointer
makes the routing guidance conditional on an agent noticing it and spending a
call to follow it -- the exact failure this plan exists to remove.
``test_platform_files_keep_the_policy_inline`` guards that amendment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_shared_ws(tmp_path: Path) -> Path:
    """A two-project workspace opted into the shared_workspace layout."""
    ws = tmp_path / "ws"
    for name in ("alpha", "beta"):
        (ws / name).mkdir(parents=True)
        (ws / name / "scaffold.yaml").write_text(f"framework:\n  project_name: {name}\n")
    (ws / "workspace.yaml").write_text(
        "projects:\n  - name: alpha\n    path: alpha\n  - name: beta\n    path: beta\n"
        "asset_layout:\n  layout: shared_workspace\n"
    )
    return ws


def _make_lone_repo(tmp_path: Path) -> Path:
    """A single repo with no workspace manifest -- the pre-Plan-234 shape."""
    root = tmp_path / "solo"
    root.mkdir(parents=True)
    (root / "scaffold.yaml").write_text("framework:\n  project_name: solo\n")
    return root


def _generate_all(config: ScaffoldConfig, project_root: Path) -> None:
    """Run full platform generation with the Claude renderer stubbed out.

    ``generate_claude_rules`` is left real elsewhere; here it is the one call
    that pulls in reviewer prompt files this fixture does not create.
    """
    from unittest.mock import patch

    from agentscaffold.agents.generate import run_agents_generate_all_platforms

    with patch(
        "agentscaffold.agents.claude.generate_claude_rules",
        return_value="# CLAUDE.md (generated)",
    ):
        run_agents_generate_all_platforms(config, project_root, dry_run=False, force=False)


# ---------------------------------------------------------------------------
# The canonical document
# ---------------------------------------------------------------------------


def test_canonical_document_carries_the_routing_policy_and_intent_map():
    from agentscaffold.rendering import canonical_guidance_document

    doc = canonical_guidance_document(ScaffoldConfig())

    assert "AgentScaffold Tool Selection Policy" in doc
    assert "Graph Trust Discipline" in doc
    assert "Intent Map" in doc
    assert "scaffold_orient" in doc


def test_canonical_document_omits_per_platform_framing():
    """Platform files add their own frontmatter, title and intro around it.

    If the canonical body carried Cursor's ``alwaysApply`` frontmatter it could
    not be embedded in ``CLAUDE.md`` or ``.windsurfrules`` unchanged, and the
    single-source claim would be false.
    """
    from agentscaffold.rendering import canonical_guidance_document

    doc = canonical_guidance_document(ScaffoldConfig())

    assert not doc.startswith("---")
    assert "alwaysApply" not in doc


def test_canonical_document_is_stable_across_calls():
    """Dedup is only meaningful if the source is deterministic."""
    from agentscaffold.rendering import canonical_guidance_document

    config = ScaffoldConfig()
    assert canonical_guidance_document(config) == canonical_guidance_document(config)


def test_guidance_hash_tracks_content():
    from agentscaffold.rendering import guidance_hash

    assert guidance_hash("abc") == guidance_hash("abc")
    assert guidance_hash("abc") != guidance_hash("abd")
    assert len(guidance_hash("abc")) == 64


# ---------------------------------------------------------------------------
# Canonical emission
# ---------------------------------------------------------------------------


def test_canonical_file_is_written_once_at_the_workspace_root(tmp_path: Path):
    from agentscaffold.rendering import canonical_guidance_document, write_canonical_guidance

    ws = _make_shared_ws(tmp_path)
    config = ScaffoldConfig()

    path, _status = write_canonical_guidance(ws / "alpha", config)

    assert path is not None
    assert path.parent.parent.parent == ws, f"canonical file escaped the workspace root: {path}"
    assert path.read_text() == canonical_guidance_document(config)


def test_writing_canonical_from_a_sibling_project_targets_the_same_file(tmp_path: Path):
    """Both projects resolve to one canonical file -- that is the whole point."""
    from agentscaffold.rendering import write_canonical_guidance

    ws = _make_shared_ws(tmp_path)
    config = ScaffoldConfig()

    from_alpha, _ = write_canonical_guidance(ws / "alpha", config)
    from_beta, _ = write_canonical_guidance(ws / "beta", config)

    assert from_alpha == from_beta


def test_rewriting_unchanged_canonical_reports_unchanged(tmp_path: Path):
    from agentscaffold.rendering import write_canonical_guidance

    ws = _make_shared_ws(tmp_path)
    config = ScaffoldConfig()

    write_canonical_guidance(ws / "alpha", config)
    _path, status = write_canonical_guidance(ws / "alpha", config)

    assert status == "unchanged"


def test_a_lone_repo_gets_no_canonical_file(tmp_path: Path):
    """ADR-024 non-regression: generation for a lone repo is unchanged.

    Canonical emission is a shared_workspace feature. A repo that never opted
    into a workspace layout must not acquire a new committed file.
    """
    from agentscaffold.rendering import canonical_guidance_path, write_canonical_guidance

    root = _make_lone_repo(tmp_path)

    assert canonical_guidance_path(root) is None
    assert write_canonical_guidance(root, ScaffoldConfig()) is None


# ---------------------------------------------------------------------------
# Hash stamping of the derived copies
# ---------------------------------------------------------------------------


def test_stamp_round_trips():
    from agentscaffold.rendering import read_guidance_stamp, render_guidance_stamp

    text = render_guidance_stamp("a" * 64, "docs/ai/agent_routing.md")
    stamp = read_guidance_stamp(f"# A rule file\n\n{text}\n\nbody\n")

    assert stamp is not None
    assert stamp.sha256 == "a" * 64
    assert stamp.source == "docs/ai/agent_routing.md"


def test_reading_a_stamp_from_unstamped_text_returns_none():
    from agentscaffold.rendering import read_guidance_stamp

    assert read_guidance_stamp("# Just a rule file\n\nbody\n") is None


def test_generated_platform_files_carry_the_canonical_hash(tmp_path: Path):
    from agentscaffold.rendering import (
        canonical_guidance_document,
        guidance_hash,
        read_guidance_stamp,
    )

    ws = _make_shared_ws(tmp_path)
    config = ScaffoldConfig()

    _generate_all(config, ws / "alpha")

    expected = guidance_hash(canonical_guidance_document(config))
    rule_file = ws / "alpha" / ".cursor" / "rules" / "agentscaffold.mdc"
    stamp = read_guidance_stamp(rule_file.read_text())

    assert stamp is not None, "generated Cursor rule file carries no guidance stamp"
    assert stamp.sha256 == expected


def test_platform_files_keep_the_policy_inline(tmp_path: Path):
    """Guards the ADR-025 Decision 6 amendment of 2026-08-05.

    These files are injected into agent context verbatim at session start. If a
    future change empties them to a pointer at the canonical file, the routing
    guidance stops being unconditionally present and this test must fail loudly
    rather than let the regression through as a dedup win.
    """
    ws = _make_shared_ws(tmp_path)

    _generate_all(ScaffoldConfig(), ws / "alpha")

    rule_file = ws / "alpha" / ".cursor" / "rules" / "agentscaffold.mdc"
    body = rule_file.read_text()

    assert "AgentScaffold Tool Selection Policy" in body
    assert "Intent Map" in body
    assert "scaffold_orient" in body
    assert "### scaffold_prepare_review" in body


def test_generation_writes_the_canonical_file_too(tmp_path: Path):
    """The copies cannot cite a source that generation never produced."""
    from agentscaffold.rendering import canonical_guidance_path

    ws = _make_shared_ws(tmp_path)

    _generate_all(ScaffoldConfig(), ws / "alpha")

    canonical = canonical_guidance_path(ws / "alpha")
    assert canonical is not None
    assert canonical.is_file()


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def test_no_drift_immediately_after_generation(tmp_path: Path):
    from agentscaffold.rendering import detect_guidance_drift

    ws = _make_shared_ws(tmp_path)
    _generate_all(ScaffoldConfig(), ws / "alpha")

    assert detect_guidance_drift(ws / "alpha") == []


def test_editing_the_canonical_file_makes_the_copies_stale(tmp_path: Path):
    from agentscaffold.rendering import canonical_guidance_path, detect_guidance_drift

    ws = _make_shared_ws(tmp_path)
    _generate_all(ScaffoldConfig(), ws / "alpha")

    canonical = canonical_guidance_path(ws / "alpha")
    assert canonical is not None
    canonical.write_text(canonical.read_text() + "\n- A hand-added routing rule.\n")

    drift = detect_guidance_drift(ws / "alpha")

    assert drift, "an edited canonical file left every copy silently stale"
    assert all(d.reason == "stale" for d in drift)
    assert any(d.path.name == "agentscaffold.mdc" for d in drift)


def test_an_unstamped_copy_is_reported(tmp_path: Path):
    """A file generated before Phase B, or hand-authored, carries no stamp."""
    from agentscaffold.rendering import detect_guidance_drift

    ws = _make_shared_ws(tmp_path)
    _generate_all(ScaffoldConfig(), ws / "alpha")

    rule_file = ws / "alpha" / ".cursor" / "rules" / "agentscaffold.mdc"
    rule_file.write_text("# Hand-authored rules\n\nDo whatever.\n")

    drift = detect_guidance_drift(ws / "alpha")

    assert [d.reason for d in drift] == ["unstamped"]
    assert drift[0].path == rule_file


def test_a_missing_canonical_file_is_reported_distinctly(tmp_path: Path):
    """Distinct from staleness: nothing to compare against, not a mismatch."""
    from agentscaffold.rendering import canonical_guidance_path, detect_guidance_drift

    ws = _make_shared_ws(tmp_path)
    _generate_all(ScaffoldConfig(), ws / "alpha")

    canonical = canonical_guidance_path(ws / "alpha")
    assert canonical is not None
    canonical.unlink()

    drift = detect_guidance_drift(ws / "alpha")

    assert drift
    assert all(d.reason == "missing_canonical" for d in drift)


def test_a_lone_repo_reports_no_drift(tmp_path: Path):
    """No canonical file means no dedup relationship to be wrong about."""
    from agentscaffold.rendering import detect_guidance_drift

    root = _make_lone_repo(tmp_path)
    _generate_all(ScaffoldConfig(), root)

    assert detect_guidance_drift(root) == []


# ---------------------------------------------------------------------------
# MCP resource parity
# ---------------------------------------------------------------------------


def test_guidance_resource_matches_the_canonical_file(tmp_path: Path):
    from agentscaffold.mcp.resources import read_guidance_routing
    from agentscaffold.rendering import canonical_guidance_path

    ws = _make_shared_ws(tmp_path)
    _generate_all(ScaffoldConfig(), ws / "alpha")

    canonical = canonical_guidance_path(ws / "alpha")
    assert canonical is not None
    assert read_guidance_routing(ws / "alpha") == canonical.read_text()


def test_guidance_resource_falls_back_to_generated_content(tmp_path: Path):
    """An MCP-first agent must get policy even with no file on disk.

    ADR-025 Decision 6 keeps all three delivery paths precisely so none of them
    is load-bearing alone; a lone repo has no canonical file and must still be
    able to read the resource.
    """
    from agentscaffold.mcp.resources import read_guidance_routing
    from agentscaffold.rendering import canonical_guidance_document

    root = _make_lone_repo(tmp_path)

    assert read_guidance_routing(root) == canonical_guidance_document(ScaffoldConfig())


def test_guidance_resource_does_not_require_a_graph(tmp_path: Path):
    """Existing resources read the graph and error without one.

    Routing guidance is static text. Making it depend on an indexed graph would
    mean a fresh clone -- the case where an agent most needs to be told how to
    behave -- gets an error instead of policy.
    """
    from agentscaffold.mcp.resources import read_guidance_routing

    root = _make_lone_repo(tmp_path)
    content = read_guidance_routing(root)

    assert "Intent Map" in content
    assert "error" not in content[:200].lower()


def test_guidance_resource_is_advertised():
    from agentscaffold.mcp.resources import GUIDANCE_ROUTING_URI, guidance_resource_definition

    pytest.importorskip("mcp.types")

    assert GUIDANCE_ROUTING_URI == "agentscaffold://guidance/routing"
    definition = guidance_resource_definition()
    assert str(definition.uri) == GUIDANCE_ROUTING_URI
    assert definition.mimeType == "text/markdown"


def test_server_lists_the_guidance_resource():
    """The definition is worthless if the server never advertises it."""
    pytest.importorskip("mcp.types")

    from agentscaffold.mcp.resources import GUIDANCE_ROUTING_URI
    from agentscaffold.mcp.server import _get_resource_definitions

    uris = {str(r.uri) for r in _get_resource_definitions()}
    assert GUIDANCE_ROUTING_URI in uris


def test_server_dispatches_the_guidance_resource():
    """Routed through the same dispatch path clients actually reach."""
    from agentscaffold.mcp.resources import GUIDANCE_ROUTING_URI
    from agentscaffold.mcp.server import _dispatch_resource

    result = _dispatch_resource(GUIDANCE_ROUTING_URI)

    assert "error" not in result
    assert "Intent Map" in result["content"]
