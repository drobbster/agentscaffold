class DataRouter:
    def fetch(self, symbol: str, lookback: int):
        pass

    def fetch_batch(self, symbols: list[str]):
        pass

    def get_latest(self, symbol: str):
        pass


def create_router():
    return DataRouter()
