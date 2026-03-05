"""Mean reversion trading strategy."""

from libs.data.router import DataRouter
from libs.strategy.base import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion strategy based on deviation from average."""

    def __init__(self, router: DataRouter, window: int = 50, std_dev: float = 2.0):
        super().__init__(router)
        self._window = window
        self._std_dev = std_dev
        self._history: list[float] = []

    def generate_signal(self, symbol: str) -> dict:
        data = self._router.fetch(symbol)
        price = data.get("close", 0)
        self._history.append(price)

        if len(self._history) < self._window:
            return {"signal": "hold", "strength": 0.0}

        window = self._history[-self._window :]
        mean = sum(window) / len(window)
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        std = variance**0.5

        if std == 0:
            return {"signal": "hold", "strength": 0.0}

        z_score = (price - mean) / std

        if z_score < -self._std_dev:
            return {"signal": "buy", "strength": min(abs(z_score) / self._std_dev, 1.0)}
        elif z_score > self._std_dev:
            return {"signal": "sell", "strength": min(z_score / self._std_dev, 1.0)}
        return {"signal": "hold", "strength": 0.0}

    def get_parameters(self) -> dict:
        return {"window": self._window, "std_dev": self._std_dev}
