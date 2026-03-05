"""Tests for data normalizer."""

from libs.data.normalizer import normalize_ohlcv, validate_ohlcv


def test_normalize_alpaca_format():
    raw = {"o": 100, "h": 110, "l": 95, "c": 105, "v": 5000, "t": "2025-01-01"}
    result = normalize_ohlcv(raw)
    assert result["open"] == 100.0
    assert result["close"] == 105.0


def test_validate_ok():
    data = {"high": 110, "low": 95, "volume": 5000, "timestamp": "2025-01-01"}
    assert validate_ohlcv(data) == []


def test_validate_high_low():
    data = {"high": 90, "low": 95, "volume": 5000, "timestamp": "2025-01-01"}
    errors = validate_ohlcv(data)
    assert "high < low" in errors
