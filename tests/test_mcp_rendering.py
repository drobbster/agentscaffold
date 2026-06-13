"""Tests for agent-facing MCP rendering (Plan 212).

Locks in that composite MCP tools return a readable 'markdown' field and that
structured rows no longer leak dot-qualified query aliases (e.g. 'caller.name').
"""

from __future__ import annotations

from agentscaffold.mcp.render import clean_row, clean_rows, format_context_markdown


def _has_dot_key(obj) -> bool:
    """Recursively check for any dict key containing a '.'."""
    if isinstance(obj, dict):
        return any("." in k for k in obj) or any(_has_dot_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_dot_key(v) for v in obj)
    return False


class TestCleanKeys:
    def test_strips_single_prefix(self):
        assert clean_row({"caller.name": "x", "r.confidence": 0.9}) == {
            "name": "x",
            "confidence": 0.9,
        }

    def test_leaves_clean_keys(self):
        assert clean_row({"name": "x", "count": 3}) == {"name": "x", "count": 3}

    def test_clean_rows_list(self):
        rows = [{"a.path": "p1"}, {"a.path": "p2"}]
        assert clean_rows(rows) == [{"path": "p1"}, {"path": "p2"}]


class TestContextMarkdown:
    def test_renders_sections(self):
        md = format_context_markdown(
            {"name": "foo", "filePath": "a.py", "startLine": 1},
            callers=[{"name": "bar", "filePath": "b.py"}],
            callees=[],
            method_callers=[{"name": "Baz.run", "filePath": "c.py"}],
        )
        assert "## `foo`" in md
        assert "Callers (1)" in md
        assert "Method callers (1)" in md
        assert "Callees (0)" in md


class TestContextTool:
    def test_context_returns_clean_markdown(self, indexed_repo):
        _repo, store = indexed_repo
        from agentscaffold.mcp.server import _tool_context

        rows = store.query('SELECT name AS "fn.name" FROM Function LIMIT 1')
        if not rows:
            import pytest

            pytest.skip("No functions in fixture graph")
        symbol = rows[0]["fn.name"]

        result = _tool_context(store, {"symbol": symbol}, {})
        assert "markdown" in result
        assert isinstance(result["markdown"], str) and result["markdown"]
        # Structured payload must not leak dot-qualified query aliases.
        assert not _has_dot_key(result["symbol"])
        assert not _has_dot_key(result["callers"])
        assert not _has_dot_key(result["callees"])


class TestImpactTool:
    def test_impact_depth_and_clean_rows(self, indexed_repo):
        _repo, store = indexed_repo
        from agentscaffold.mcp.server import _tool_impact

        rows = store.query('SELECT path AS "f.path" FROM File LIMIT 1')
        if not rows:
            import pytest

            pytest.skip("No files in fixture graph")
        target = rows[0]["f.path"]

        result = _tool_impact(store, {"file_or_symbol": target, "depth": 2}, {})
        assert result["depth"] == 2
        assert "markdown" in result
        assert not _has_dot_key(result["direct_importers"])
        assert not _has_dot_key(result["transitive_importers"])
        assert not _has_dot_key(result["callers_into_file"])
