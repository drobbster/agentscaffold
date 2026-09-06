"""Plan 270: ADR ingest accepts bold Status/Date metadata."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.graph.governance import _parse_adr


def test_parse_adr_bold_status_and_date(tmp_path: Path) -> None:
    path = tmp_path / "025-example.md"
    path.write_text(
        "# ADR-025: Example\n\n**Status**: Accepted\n**Date**: 2026-03-01\n\n## Context\n\nBody.\n",
        encoding="utf-8",
    )
    parsed = _parse_adr(path)
    assert parsed is not None
    assert parsed["status"] == "Accepted"
    assert parsed["date"] == "2026-03-01"
    assert parsed["number"] == 25


def test_parse_adr_heading_status_still_works(tmp_path: Path) -> None:
    path = tmp_path / "026-headed.md"
    path.write_text(
        "# ADR-026: Headed\n\n## Status\n\nSuperseded\n\n## Date\n\n2026-04-01\n",
        encoding="utf-8",
    )
    parsed = _parse_adr(path)
    assert parsed is not None
    assert parsed["status"] == "Superseded"
    assert parsed["date"] == "2026-04-01"
