"""Tests for Steps C.4-C.6: agent markdown templates and all-platforms generation."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.config import ReviewerConfig, ReviewsConfig, ScaffoldConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_reviewer(
    name: str = "quant_architect",
    description: str = "Quant reviewer",
    cursor_description: str | None = None,
    file_patterns: list[str] | None = None,
    prompt_file: str | None = None,
    tools: list[str] | None = None,
) -> ReviewerConfig:
    return ReviewerConfig(
        name=name,
        description=description,
        cursor_description=cursor_description,
        file_patterns=file_patterns or [],
        prompt_file=prompt_file,
        tools=tools or [],
    )


def _make_config(reviewers: list[ReviewerConfig]) -> ScaffoldConfig:
    return ScaffoldConfig(reviews=ReviewsConfig(expert_reviewers=reviewers))


# ---------------------------------------------------------------------------
# ReviewerConfig unit tests
# ---------------------------------------------------------------------------


def test_reviewer_effective_cursor_description_explicit():
    r = _make_reviewer(cursor_description="Call this for quant reviews")
    assert r.effective_cursor_description() == "Call this for quant reviews"


def test_reviewer_effective_cursor_description_fallback():
    r = _make_reviewer(name="quant_architect", cursor_description=None)
    desc = r.effective_cursor_description()
    assert "quant_architect" in desc
    assert len(desc) > 0


def test_reviews_config_defaults():
    config = ScaffoldConfig()
    assert config.reviews.expert_reviewers == []


def test_reviews_config_from_dict():
    config = ScaffoldConfig.model_validate(
        {
            "reviews": {
                "expert_reviewers": [
                    {
                        "name": "quant_architect",
                        "description": "Quant reviewer",
                        "cursor_description": "Quant review",
                        "file_patterns": ["libs/risk/**"],
                    }
                ]
            }
        }
    )
    assert len(config.reviews.expert_reviewers) == 1
    reviewer = config.reviews.expert_reviewers[0]
    assert reviewer.name == "quant_architect"
    assert reviewer.file_patterns == ["libs/risk/**"]
    assert reviewer.effective_cursor_description() == "Quant review"


# ---------------------------------------------------------------------------
# Template rendering: agent.md.j2 (Claude Code)
# ---------------------------------------------------------------------------


def test_agent_md_template_has_frontmatter():
    from agentscaffold.agents.claude import generate_agent_markdown

    r = _make_reviewer(name="quant_architect", description="Quant reviewer")
    content = generate_agent_markdown(r)
    assert content.startswith("---")
    assert "name: quant_architect" in content


def test_agent_md_template_includes_scaffold_tools():
    from agentscaffold.agents.claude import generate_agent_markdown

    r = _make_reviewer()
    content = generate_agent_markdown(r)
    assert "scaffold_record_finding" in content
    assert "scaffold_resolve_finding" in content
    assert "scaffold_prepare_review" in content


def test_agent_md_template_includes_extra_tools():
    from agentscaffold.agents.claude import generate_agent_markdown

    r = _make_reviewer(tools=["Bash", "Read"])
    content = generate_agent_markdown(r)
    assert "Bash" in content
    assert "Read" in content


def test_agent_md_template_prompt_body_included():
    from agentscaffold.agents.claude import generate_agent_markdown

    r = _make_reviewer()
    content = generate_agent_markdown(r, prompt_body="## My criteria\n- check X\n")
    assert "## My criteria" in content
    assert "check X" in content


def test_agent_md_template_no_prompt_body():
    from agentscaffold.agents.claude import generate_agent_markdown

    r = _make_reviewer()
    content = generate_agent_markdown(r, prompt_body="")
    # Should not have the Review Criteria section
    assert "## Review Criteria" not in content


# ---------------------------------------------------------------------------
# Template rendering: cursor_agent.md.j2
# ---------------------------------------------------------------------------


def test_cursor_agent_template_has_frontmatter():
    from agentscaffold.agents.cursor import generate_cursor_reviewer_rule

    r = _make_reviewer()
    content = generate_cursor_reviewer_rule(r)
    assert content.startswith("---")
    assert "alwaysApply: false" in content


def test_cursor_agent_template_description_present():
    from agentscaffold.agents.cursor import generate_cursor_reviewer_rule

    r = _make_reviewer(cursor_description="Load for quant plans")
    content = generate_cursor_reviewer_rule(r)
    assert "Load for quant plans" in content


def test_cursor_agent_template_globs_when_file_patterns():
    from agentscaffold.agents.cursor import generate_cursor_reviewer_rule

    r = _make_reviewer(file_patterns=["libs/risk/**", "execution/**"])
    content = generate_cursor_reviewer_rule(r)
    assert "globs:" in content
    assert "libs/risk/**" in content


def test_cursor_agent_template_no_globs_without_file_patterns():
    from agentscaffold.agents.cursor import generate_cursor_reviewer_rule

    r = _make_reviewer(file_patterns=[])
    content = generate_cursor_reviewer_rule(r)
    assert "globs:" not in content


def test_cursor_agent_template_includes_record_finding_instruction():
    from agentscaffold.agents.cursor import generate_cursor_reviewer_rule

    r = _make_reviewer()
    content = generate_cursor_reviewer_rule(r)
    assert "scaffold_record_finding" in content


# ---------------------------------------------------------------------------
# Template rendering: windsurf_agent.md.j2
# ---------------------------------------------------------------------------


def test_windsurf_agent_template_has_heading():
    from agentscaffold.agents.windsurf import generate_windsurf_agent_stub

    r = _make_reviewer(name="quant_architect")
    content = generate_windsurf_agent_stub(r)
    assert "quant_architect" in content
    assert "Windsurf Cascade" in content


def test_windsurf_agent_template_includes_mcp_tools():
    from agentscaffold.agents.windsurf import generate_windsurf_agent_stub

    r = _make_reviewer()
    content = generate_windsurf_agent_stub(r)
    assert "scaffold_prepare_review" in content
    assert "scaffold_record_finding" in content
    assert "scaffold_resolve_finding" in content


# ---------------------------------------------------------------------------
# write_claude_agents — file I/O
# ---------------------------------------------------------------------------


def test_write_claude_agents_creates_files(tmp_path: Path):
    from agentscaffold.agents.claude import write_claude_agents

    r = _make_reviewer(name="quant_architect")
    config = _make_config([r])
    written = write_claude_agents(config, tmp_path)
    assert len(written) == 1
    dest = tmp_path / ".claude" / "agents" / "quant_architect.md"
    assert dest.exists()
    assert "quant_architect" in dest.read_text()


def test_write_claude_agents_dry_run_no_files(tmp_path: Path):
    from agentscaffold.agents.claude import write_claude_agents

    r = _make_reviewer(name="quant_architect")
    config = _make_config([r])
    written = write_claude_agents(config, tmp_path, dry_run=True)
    assert len(written) == 1
    assert not (tmp_path / ".claude" / "agents" / "quant_architect.md").exists()


def test_write_claude_agents_empty_reviewers(tmp_path: Path):
    from agentscaffold.agents.claude import write_claude_agents

    config = _make_config([])
    written = write_claude_agents(config, tmp_path)
    assert written == []


def test_write_claude_agents_loads_prompt_file(tmp_path: Path):
    from agentscaffold.agents.claude import write_claude_agents

    prompt_dir = tmp_path / "docs" / "ai" / "prompts"
    prompt_dir.mkdir(parents=True)
    prompt_file = prompt_dir / "quant_architect_review.md"
    prompt_file.write_text("## Quant Criteria\n- check P&L\n")

    r = _make_reviewer(
        name="quant_architect",
        prompt_file="docs/ai/prompts/quant_architect_review.md",
    )
    config = _make_config([r])
    write_claude_agents(config, tmp_path)
    dest = tmp_path / ".claude" / "agents" / "quant_architect.md"
    assert "check P&L" in dest.read_text()


def test_write_claude_agents_missing_prompt_file_ok(tmp_path: Path):
    from agentscaffold.agents.claude import write_claude_agents

    r = _make_reviewer(
        name="quant_architect",
        prompt_file="docs/ai/prompts/nonexistent.md",
    )
    config = _make_config([r])
    written = write_claude_agents(config, tmp_path)
    assert len(written) == 1  # still writes, just no prompt body


# ---------------------------------------------------------------------------
# write_cursor_reviewer_rules — file I/O
# ---------------------------------------------------------------------------


def test_write_cursor_reviewer_rules_creates_files(tmp_path: Path):
    from agentscaffold.agents.cursor import write_cursor_reviewer_rules

    cursor_dir = tmp_path / ".cursor"
    r = _make_reviewer(name="quant_architect", file_patterns=["libs/risk/**"])
    config = _make_config([r])
    written = write_cursor_reviewer_rules(config, cursor_dir)
    assert len(written) == 1
    dest = cursor_dir / "rules" / "quant_architect.mdc"
    assert dest.exists()
    content = dest.read_text()
    assert "alwaysApply: false" in content
    assert "libs/risk/**" in content


def test_write_cursor_reviewer_rules_dry_run(tmp_path: Path):
    from agentscaffold.agents.cursor import write_cursor_reviewer_rules

    cursor_dir = tmp_path / ".cursor"
    r = _make_reviewer(name="quant_architect")
    config = _make_config([r])
    written = write_cursor_reviewer_rules(config, cursor_dir, dry_run=True)
    assert len(written) == 1
    assert not (cursor_dir / "rules" / "quant_architect.mdc").exists()


def test_write_cursor_reviewer_rules_description_fallback(tmp_path: Path):
    from agentscaffold.agents.cursor import write_cursor_reviewer_rules

    cursor_dir = tmp_path / ".cursor"
    r = _make_reviewer(name="quant_architect", cursor_description=None)
    config = _make_config([r])
    write_cursor_reviewer_rules(config, cursor_dir)
    content = (cursor_dir / "rules" / "quant_architect.mdc").read_text()
    assert "quant_architect" in content


# ---------------------------------------------------------------------------
# write_windsurf_agent_stubs — file I/O
# ---------------------------------------------------------------------------


def test_write_windsurf_agent_stubs_creates_files(tmp_path: Path):
    from agentscaffold.agents.windsurf import write_windsurf_agent_stubs

    r = _make_reviewer(name="quant_architect")
    config = _make_config([r])
    written = write_windsurf_agent_stubs(config, tmp_path)
    assert len(written) == 1
    dest = tmp_path / ".windsurf" / "agents" / "quant_architect.md"
    assert dest.exists()
    assert "scaffold_record_finding" in dest.read_text()


def test_write_windsurf_agent_stubs_dry_run(tmp_path: Path):
    from agentscaffold.agents.windsurf import write_windsurf_agent_stubs

    r = _make_reviewer(name="quant_architect")
    config = _make_config([r])
    written = write_windsurf_agent_stubs(config, tmp_path, dry_run=True)
    assert len(written) == 1
    assert not (tmp_path / ".windsurf" / "agents" / "quant_architect.md").exists()


def test_write_windsurf_agent_stubs_empty_reviewers(tmp_path: Path):
    from agentscaffold.agents.windsurf import write_windsurf_agent_stubs

    config = _make_config([])
    written = write_windsurf_agent_stubs(config, tmp_path)
    assert written == []


# ---------------------------------------------------------------------------
# run_agents_generate_all_platforms — integration (dry_run only)
# ---------------------------------------------------------------------------


def test_all_platforms_dry_run_returns_paths(tmp_path: Path):
    from agentscaffold.agents.generate import run_agents_generate_all_platforms

    r = _make_reviewer(name="quant_architect", file_patterns=["libs/risk/**"])
    config = _make_config([r])
    result = run_agents_generate_all_platforms(config, tmp_path, dry_run=True)
    assert isinstance(result, dict)
    assert "claude_code" in result
    assert "cursor" in result
    assert "windsurf" in result


def test_all_platforms_dry_run_writes_nothing(tmp_path: Path):
    from agentscaffold.agents.generate import run_agents_generate_all_platforms

    r = _make_reviewer(name="quant_architect")
    config = _make_config([r])
    run_agents_generate_all_platforms(config, tmp_path, dry_run=True)
    # No agent files should be written
    assert not (tmp_path / ".claude" / "agents" / "quant_architect.md").exists()
    assert not (tmp_path / ".windsurf" / "agents" / "quant_architect.md").exists()


def test_all_platforms_no_reviewers_runs_without_error(tmp_path: Path):
    from agentscaffold.agents.generate import run_agents_generate_all_platforms

    config = _make_config([])
    result = run_agents_generate_all_platforms(config, tmp_path, dry_run=True)
    assert isinstance(result, dict)


def test_all_platforms_real_write_creates_artifacts(tmp_path: Path):
    from unittest.mock import patch

    from agentscaffold.agents.generate import run_agents_generate_all_platforms

    r = _make_reviewer(name="security_reviewer", file_patterns=["api/**"])
    config = _make_config([r])

    # Patch generate_claude_rules to avoid needing scaffold.yaml on disk
    with patch(
        "agentscaffold.agents.claude.generate_claude_rules",
        return_value="# CLAUDE.md",
    ):
        run_agents_generate_all_platforms(config, tmp_path, dry_run=False)

    assert (tmp_path / ".claude" / "agents" / "security_reviewer.md").exists()
    assert (tmp_path / ".windsurf" / "agents" / "security_reviewer.md").exists()
    assert (tmp_path / ".cursor" / "rules" / "security_reviewer.mdc").exists()


def test_agents_md_template_contains_human_readable_review_terminology():
    from agentscaffold.rendering import get_default_context, render_template

    content = render_template("agents/agents_md.md.j2", get_default_context(ScaffoldConfig()))

    assert "## Review Terminology (Human-Readable)" in content
    assert "Pre-implementation review" in content
    assert "Those tool names are an" in content
    assert "implementation detail" in content
    assert "never as the" in content
    assert "primary description" in content


def test_agents_md_template_contains_two_phase_governed_lifecycle():
    from agentscaffold.rendering import get_default_context, render_template

    content = render_template("agents/agents_md.md.j2", get_default_context(ScaffoldConfig()))

    assert "### Two-Phase Governed Lifecycle" in content
    assert "tools own graph state" in content
    assert "the agent owns file state" in content
    assert "Strict-mode gate" in content
    assert "freshness.gate_strict" in content


def test_agents_md_template_contains_architecture_changelog_scope():
    from agentscaffold.rendering import get_default_context, render_template

    content = render_template("agents/agents_md.md.j2", get_default_context(ScaffoldConfig()))

    assert "## Architecture Changelog Scope" in content
    assert "durable" in content
    assert "one-off recovery" in content


def test_agents_md_template_contains_handoff_and_fix_vs_backlog():
    from agentscaffold.rendering import get_default_context, render_template

    content = render_template("agents/agents_md.md.j2", get_default_context(ScaffoldConfig()))

    assert "### Session Handoff Hygiene" in content
    assert "in-flight state" in content
    assert "Fixing pre-existing defects (immediate vs backlog)" in content


def test_agents_md_template_contains_study_artifact_naming():
    from agentscaffold.rendering import get_default_context, render_template

    content = render_template("agents/agents_md.md.j2", get_default_context(ScaffoldConfig()))

    assert "### Study Artifact Naming" in content
    assert "nest them under" in content


def test_agents_md_template_stays_generic_no_domain_leakage():
    from agentscaffold.rendering import get_default_context, render_template

    content = render_template("agents/agents_md.md.j2", get_default_context(ScaffoldConfig()))

    # The generic template must not carry consumer/domain-specific vocabulary.
    for term in ("Prefect", "CUSIP", "CIK", "rebellion", "trading"):
        assert term not in content


def test_collaboration_protocol_template_contains_enriched_sections():
    from agentscaffold.rendering import get_default_context, render_template

    content = render_template(
        "project/collaboration_protocol.md.j2",
        get_default_context(ScaffoldConfig()),
    )

    assert "## Prompting Patterns" in content
    assert "### Devil's Advocate" in content
    assert "## Future Regret Evaluation" in content
    assert "## Communication Patterns" in content
    assert "## Review Terminology (Human-Readable)" in content
    assert "Quant Architect" not in content


def test_collaboration_protocol_template_renders_domain_reviews_conditionally():
    from agentscaffold.rendering import get_default_context, render_template

    config = ScaffoldConfig()
    config.gates.review_to_ready.domain_reviews = ["Quant Architect Review"]
    content = render_template("project/collaboration_protocol.md.j2", get_default_context(config))

    assert "Quant Architect Review" in content


# ---------------------------------------------------------------------------
# write_managed_block — never-clobber managed-section writer
# ---------------------------------------------------------------------------


def test_managed_block_creates_when_missing(tmp_path: Path):
    from agentscaffold.rendering import (
        MANAGED_BLOCK_BEGIN,
        MANAGED_BLOCK_END,
        write_managed_block,
    )

    dest = tmp_path / "AGENTS.md"
    status = write_managed_block(dest, "generated guidance")
    assert status == "created"
    text = dest.read_text()
    assert MANAGED_BLOCK_BEGIN in text
    assert MANAGED_BLOCK_END in text
    assert "generated guidance" in text


def test_managed_block_appends_to_unmarked_file(tmp_path: Path):
    """An org/user-owned file (no markers) is preserved; the block is appended."""
    from agentscaffold.rendering import MANAGED_BLOCK_BEGIN, write_managed_block

    dest = tmp_path / "AGENTS.md"
    dest.write_text("MY CUSTOM GOVERNANCE\n")
    status = write_managed_block(dest, "generated guidance")
    assert status == "appended"
    text = dest.read_text()
    # Every byte of the user's content survives, at the top of the file.
    assert text.startswith("MY CUSTOM GOVERNANCE\n")
    assert MANAGED_BLOCK_BEGIN in text
    assert "generated guidance" in text
    assert not dest.with_suffix(".md.bak").exists()  # append never needs a backup


def test_managed_block_refreshes_only_the_block(tmp_path: Path):
    """A second run replaces just the managed region, leaving user content intact."""
    from agentscaffold.rendering import write_managed_block

    dest = tmp_path / "AGENTS.md"
    dest.write_text("USER PREAMBLE\n")
    write_managed_block(dest, "version one")
    # User edits content OUTSIDE the block after the first generation.
    text = dest.read_text() + "\nUSER APPENDIX\n"
    dest.write_text(text)

    status = write_managed_block(dest, "version two")
    assert status == "block-updated"
    final = dest.read_text()
    assert "USER PREAMBLE" in final
    assert "USER APPENDIX" in final
    assert "version two" in final
    assert "version one" not in final  # stale managed content replaced
    assert final.count("BEGIN AGENTSCAFFOLD MANAGED SECTION") == 1  # idempotent, no duplication


def test_managed_block_unchanged_when_identical(tmp_path: Path):
    from agentscaffold.rendering import write_managed_block

    dest = tmp_path / "AGENTS.md"
    write_managed_block(dest, "stable")
    status = write_managed_block(dest, "stable")
    assert status == "unchanged"


def test_managed_block_force_overwrites_whole_file_with_backup(tmp_path: Path):
    from agentscaffold.rendering import write_managed_block

    dest = tmp_path / "AGENTS.md"
    dest.write_text("MY CUSTOM GOVERNANCE")
    status = write_managed_block(dest, "generated guidance", force=True)
    assert status == "overwritten"
    assert "MY CUSTOM GOVERNANCE" not in dest.read_text()
    backup = dest.with_suffix(".md.bak")
    assert backup.exists()
    assert backup.read_text() == "MY CUSTOM GOVERNANCE"


# ---------------------------------------------------------------------------
# Project-owned doc preservation in generate-all (the trust/safety fix)
# ---------------------------------------------------------------------------


def _generate_all_with_stubbed_claude(config, tmp_path: Path, force: bool = False) -> None:
    from unittest.mock import patch

    from agentscaffold.agents.generate import run_agents_generate_all_platforms

    with patch(
        "agentscaffold.agents.claude.generate_claude_rules",
        return_value="# CLAUDE.md (generated)",
    ):
        run_agents_generate_all_platforms(config, tmp_path, dry_run=False, force=force)


def test_generate_all_preserves_org_owned_docs(tmp_path: Path):
    config = _make_config([])
    # Simulate an org/user that already owns these agent docs (no markers).
    (tmp_path / "AGENTS.md").write_text("MY CUSTOM AGENTS")
    (tmp_path / "CLAUDE.md").write_text("MY CUSTOM CLAUDE")
    (tmp_path / ".windsurfrules").write_text("MY CUSTOM WINDSURF")

    _generate_all_with_stubbed_claude(config, tmp_path)

    # Existing content is never destroyed -- the managed block is appended after it.
    agents = (tmp_path / "AGENTS.md").read_text()
    assert agents.startswith("MY CUSTOM AGENTS")
    assert "BEGIN AGENTSCAFFOLD MANAGED SECTION" in agents
    claude = (tmp_path / "CLAUDE.md").read_text()
    assert claude.startswith("MY CUSTOM CLAUDE")
    assert "# CLAUDE.md (generated)" in claude
    assert (tmp_path / ".windsurfrules").read_text().startswith("MY CUSTOM WINDSURF")
    # ... while the machine-owned routing policy is still regenerated.
    assert (tmp_path / ".cursor" / "rules" / "agentscaffold.mdc").exists()


def test_generate_all_refreshes_managed_block_idempotently(tmp_path: Path):
    config = _make_config([])
    (tmp_path / "AGENTS.md").write_text("MY CUSTOM AGENTS\n")

    _generate_all_with_stubbed_claude(config, tmp_path)
    _generate_all_with_stubbed_claude(config, tmp_path)

    agents = (tmp_path / "AGENTS.md").read_text()
    # User content preserved and the managed block is not duplicated on re-run.
    assert agents.startswith("MY CUSTOM AGENTS")
    assert agents.count("BEGIN AGENTSCAFFOLD MANAGED SECTION") == 1


def test_generate_all_force_overwrites_docs_with_backup(tmp_path: Path):
    config = _make_config([])
    (tmp_path / "AGENTS.md").write_text("MY CUSTOM AGENTS")

    _generate_all_with_stubbed_claude(config, tmp_path, force=True)

    # Forced: rewritten whole, but the original is preserved as a .bak snapshot.
    assert "MY CUSTOM AGENTS" not in (tmp_path / "AGENTS.md").read_text()
    backup = tmp_path / "AGENTS.md.bak"
    assert backup.exists()
    assert backup.read_text() == "MY CUSTOM AGENTS"


def test_generate_all_into_realistic_manual_does_not_duplicate(tmp_path: Path) -> None:
    from agentscaffold.agents.manual_diff import render_governance_manual, stamp_manual

    config = _make_config([])
    manual = stamp_manual(render_governance_manual(config))
    (tmp_path / "AGENTS.md").write_text(manual)
    _generate_all_with_stubbed_claude(config, tmp_path)
    text = (tmp_path / "AGENTS.md").read_text()
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings
    assert len(headings) == len(set(headings))
    assert "Session Working Rhythm" in text
    assert "BEGIN AGENTSCAFFOLD MANAGED SECTION" in text


def test_generate_all_writes_docs_when_absent(tmp_path: Path):
    config = _make_config([])

    _generate_all_with_stubbed_claude(config, tmp_path)

    # Fresh project: docs are created (managed block wraps the generated content).
    assert (tmp_path / "AGENTS.md").exists()
    claude = (tmp_path / "CLAUDE.md").read_text()
    assert "# CLAUDE.md (generated)" in claude
    assert "BEGIN AGENTSCAFFOLD MANAGED SECTION" in claude
    assert (tmp_path / ".windsurfrules").exists()


# ---------------------------------------------------------------------------
# Shared-workspace stub-first project AGENTS + workspace router (Plan 234)
# ---------------------------------------------------------------------------


def _make_shared_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    for name in ("alpha", "beta"):
        (ws / name).mkdir(parents=True)
        (ws / name / "scaffold.yaml").write_text(f"framework:\n  project_name: {name}\n")
    (ws / "workspace.yaml").write_text(
        "projects:\n  - name: alpha\n    path: alpha\n  - name: beta\n    path: beta\n"
        "asset_layout:\n  layout: shared_workspace\n"
    )
    return ws


def test_project_agents_is_stub_first_under_shared_workspace(tmp_path: Path):
    from agentscaffold.agents.generate import _render_project_agents_md
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.rendering import get_default_context

    ws = _make_shared_ws(tmp_path)
    config = ScaffoldConfig()
    content = _render_project_agents_md(config, ws / "alpha", get_default_context(config))

    # Stub references shared assets and stays small (no duplicated process bodies).
    assert "stub-first" in content
    assert "Shared Workspace Process" in content
    # Full-template-only sections must NOT be duplicated into the stub.
    assert "## Plan Lifecycle" not in content
    assert "## Linter Warning Protocol" not in content
    assert len(content) < 4000


def test_full_project_agents_when_project_local(tmp_path: Path):
    from agentscaffold.agents.generate import _render_project_agents_md
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.rendering import get_default_context

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "scaffold.yaml").write_text("framework:\n  project_name: solo\n")
    config = ScaffoldConfig()
    content = _render_project_agents_md(config, proj, get_default_context(config))

    # No shared workspace -> routing-only managed body (manual is scaffolded by init).
    assert "## Session Working Rhythm" in content
    assert "## Plan Lifecycle" not in content


def test_workspace_router_generated(tmp_path: Path):
    from agentscaffold.agents.generate import write_workspace_agents_router
    from agentscaffold.paths import load_workspace

    ws = _make_shared_ws(tmp_path)
    workspace = load_workspace(ws / "alpha")
    status = write_workspace_agents_router(ws, workspace)

    assert status in ("created", "block-updated")
    router = (ws / "AGENTS.md").read_text()
    assert "Workspace Router" in router
    assert "alpha" in router and "beta" in router
    # The router must not claim project execution state.
    assert "## Plan Lifecycle" not in router
