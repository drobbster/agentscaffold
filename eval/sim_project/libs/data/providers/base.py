"""Base data provider interface."""

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Abstract base for all market data providers."""

    @abstractmethod
    def fetch(self, symbol: str) -> dict:
        """Fetch latest data for a symbol."""

    @abstractmethod
    def fetch_historical(self, symbol: str, start: str, end: str) -> list[dict]:
        """Fetch historical data for a date range."""

    def validate(self) -> bool:
        """Validate provider connectivity. Override for real checks."""
        return True

    def get_supported_symbols(self) -> list[str]:
        """Return list of supported symbols. Override per provider."""
        return []
