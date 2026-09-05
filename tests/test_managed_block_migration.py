"""Plan 260: sentinel, heading-overlap guard, and upgrade lift."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig
from agentscaffold.rendering import (
    MANAGED_BLOCK_BEGIN,
    MANAGED_FALSE_SENTINEL,
    ManagedBlockAppendRefusedError,
    render_managed_block,
    write_gitignore_block,
    write_managed_block,
)


def test_sentinel_skips_managed_write(tmp_path: Path) -> None:
    dest = tmp_path / "AGENTS.md"
    dest.write_text(f"{MANAGED_FALSE_SENTINEL}\n# Mine\n")
    status = write_managed_block(dest, "## Session Working Rhythm\n\nkeep out\n")
    assert status == "skipped"
    assert dest.read_text() == f"{MANAGED_FALSE_SENTINEL}\n# Mine\n"


def test_sentinel_skips_gitignore(tmp_path: Path) -> None:
    dest = tmp_path / ".gitignore"
    dest.write_text(f"{MANAGED_FALSE_SENTINEL}\n*.log\n")
    status = write_gitignore_block(dest)
    assert status == "skipped"
    assert "*.log" in dest.read_text()
    assert "BEGIN AGENTSCAFFOLD" not in dest.read_text()


def test_heading_guard_refuses_and_names_allow_append(tmp_path: Path) -> None:
    dest = tmp_path / "AGENTS.md"
    dest.write_text(
        "## Session Working Rhythm\n\nlocal\n\n"
        "## Graph Trust Discipline (Avoid Context Blindness)\n\nlocal\n\n"
        "## Multi-Project Workspace Discipline\n\nlocal\n\n"
        "## AgentScaffold Tool Selection Policy (MCP-First with Practical Fallback)\n\nlocal\n\n"
        "## Required Procedure\n\nlocal\n\n"
        "## Fallback Is Allowed When\n\nlocal\n\n"
        "## High-Value MCP-First Routes\n\nlocal\n\n"
        "## Call Compression Discipline\n\nlocal\n\n"
        "## Governance Guardrails (Always Apply)\n\nlocal\n"
    )
    with pytest.raises(ManagedBlockAppendRefusedError, match="--allow-append") as exc:
        write_managed_block(dest, dest.read_text())
    assert "--force" in str(exc.value)
    assert "allow-append" in str(exc.value).lower()


def test_allow_append_writes_once(tmp_path: Path) -> None:
    dest = tmp_path / "AGENTS.md"
    dest.write_text("## Session Working Rhythm\n\nmine\n")
    # One of six headings is not a substantial share.
    block = "\n\n".join(f"## Heading {i}\n\nnew {i}" for i in range(6))
    status = write_managed_block(dest, block)
    assert status == "appended"
    assert dest.read_text().startswith("## Session Working Rhythm\n\nmine\n")


def test_allow_append_overrides_guard(tmp_path: Path) -> None:
    headings = "\n\n".join(f"## Heading {i}\n\nbody {i}" for i in range(6))
    dest = tmp_path / "AGENTS.md"
    dest.write_text(headings + "\n")
    status = write_managed_block(dest, headings, allow_append=True)
    assert status == "appended"
    assert dest.read_text().count("## Heading 0") == 2


def test_gitignore_still_appends_without_headings(tmp_path: Path) -> None:
    dest = tmp_path / ".gitignore"
    dest.write_text("*.log\n")
    status = write_gitignore_block(dest)
    assert status == "appended"
    assert "*.log" in dest.read_text()
    assert "BEGIN AGENTSCAFFOLD MANAGED SECTION" in dest.read_text()


def test_lift_keeps_manual_and_writes_bak(tmp_path: Path) -> None:
    from agentscaffold.agents.generate import _lift_legacy_agents_block, render_agents_routing

    dest = tmp_path / "AGENTS.md"
    manual = "## Planning Rules\n\nDo the work.\n"
    dest.write_text("UNMANAGED\n\n" + render_managed_block(manual))
    routing = render_agents_routing(ScaffoldConfig())
    assert _lift_legacy_agents_block(dest, routing)
    text = dest.read_text()
    assert MANAGED_BLOCK_BEGIN not in text
    assert "## Planning Rules" in text
    assert "UNMANAGED" in text
    backup = tmp_path / "AGENTS.md.bak"
    assert backup.is_file()
    assert "BEGIN AGENTSCAFFOLD" in backup.read_text()


def test_lift_skips_already_routing_block(tmp_path: Path) -> None:
    from agentscaffold.agents.generate import _lift_legacy_agents_block, render_agents_routing

    dest = tmp_path / "AGENTS.md"
    routing = render_agents_routing(ScaffoldConfig())
    dest.write_text(render_managed_block(routing))
    assert _lift_legacy_agents_block(dest, routing) is False
    assert MANAGED_BLOCK_BEGIN in dest.read_text()


def test_note_describes_sentinel_not_delete_markers() -> None:
    from agentscaffold.rendering import _MANAGED_BLOCK_NOTE

    assert "agentscaffold: managed=false" in _MANAGED_BLOCK_NOTE
    assert MANAGED_FALSE_SENTINEL not in _MANAGED_BLOCK_NOTE
    assert "Deleting the markers is not ownership" in _MANAGED_BLOCK_NOTE
