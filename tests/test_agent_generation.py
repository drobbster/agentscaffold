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
    dest = cursor_dir / "rules" / "quant_architect.md"
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
    assert not (cursor_dir / "rules" / "quant_architect.md").exists()


def test_write_cursor_reviewer_rules_description_fallback(tmp_path: Path):
    from agentscaffold.agents.cursor import write_cursor_reviewer_rules

    cursor_dir = tmp_path / ".cursor"
    r = _make_reviewer(name="quant_architect", cursor_description=None)
    config = _make_config([r])
    write_cursor_reviewer_rules(config, cursor_dir)
    content = (cursor_dir / "rules" / "quant_architect.md").read_text()
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
    assert (tmp_path / ".cursor" / "rules" / "security_reviewer.md").exists()
