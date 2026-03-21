"""Tests for SwarmCache."""

from __future__ import annotations

import time

from attoswarm.coordinator.cache import SwarmCache


class TestSwarmCache:
    def test_put_and_get(self) -> None:
        cache = SwarmCache()
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_miss(self) -> None:
        cache = SwarmCache()
        assert cache.get("missing") is None
        assert cache.stats.misses == 1

    def test_hit_tracking(self) -> None:
        cache = SwarmCache()
        cache.put("k1", "v1")
        cache.get("k1")
        assert cache.stats.hits == 1

    def test_ttl_expiry(self) -> None:
        cache = SwarmCache(default_ttl=0.01)
        cache.put("k1", "v1")
        time.sleep(0.02)
        assert cache.get("k1") is None
        assert cache.stats.misses == 1

    def test_ttl_override(self) -> None:
        cache = SwarmCache(default_ttl=100.0)
        cache.put("k1", "v1", ttl=0.01)
        time.sleep(0.02)
        assert cache.get("k1") is None

    def test_lru_eviction(self) -> None:
        cache = SwarmCache(max_size=2)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")  # evicts k1
        assert cache.get("k1") is None
        assert cache.get("k2") == "v2"
        assert cache.get("k3") == "v3"
        assert cache.stats.evictions == 1

    def test_invalidate(self) -> None:
        cache = SwarmCache()
        cache.put("k1", "v1")
        assert cache.invalidate("k1") is True
        assert cache.get("k1") is None
        assert cache.invalidate("k1") is False

    def test_invalidate_prefix(self) -> None:
        cache = SwarmCache()
        cache.put("task:1", "a")
        cache.put("task:2", "b")
        cache.put("other:1", "c")
        removed = cache.invalidate_prefix("task:")
        assert removed == 2
        assert cache.get("task:1") is None
        assert cache.get("other:1") == "c"

    def test_clear(self) -> None:
        cache = SwarmCache()
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert cache.size == 0

    def test_update_existing_key(self) -> None:
        cache = SwarmCache()
        cache.put("k1", "v1")
        cache.put("k1", "v2")
        assert cache.get("k1") == "v2"
        assert cache.size == 1
