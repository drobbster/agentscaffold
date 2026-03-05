# Execution Engine Interface Contract

Version | v0.1
Last Updated | 2026-01-10

## ExecutionEngine

```python
class ExecutionEngine:
    def submit(symbol: str, signal: dict) -> dict
    def get_orders() -> list[dict]
    def cancel_all() -> int
    def get_fill_rate() -> float  # NOT YET IMPLEMENTED -- contract drift
```

## Consumers
- services/api/routes.py
