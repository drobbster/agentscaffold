"""Secondary-project data routing fixture for multi-project evals."""

from __future__ import annotations


class DataRouter:
    """Route market data requests for the sibling project."""

    def __init__(self, providers: dict[str, object] | None = None) -> None:
        self.providers = providers or {}

    def route(self, symbol: str) -> str:
        """Return the provider key for a symbol."""
        if symbol.endswith(".CRYPTO"):
            return "crypto"
        return "equities"


def normalize_symbol(symbol: str) -> str:
    """Normalize a symbol before data-provider routing."""
    return symbol.strip().upper().replace("/", "-")
