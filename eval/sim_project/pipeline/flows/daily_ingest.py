"""Daily data ingestion flow."""

from libs.data.normalizer import validate_ohlcv
from libs.data.router import DataRouter

UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA"]


def run_daily_ingest(provider: str = "alpaca") -> dict:
    """Fetch and validate daily data for the universe."""
    router = DataRouter()
    results = {"success": 0, "failed": 0, "errors": []}

    for symbol in UNIVERSE:
        try:
            data = router.fetch(symbol, provider)
            errors = validate_ohlcv(data)
            if errors:
                results["errors"].append({"symbol": symbol, "issues": errors})
                results["failed"] += 1
            else:
                results["success"] += 1
        except Exception as exc:
            results["errors"].append({"symbol": symbol, "issues": [str(exc)]})
            results["failed"] += 1

    return results
