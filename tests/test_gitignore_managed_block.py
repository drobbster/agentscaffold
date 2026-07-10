"""Tests for the auto .gitignore managed block (Plan 241).

Covers the never-clobber writer (`write_gitignore_block`) and its wiring into
`run_init` and `run_agents_generate_all_platforms`.
"""

from __future__ import annotations

from pathlib import Path

from agentscaffold.rendering import (
    GITIGNORE_BLOCK_BEGIN,
    GITIGNORE_BLOCK_END,
    GITIGNORE_MANAGED_PATTERNS,
    write_gitignore_block,
)


def test_creates_gitignore_with_all_patterns(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    status = write_gitignore_block(gitignore)

    assert status == "created"
    content = gitignore.read_text()
    assert GITIGNORE_BLOCK_BEGIN in content
    assert GITIGNORE_BLOCK_END in content
    for pattern in GITIGNORE_MANAGED_PATTERNS:
        assert pattern in content
    # The three artifacts consumers had to add by hand are all covered.
    assert ".scaffold/" in content
    assert ".venv-scaffold/" in content
    assert "*.duckdb" in content


def test_rerun_is_idempotent(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    write_gitignore_block(gitignore)
    first = gitignore.read_text()

    status = write_gitignore_block(gitignore)

    assert status == "unchanged"
    assert gitignore.read_text() == first
    # Exactly one managed block, no duplication.
    assert first.count(GITIGNORE_BLOCK_BEGIN) == 1
    assert first.count(GITIGNORE_BLOCK_END) == 1


def test_appends_to_existing_gitignore_without_clobbering(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    user_content = "# user rules\nnode_modules/\n.env\n__pycache__/\n"
    gitignore.write_text(user_content)

    status = write_gitignore_block(gitignore)

    assert status == "appended"
    result = gitignore.read_text()
    # Every user line is preserved verbatim.
    assert "node_modules/" in result
    assert ".env" in result
    assert "__pycache__/" in result
    assert result.startswith(user_content)
    # And the managed block is present after user content.
    assert GITIGNORE_BLOCK_BEGIN in result
    assert ".scaffold/" in result


def test_refreshes_only_the_block_region(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    # Simulate an older managed block with a stale pattern, surrounded by user lines.
    stale = (
        "keep-before/\n\n"
        f"{GITIGNORE_BLOCK_BEGIN}\n"
        ".scaffold/\n"
        "OLD_STALE_PATTERN/\n"
        f"{GITIGNORE_BLOCK_END}\n\n"
        "keep-after/\n"
    )
    gitignore.write_text(stale)

    status = write_gitignore_block(gitignore)

    assert status == "block-updated"
    result = gitignore.read_text()
    # User lines outside the block are untouched.
    assert "keep-before/" in result
    assert "keep-after/" in result
    # Stale in-block pattern is gone; current patterns are present.
    assert "OLD_STALE_PATTERN/" not in result
    assert ".venv-scaffold/" in result
    assert result.count(GITIGNORE_BLOCK_BEGIN) == 1


def test_run_init_writes_gitignore(tmp_path: Path) -> None:
    from agentscaffold.init_cmd import run_init

    run_init(tmp_path, non_interactive=True)

    gitignore = tmp_path / ".gitignore"
    assert gitignore.is_file()
    content = gitignore.read_text()
    assert GITIGNORE_BLOCK_BEGIN in content
    assert ".scaffold/" in content
    assert ".venv-scaffold/" in content


def test_generate_all_platforms_writes_gitignore(tmp_path: Path) -> None:
    from agentscaffold.agents.generate import run_agents_generate_all_platforms
    from agentscaffold.config import ScaffoldConfig

    config = ScaffoldConfig()
    written = run_agents_generate_all_platforms(config, tmp_path)

    gitignore = tmp_path / ".gitignore"
    assert gitignore.is_file()
    assert ".scaffold/" in gitignore.read_text()
    assert gitignore in written["project"]
