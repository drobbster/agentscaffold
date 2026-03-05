"""Risk management module."""

from libs.risk.position_sizer import PositionSizer


class RiskManager:
    """Evaluates and enforces risk constraints."""

    def __init__(self, max_position_pct: float = 0.1, max_drawdown: float = 0.2):
        self._max_position_pct = max_position_pct
        self._max_drawdown = max_drawdown
        self._sizer = PositionSizer()
        self._portfolio_value = 100000.0
        self._peak_value = 100000.0

    def check_signal(self, signal: dict, symbol: str) -> dict:
        """Validate a signal against risk constraints."""
        if signal.get("signal") == "hold":
            return {"approved": True, "reason": "no action"}

        drawdown = self._current_drawdown()
        if drawdown > self._max_drawdown:
            return {"approved": False, "reason": f"drawdown {drawdown:.2%} exceeds limit"}

        size = self._sizer.calculate(signal, self._portfolio_value, self._max_position_pct)
        return {"approved": True, "size": size, "reason": "within limits"}

    def update_portfolio(self, value: float):
        self._portfolio_value = value
        self._peak_value = max(self._peak_value, value)

    def _current_drawdown(self) -> float:
        if self._peak_value == 0:
            return 0.0
        return (self._peak_value - self._portfolio_value) / self._peak_value

    def get_limits(self) -> dict:
        return {
            "max_position_pct": self._max_position_pct,
            "max_drawdown": self._max_drawdown,
        }
