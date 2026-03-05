from libs.data.router import DataRouter


class RiskManager:
    def __init__(self):
        self.router = DataRouter()

    def evaluate(self, position):
        self.router.get_latest("AAPL")
        pass

    def check_limits(self, position):
        pass
