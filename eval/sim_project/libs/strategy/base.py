"""Base strategy interface."""

from abc import ABC, abstractmethod

from libs.data.router import DataRouter


class BaseStrategy(ABC):
    """Abstract base for trading strategies."""

    def __init__(self, router: DataRouter):
        self._router = router
        self._position = 0.0
        self._entry_price = 0.0  # noqa: F841

    @abstractmethod
    def generate_signal(self, symbol: str) -> dict:
        """Generate a trading signal for a symbol."""

    @abstractmethod
    def get_parameters(self) -> dict:
        """Return strategy parameters."""

    def get_position(self) -> float:
        return self._position

    def reset(self):
        self._position = 0.0
        self._entry_price = 0.0
