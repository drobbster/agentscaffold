"""API route handlers."""

from libs.data.router import DataRouter
from libs.risk.manager import RiskManager
from libs.strategy.momentum import MomentumStrategy


def get_quote(symbol: str) -> dict:
    router = DataRouter()
    return router.fetch(symbol)


def get_signal(symbol: str) -> dict:
    router = DataRouter()
    strategy = MomentumStrategy(router)
    return strategy.generate_signal(symbol)


def get_health() -> dict:
    router = DataRouter()
    return {
        "providers": router.health_check(),
        "status": "ok",
    }


def submit_order(symbol: str, signal: dict) -> dict:
    router = DataRouter()
    risk = RiskManager()
    from libs.execution.engine import ExecutionEngine  # noqa: F401

    engine = ExecutionEngine(router, risk)
    return engine.submit(symbol, signal)
