from libs.data.providers.alpaca import AlpacaProvider  # noqa: F401
from libs.data.router import DataRouter
from libs.strategy.base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    def generate_signals(self, data):
        router = DataRouter()
        router.fetch("AAPL", 30)
        pass
