"""Signal generation flow."""

from libs.data.router import DataRouter
from libs.risk.manager import RiskManager
from libs.strategy.mean_reversion import MeanReversionStrategy
from libs.strategy.momentum import MomentumStrategy


def run_signal_generation(symbols: list[str] | None = None) -> list[dict]:
    """Generate signals for all strategies across the universe."""
    if symbols is None:
        symbols = ["AAPL", "MSFT", "GOOGL"]

    router = DataRouter()
    risk = RiskManager()

    strategies = [
        ("momentum", MomentumStrategy(router)),
        ("mean_reversion", MeanReversionStrategy(router)),
    ]

    signals = []
    for symbol in symbols:
        for name, strategy in strategies:
            signal = strategy.generate_signal(symbol)
            check = risk.check_signal(signal, symbol)
            signals.append(
                {
                    "symbol": symbol,
                    "strategy": name,
                    "signal": signal,
                    "risk_check": check,
                }
            )

    return signals
