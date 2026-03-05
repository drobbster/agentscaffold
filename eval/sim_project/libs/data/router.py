"""Central data router that dispatches to providers."""

from libs.data.cache import DataCache
from libs.data.providers.alpaca import AlpacaProvider
from libs.data.providers.base import BaseProvider
from libs.data.providers.polygon import PolygonProvider


class DataRouter:
    """Routes data requests to the appropriate provider with caching."""

    def __init__(self, cache: DataCache | None = None):
        self._providers: dict[str, BaseProvider] = {}
        self._cache = cache or DataCache()
        self._register_defaults()

    def _register_defaults(self):
        self._providers["alpaca"] = AlpacaProvider()
        self._providers["polygon"] = PolygonProvider()

    def register(self, name: str, provider: BaseProvider):
        self._providers[name] = provider

    def fetch(self, symbol: str, provider: str = "alpaca") -> dict:
        cache_key = f"{provider}:{symbol}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        p = self._providers.get(provider)
        if p is None:
            raise ValueError(f"Unknown provider: {provider}")

        data = p.fetch(symbol)
        self._cache.set(cache_key, data)
        return data

    def fetch_batch(self, symbols: list[str], provider: str = "alpaca") -> list[dict]:
        return [self.fetch(s, provider) for s in symbols]

    def get_providers(self) -> list[str]:
        return list(self._providers.keys())

    def health_check(self) -> dict[str, bool]:
        results = {}
        for name, p in self._providers.items():
            try:
                p.validate()
                results[name] = True
            except Exception:
                results[name] = False
        return results
