"""Tests for risk management."""

from libs.risk.manager import RiskManager


def test_risk_check_hold():
    rm = RiskManager()
    result = rm.check_signal({"signal": "hold"}, "AAPL")
    assert result["approved"] is True


def test_risk_drawdown_limit():
    rm = RiskManager(max_drawdown=0.1)
    rm.update_portfolio(80000)
    result = rm.check_signal({"signal": "buy", "strength": 0.5}, "AAPL")
    assert result["approved"] is False
