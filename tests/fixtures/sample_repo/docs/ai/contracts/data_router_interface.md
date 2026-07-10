# Data Router Interface Contract

| Field | Value |
|-------|-------|
| Version | v1.2 |
| Last Updated | 2026-02-20 |

## Exported Functions

- `fetch(symbol: str, lookback: int = 30) -> DataFrame`
- `fetch_batch(symbols: list[str]) -> dict[str, DataFrame]`

## Exported Classes

- `DataRouter`
- `DataProvider`

## Reference Declaration

```python
class DataRouter:
    def fetch(self, symbol, lookback): ...
    def fetch_batch(self, symbols): ...
```
