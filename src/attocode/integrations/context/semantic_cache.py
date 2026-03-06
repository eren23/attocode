"""Semantic cache using embedding similarity.

Caches LLM responses keyed by input similarity. Uses cosine similarity
between embeddings to find cache hits above a configurable threshold.
Falls back to exact-match hashing when embeddings aren't available.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SemanticCacheConfig:
    """Semantic cache configuration."""

    enabled: bool = False
    threshold: float = 0.95  # Cosine similarity threshold for cache hit
    max_size: int = 1_000
    ttl: int = 0  # Seconds, 0 = no expiry


@dataclass(slots=True)
class CacheEntry:
    """A cached response."""

    key_hash: str
    embedding: list[float] | None
    response: Any
    timestamp: float
    hit_count: int = 0


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticCacheManager:
    """Embedding-based response cache.

    Stores LLM responses keyed by input embeddings. When a new query
    arrives, checks similarity against cached entries. If above threshold,
    returns the cached response without calling the LLM.

    Falls back to exact string hash matching when embeddings are not
    provided.
    """

    def __init__(self, config: SemanticCacheConfig | None = None) -> None:
        self.config = config or SemanticCacheConfig()
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}

    def get(
        self,
        key: str,
        embedding: list[float] | None = None,
    ) -> Any | None:
        """Look up a cached response.

        First tries exact hash match, then falls back to semantic
        similarity if embeddings are available.
        """
        if not self.config.enabled:
            return None

        now = time.monotonic()

        # Exact match
        key_hash = self._hash(key)
        if key_hash in self._entries:
            entry = self._entries[key_hash]
            if self._is_valid(entry, now):
                entry.hit_count += 1
                self._stats["hits"] += 1
                self._entries.move_to_end(key_hash)
                return entry.response
            else:
                del self._entries[key_hash]

        # Semantic match
        if embedding is not None:
            best_entry: CacheEntry | None = None
            best_sim = 0.0
            expired_keys: list[str] = []

            for k, entry in self._entries.items():
                if not self._is_valid(entry, now):
                    expired_keys.append(k)
                    continue
                if entry.embedding is not None:
                    sim = cosine_similarity(embedding, entry.embedding)
                    if sim > best_sim:
                        best_sim = sim
                        best_entry = entry

            # Clean expired
            for k in expired_keys:
                del self._entries[k]

            if best_entry is not None and best_sim >= self.config.threshold:
                best_entry.hit_count += 1
                self._stats["hits"] += 1
                return best_entry.response

        self._stats["misses"] += 1
        return None

    def put(
        self,
        key: str,
        response: Any,
        embedding: list[float] | None = None,
    ) -> None:
        """Store a response in the cache."""
        if not self.config.enabled:
            return

        key_hash = self._hash(key)

        # Evict if at capacity
        while len(self._entries) >= self.config.max_size:
            evicted_key, _ = self._entries.popitem(last=False)
            self._stats["evictions"] += 1

        self._entries[key_hash] = CacheEntry(
            key_hash=key_hash,
            embedding=embedding,
            response=response,
            timestamp=time.monotonic(),
        )

    def invalidate(self, key: str) -> bool:
        """Remove a specific entry. Returns True if found."""
        key_hash = self._hash(key)
        if key_hash in self._entries:
            del self._entries[key_hash]
            return True
        return False

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)

    def get_stats(self) -> dict[str, int]:
        """Cache statistics."""
        return {
            **self._stats,
            "size": len(self._entries),
            "max_size": self.config.max_size,
        }

    def _hash(self, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _is_valid(self, entry: CacheEntry, now: float) -> bool:
        if self.config.ttl <= 0:
            return True
        return (now - entry.timestamp) < self.config.ttl
