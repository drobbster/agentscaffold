"""Tests for data cache."""

from libs.data.cache import DataCache


def test_cache_set_get():
    cache = DataCache()
    cache.set("key1", {"value": 1})
    assert cache.get("key1") == {"value": 1}


def test_cache_miss():
    cache = DataCache()
    assert cache.get("missing") is None
