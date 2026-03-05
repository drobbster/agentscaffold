"""API middleware for logging and rate limiting."""

import time


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._requests: list[float] = []

    def allow(self) -> bool:
        now = time.time()
        self._requests = [t for t in self._requests if now - t < self._window]
        if len(self._requests) >= self._max:
            return False
        self._requests.append(now)
        return True


class RequestLogger:
    """Logs API requests."""

    def __init__(self):
        self._log: list[dict] = []

    def log(self, method: str, path: str, status: int):
        self._log.append(
            {
                "method": method,
                "path": path,
                "status": status,
                "timestamp": time.time(),
            }
        )

    def get_recent(self, count: int = 10) -> list[dict]:
        return self._log[-count:]
