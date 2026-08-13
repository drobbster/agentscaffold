"""The MCP extra must not pull an SDK that dropped our Server API.

0.10.6 left the extra unbounded (``mcp>=1.0.0``). A fresh extras install then
resolved mcp 2.0, whose ``Server`` has no ``list_tools``, so the process died
before handshake. Pinning lives in ``pyproject.toml``; this test is what keeps
the pin from being widened again without someone noticing.
"""

from __future__ import annotations

from pathlib import Path


def test_mcp_extra_refuses_sdk_2() -> None:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert '"mcp>=1.0.0,<2"' in text
    assert '"mcp>=1.0.0"' not in text


def test_duckpgq_extra_refuses_duckdb_without_duckpgq() -> None:
    """1.5.5 has no community duckpgq build (HTTP 404), so graphs cannot open."""
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert '"duckdb>=0.10.0,<1.5.5"' in text
    assert '"duckdb>=0.10.0"' not in text
