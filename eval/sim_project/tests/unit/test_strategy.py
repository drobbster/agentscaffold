"""Tests for trading strategies."""

from libs.data.router import DataRouter
from libs.strategy.momentum import MomentumStrategy


def test_momentum_signal():
    router = DataRouter()
    strategy = MomentumStrategy(router)
    signal = strategy.generate_signal("AAPL")
    assert signal["signal"] in ("buy", "sell", "hold")


def test_momentum_params():
    router = DataRouter()
    strategy = MomentumStrategy(router, lookback=10, threshold=0.01)
    params = strategy.get_parameters()
    assert params["lookback"] == 10
