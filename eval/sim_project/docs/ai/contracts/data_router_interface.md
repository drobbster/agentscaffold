# Data Router Interface Contract

Version | v1.3
Last Updated | 2025-12-01

## DataRouter

```python
class DataRouter:
    def fetch(symbol: str, provider: str = "alpaca") -> dict
    def fetch_batch(symbols: list[str], provider: str = "alpaca") -> list[dict]
    def register(name: str, provider: BaseProvider) -> None
    def get_providers() -> list[str]
    def health_check() -> dict[str, bool]
```

## BaseProvider

```python
class BaseProvider(ABC):
    def fetch(symbol: str) -> dict
    def fetch_historical(symbol: str, start: str, end: str) -> list[dict]
    def validate() -> bool
```

## Consumers
- libs/strategy/base.py (via constructor injection)
- libs/execution/engine.py (via constructor injection)
- services/api/routes.py (direct instantiation)
- pipeline/flows/daily_ingest.py (direct instantiation)
