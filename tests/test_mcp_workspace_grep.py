"""Plan 246: workspace grep sandbox."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.mcp.workspace_grep import workspace_grep


def test_grep_finds_hit(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def normalize_feeds():\n    pass\n", encoding="utf-8")
    result = workspace_grep(tmp_path, "normalize_feeds", glob="*.py")
    assert result["count"] >= 1
    assert any("normalize_feeds" in h["text"] for h in result["hits"])


def test_grep_rejects_path_escape(tmp_path: Path) -> None:
    result = workspace_grep(tmp_path, "x", path="../outside")
    assert result.get("sandbox_rejected") is True
