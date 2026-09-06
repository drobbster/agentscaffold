"""Plan 270: symbol spot-checks skip Title-case prose."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.mcp.diff_plan import _is_symbol_token, _symbol_spot_check


def test_prose_tokens_are_not_symbols() -> None:
    assert not _is_symbol_token("Added")
    assert not _is_symbol_token("Listed")
    assert not _is_symbol_token("Reversed")
    assert not _is_symbol_token("Medium")
    assert not _is_symbol_token("Owns")
    assert not _is_symbol_token("L261")
    assert _is_symbol_token("WidgetFactory")
    assert _is_symbol_token("source_has_tests")


def test_spot_check_skips_prose_on_plan_line(tmp_path: Path) -> None:
    src = tmp_path / "widget.py"
    src.write_text("class WidgetFactory:\n    pass\n", encoding="utf-8")
    plan = (
        "| File | Change Type | Notes |\n"
        "| `widget.py` | MODIFY | Added Listed Reversed Medium WidgetFactory |\n"
    )
    result = _symbol_spot_check(src, plan, "MODIFY", rel_path="widget.py")
    assert result is not None
    assert "WidgetFactory" in result["found_symbols"]
    assert "Added" not in result["checked_symbols"]
    assert "Listed" not in result["missing_symbols"]
    assert "Reversed" not in result["missing_symbols"]
    assert "Medium" not in result["missing_symbols"]
