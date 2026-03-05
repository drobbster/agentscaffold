from libs.data.router import DataRouter


def run_daily_flow():
    router = DataRouter()
    router.fetch_batch(["AAPL", "GOOG"])
    pass
