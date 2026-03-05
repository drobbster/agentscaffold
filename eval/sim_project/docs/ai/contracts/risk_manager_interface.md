# Risk Manager Interface Contract

Version | v1.0
Last Updated | 2026-01-10

## RiskManager

```python
class RiskManager:
    def check_signal(signal: dict, symbol: str) -> dict
    def update_portfolio(value: float) -> None
    def get_limits() -> dict
```

## PositionSizer

```python
class PositionSizer:
    def calculate(signal: dict, portfolio_value: float, max_pct: float) -> float
    def kelly_criterion(win_rate: float, win_loss_ratio: float) -> float
```

## Consumers
- libs/execution/engine.py
- services/api/routes.py
- pipeline/flows/signal_generation.py
