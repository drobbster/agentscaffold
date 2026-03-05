"""Polygon.io market data provider."""

from libs.data.normalizer import normalize_ohlcv
from libs.data.providers.base import BaseProvider


class PolygonProvider(BaseProvider):
    """Fetches data from Polygon.io API."""

    def __init__(self, api_key: str = ""):
        self._api_key = api_key

    def fetch(self, symbol: str) -> dict:
        raw = self._mock_fetch(symbol)
        return normalize_ohlcv(raw)

    def fetch_historical(self, symbol: str, start: str, end: str) -> list[dict]:
        return [self._mock_fetch(symbol)]

    def validate(self) -> bool:
        return True

    def _mock_fetch(self, symbol: str) -> dict:
        return {
            "open": 150.0,
            "high": 155.0,
            "low": 148.0,
            "close": 153.0,
            "volume": 1000000,
            "timestamp": "2025-01-15T16:00:00Z",
        }
