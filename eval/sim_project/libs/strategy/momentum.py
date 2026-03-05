"""Momentum-based trading strategy."""

from libs.data.router import DataRouter
from libs.strategy.base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    """Simple momentum strategy based on price change."""

    def __init__(self, router: DataRouter, lookback: int = 20, threshold: float = 0.02):
        super().__init__(router)
        self._lookback = lookback
        self._threshold = threshold

    def generate_signal(self, symbol: str) -> dict:
        data = self._router.fetch(symbol)
        price = data.get("close", 0)
        open_price = data.get("open", 0)

        if open_price == 0:
            return {"signal": "hold", "strength": 0.0}

        change = (price - open_price) / open_price

        if change > self._threshold:
            return {"signal": "buy", "strength": min(change / self._threshold, 1.0)}
        elif change < -self._threshold:
            return {"signal": "sell", "strength": min(abs(change) / self._threshold, 1.0)}
        return {"signal": "hold", "strength": 0.0}

    def get_parameters(self) -> dict:
        return {"lookback": self._lookback, "threshold": self._threshold}
