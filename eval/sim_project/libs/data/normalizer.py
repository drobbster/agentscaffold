"""Data normalization utilities."""


def normalize_ohlcv(raw: dict) -> dict:
    """Normalize raw OHLCV data to standard format."""
    return {
        "open": float(raw.get("o", raw.get("open", 0))),
        "high": float(raw.get("h", raw.get("high", 0))),
        "low": float(raw.get("l", raw.get("low", 0))),
        "close": float(raw.get("c", raw.get("close", 0))),
        "volume": int(raw.get("v", raw.get("volume", 0))),
        "timestamp": raw.get("t", raw.get("timestamp", "")),
    }


def normalize_batch(rows: list[dict]) -> list[dict]:
    return [normalize_ohlcv(r) for r in rows]


def validate_ohlcv(data: dict) -> list[str]:
    """Return list of validation errors."""
    errors = []
    if data.get("high", 0) < data.get("low", 0):
        errors.append("high < low")
    if data.get("volume", 0) < 0:
        errors.append("negative volume")
    if not data.get("timestamp"):
        errors.append("missing timestamp")
    return errors
