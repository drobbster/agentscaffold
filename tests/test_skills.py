"""Tests for Phase D: Skills generator and catalog (Steps D.1-D.3)."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# generator.py tests
# ---------------------------------------------------------------------------


def test_generate_skill_md_has_frontmatter():
    from agentscaffold.skills.generator import generate_skill_md

    content = generate_skill_md("testing", "Testing standards", "## Principles\n- test first\n")
    assert content.startswith("---\n")
    assert "name: testing" in content
    assert "description: Testing standards" in content


def test_generate_skill_md_platforms_default():
    from agentscaffold.skills.generator import generate_skill_md

    content = generate_skill_md("testing", "Testing standards", "body")
    assert "claude-code" in content
    assert "cursor" in content
    assert "windsurf" in content


def test_generate_skill_md_custom_platforms():
    from agentscaffold.skills.generator import generate_skill_md

    content = generate_skill_md("testing", "Testing standards", "body", platforms=["claude-code"])
    assert "claude-code" in content
    assert "windsurf" not in content


def test_generate_skill_md_has_catalog_entry():
    from agentscaffold.skills.generator import generate_skill_md

    content = generate_skill_md("testing", "Testing standards", "Some useful content here.\n")
    assert "## Catalog Entry" in content
    assert "testing" in content.lower()


def test_generate_skill_md_has_full_instructions():
    from agentscaffold.skills.generator import generate_skill_md

    body = "## Pattern A\nDo this thing.\n"
    content = generate_skill_md("testing", "desc", body)
    assert "## Full Instructions" in content
    assert "Do this thing." in content


def test_generate_skill_md_has_resources():
    from agentscaffold.skills.generator import generate_skill_md

    content = generate_skill_md(
        "testing", "desc", "body", resources=["docs/ai/standards/testing.md"]
    )
    assert "## Resources" in content
    assert "docs/ai/standards/testing.md" in content


def test_generate_skill_md_slugifies_name():
    from agentscaffold.skills.generator import generate_skill_md

    content = generate_skill_md("RL Patterns", "desc", "body")
    assert "name: rl_patterns" in content


def test_generate_skills_from_standards_dir(tmp_path: Path):
    from agentscaffold.skills.generator import generate_skills_from_standards_dir

    std_dir = tmp_path / "standards"
    std_dir.mkdir()
    (std_dir / "testing.md").write_text("# Testing Standards\n\nDo this.\n")
    (std_dir / "errors.md").write_text("# Error Handling\n\nHandle them.\n")
    (std_dir / "README.md").write_text("# Overview\n")

    out_dir = tmp_path / "skills"
    written = generate_skills_from_standards_dir(std_dir, out_dir)
    assert len(written) == 2  # README.md excluded
    assert (out_dir / "testing.md").exists()
    assert (out_dir / "errors.md").exists()


def test_generate_skills_from_standards_dir_dry_run(tmp_path: Path):
    from agentscaffold.skills.generator import generate_skills_from_standards_dir

    std_dir = tmp_path / "standards"
    std_dir.mkdir()
    (std_dir / "testing.md").write_text("# Testing\n")
    out_dir = tmp_path / "skills"

    written = generate_skills_from_standards_dir(std_dir, out_dir, dry_run=True)
    assert len(written) == 1
    assert not out_dir.exists()


def test_generate_skills_empty_dir(tmp_path: Path):
    from agentscaffold.skills.generator import generate_skills_from_standards_dir

    written = generate_skills_from_standards_dir(tmp_path / "nonexistent", tmp_path / "out")
    assert written == []


def test_parse_skill_frontmatter(tmp_path: Path):
    from agentscaffold.skills.generator import generate_skill_md, parse_skill_frontmatter

    content = generate_skill_md("testing", "Testing standards", "body")
    skill_file = tmp_path / "testing.md"
    skill_file.write_text(content)

    fm = parse_skill_frontmatter(skill_file)
    assert fm["name"] == "testing"
    assert fm["description"] == "Testing standards"
    assert "claude-code" in fm["platforms"]


def test_parse_skill_frontmatter_no_frontmatter(tmp_path: Path):
    from agentscaffold.skills.generator import parse_skill_frontmatter

    skill_file = tmp_path / "plain.md"
    skill_file.write_text("# Plain markdown\nNo frontmatter.\n")

    fm = parse_skill_frontmatter(skill_file)
    assert fm == {}


# ---------------------------------------------------------------------------
# catalog.py tests
# ---------------------------------------------------------------------------


def test_build_catalog_returns_entries(tmp_path: Path):
    from agentscaffold.skills.catalog import build_catalog
    from agentscaffold.skills.generator import generate_skill_md

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    for name, desc in [("testing", "Testing"), ("errors", "Error handling")]:
        content = generate_skill_md(name, desc, f"## {desc}\nBody.\n")
        (skills_dir / f"{name}.md").write_text(content)

    entries = build_catalog([skills_dir])
    assert len(entries) == 2
    names = {e["name"] for e in entries}
    assert "testing" in names
    assert "errors" in names


def test_build_catalog_deduplicates(tmp_path: Path):
    from agentscaffold.skills.catalog import build_catalog
    from agentscaffold.skills.generator import generate_skill_md

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    for d in (dir_a, dir_b):
        (d / "testing.md").write_text(generate_skill_md("testing", "Testing", "body"))

    entries = build_catalog([dir_a, dir_b])
    assert sum(1 for e in entries if e["name"] == "testing") == 1


def test_build_catalog_empty_dirs(tmp_path: Path):
    from agentscaffold.skills.catalog import build_catalog

    entries = build_catalog([tmp_path / "nonexistent"])
    assert entries == []


def test_format_catalog_markdown_empty():
    from agentscaffold.skills.catalog import format_catalog_markdown

    result = format_catalog_markdown([])
    assert "No skills" in result


def test_format_catalog_markdown_table(tmp_path: Path):
    from agentscaffold.skills.catalog import build_catalog, format_catalog_markdown
    from agentscaffold.skills.generator import generate_skill_md

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "testing.md").write_text(generate_skill_md("testing", "Testing standards", "b"))

    entries = build_catalog([skills_dir])
    md = format_catalog_markdown(entries)
    assert "| Skill |" in md
    assert "testing" in md


def test_write_catalog_creates_file(tmp_path: Path):
    from agentscaffold.skills.catalog import write_catalog
    from agentscaffold.skills.generator import generate_skill_md

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "testing.md").write_text(generate_skill_md("testing", "Testing", "body"))

    out = tmp_path / "SKILLS_CATALOG.md"
    result = write_catalog([skills_dir], out)
    assert result == out
    assert out.exists()
    assert "testing" in out.read_text()


def test_write_catalog_dry_run(tmp_path: Path):
    from agentscaffold.skills.catalog import write_catalog
    from agentscaffold.skills.generator import generate_skill_md

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "testing.md").write_text(generate_skill_md("testing", "Testing", "body"))

    out = tmp_path / "SKILLS_CATALOG.md"
    write_catalog([skills_dir], out, dry_run=True)
    assert not out.exists()
