"""In-memory data cache with TTL support."""

import time


class DataCache:
    """Simple TTL cache for market data."""

    def __init__(self, ttl_seconds: int = 300):
        self._store: dict[str, tuple[float, dict]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> dict | None:
        if key not in self._store:
            return None
        ts, data = self._store[key]
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        return data

    def set(self, key: str, data: dict) -> None:
        self._store[key] = (time.time(), data)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def size(self) -> int:
        return len(self._store)
