from libs.data.router import DataRouter  # noqa: F401


class BaseStrategy:
    def generate_signals(self, data):
        pass
