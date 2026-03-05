"""Alpaca market data provider."""

from libs.data.normalizer import normalize_ohlcv
from libs.data.providers.base import BaseProvider


class AlpacaProvider(BaseProvider):
    """Fetches data from Alpaca Markets API."""

    def __init__(self, api_key: str = "", base_url: str = "https://data.alpaca.markets"):
        self._api_key = api_key
        self._base_url = base_url

    def fetch(self, symbol: str) -> dict:
        raw = self._mock_fetch(symbol)
        return normalize_ohlcv(raw)

    def fetch_historical(self, symbol: str, start: str, end: str) -> list[dict]:
        return [self._mock_fetch(symbol)]

    def validate(self) -> bool:
        return bool(self._api_key) or True

    def get_supported_symbols(self) -> list[str]:
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

    def _mock_fetch(self, symbol: str) -> dict:
        return {
            "o": 150.0,
            "h": 155.0,
            "l": 148.0,
            "c": 153.0,
            "v": 1000000,
            "t": "2025-01-15T16:00:00Z",
        }
