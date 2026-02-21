"""Tests for semantic cache module."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from attocode.integrations.context.semantic_cache import (
    CacheEntry,
    SemanticCacheConfig,
    SemanticCacheManager,
    cosine_similarity,
)


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        vec = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_empty_vectors(self) -> None:
        assert cosine_similarity([], []) == 0.0

    def test_different_lengths(self) -> None:
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestSemanticCacheManager:
    def test_disabled_cache_returns_none(self) -> None:
        config = SemanticCacheConfig(enabled=False)
        cache = SemanticCacheManager(config)
        cache.put("key", "value")
        assert cache.get("key") is None
        assert cache.size == 0

    def test_put_and_get_exact_match(self) -> None:
        config = SemanticCacheConfig(enabled=True)
        cache = SemanticCacheManager(config)
        cache.put("hello world", "response-1")
        result = cache.get("hello world")
        assert result == "response-1"

    def test_get_miss(self) -> None:
        config = SemanticCacheConfig(enabled=True)
        cache = SemanticCacheManager(config)
        assert cache.get("nonexistent") is None

    def test_semantic_similarity_hit(self) -> None:
        config = SemanticCacheConfig(enabled=True, threshold=0.9)
        cache = SemanticCacheManager(config)
        embedding_a = [1.0, 0.0, 0.0]
        embedding_b = [0.99, 0.05, 0.01]  # very similar to a
        cache.put("query-a", "response-a", embedding=embedding_a)
        result = cache.get("query-b", embedding=embedding_b)
        assert result == "response-a"

    def test_semantic_similarity_miss_below_threshold(self) -> None:
        config = SemanticCacheConfig(enabled=True, threshold=0.99)
        cache = SemanticCacheManager(config)
        embedding_a = [1.0, 0.0, 0.0]
        embedding_b = [0.5, 0.5, 0.5]  # not similar enough
        cache.put("query-a", "response-a", embedding=embedding_a)
        result = cache.get("query-b", embedding=embedding_b)
        assert result is None

    def test_lru_eviction(self) -> None:
        config = SemanticCacheConfig(enabled=True, max_size=3)
        cache = SemanticCacheManager(config)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")
        assert cache.size == 3
        cache.put("k4", "v4")  # should evict k1
        assert cache.size == 3
        assert cache.get("k1") is None
        assert cache.get("k4") == "v4"
        stats = cache.get_stats()
        assert stats["evictions"] >= 1

    def test_ttl_expiry(self) -> None:
        config = SemanticCacheConfig(enabled=True, ttl=1)
        cache = SemanticCacheManager(config)

        # Patch time.monotonic to simulate time passing
        initial_time = time.monotonic()
        with patch("attocode.integrations.context.semantic_cache.time.monotonic", return_value=initial_time):
            cache.put("key", "value")

        # Access at initial_time + 0.5s (within TTL)
        with patch("attocode.integrations.context.semantic_cache.time.monotonic", return_value=initial_time + 0.5):
            assert cache.get("key") == "value"

        # Access at initial_time + 2s (past TTL)
        with patch("attocode.integrations.context.semantic_cache.time.monotonic", return_value=initial_time + 2.0):
            assert cache.get("key") is None

    def test_invalidate(self) -> None:
        config = SemanticCacheConfig(enabled=True)
        cache = SemanticCacheManager(config)
        cache.put("key", "value")
        assert cache.invalidate("key") is True
        assert cache.get("key") is None
        assert cache.invalidate("key") is False

    def test_clear(self) -> None:
        config = SemanticCacheConfig(enabled=True)
        cache = SemanticCacheManager(config)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        assert cache.size == 2
        cache.clear()
        assert cache.size == 0

    def test_stats_tracking(self) -> None:
        config = SemanticCacheConfig(enabled=True)
        cache = SemanticCacheManager(config)
        cache.put("key", "value")
        cache.get("key")   # hit
        cache.get("key")   # hit
        cache.get("miss")  # miss
        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["size"] == 1

    def test_hit_count_incremented(self) -> None:
        config = SemanticCacheConfig(enabled=True)
        cache = SemanticCacheManager(config)
        cache.put("key", "value")
        cache.get("key")
        cache.get("key")
        stats = cache.get_stats()
        assert stats["hits"] == 2
