"""Order execution engine."""

from libs.data.router import DataRouter
from libs.risk.manager import RiskManager


class ExecutionEngine:
    """Executes approved trading signals."""

    def __init__(self, router: DataRouter, risk_manager: RiskManager):
        self._router = router
        self._risk = risk_manager
        self._orders: list[dict] = []

    def submit(self, symbol: str, signal: dict) -> dict:
        check = self._risk.check_signal(signal, symbol)
        if not check.get("approved"):
            return {"status": "rejected", "reason": check.get("reason")}

        order = {
            "symbol": symbol,
            "side": signal["signal"],
            "size": check.get("size", 0),
            "status": "filled",
        }
        self._orders.append(order)
        return order

    def get_orders(self) -> list[dict]:
        return list(self._orders)

    def cancel_all(self) -> int:
        count = len(self._orders)
        self._orders.clear()
        return count
