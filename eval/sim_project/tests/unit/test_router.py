"""Tests for data router."""

from libs.data.router import DataRouter


def test_router_fetch():
    router = DataRouter()
    data = router.fetch("AAPL")
    assert "close" in data


def test_router_providers():
    router = DataRouter()
    providers = router.get_providers()
    assert "alpaca" in providers
    assert "polygon" in providers
