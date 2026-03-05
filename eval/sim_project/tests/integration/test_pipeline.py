"""Integration tests for pipeline flows."""

from pipeline.flows.daily_ingest import run_daily_ingest


def test_daily_ingest():
    result = run_daily_ingest()
    assert result["success"] > 0
    assert result["failed"] == 0
