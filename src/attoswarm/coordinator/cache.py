"""Generic async-aware LRU cache with TTL for swarm orchestration.

Provides a simple in-memory cache with:
- Maximum size with LRU eviction
- Per-entry TTL (time-to-live)
- Prefix-based invalidation
- Hit/miss/eviction statistics
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CacheStats:
    """Cache performance statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": round(self.hit_rate, 4),
        }


@dataclass(slots=True)
class _CacheEntry:
    """Internal cache entry with value and expiry."""

    value: Any
    expires_at: float


class SwarmCache:
    """In-memory LRU cache with TTL support.

    Usage::

        cache = SwarmCache(max_size=256, default_ttl=300.0)
        cache.put("key", value, ttl=60.0)
        result = cache.get("key")  # returns value or None
        cache.invalidate_prefix("task:")  # remove all keys starting with "task:"
    """

    def __init__(
        self,
        max_size: int = 256,
        default_ttl: float = 300.0,
    ) -> None:
        self._max_size = max(max_size, 1)
        self._default_ttl = default_ttl
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._stats = CacheStats()

    def get(self, key: str) -> Any | None:
        """Get a value by key.  Returns ``None`` on miss or expiry."""
        entry = self._entries.get(key)
        if entry is None:
            self._stats.misses += 1
            return None

        if time.time() > entry.expires_at:
            del self._entries[key]
            self._stats.misses += 1
            return None

        # Move to end (most recently used)
        self._entries.move_to_end(key)
        self._stats.hits += 1
        return entry.value

    def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value with optional TTL override."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + effective_ttl

        if key in self._entries:
            self._entries.move_to_end(key)
            self._entries[key] = _CacheEntry(value=value, expires_at=expires_at)
            return

        # Evict LRU if at capacity
        while len(self._entries) >= self._max_size:
            self._entries.popitem(last=False)
            self._stats.evictions += 1

        self._entries[key] = _CacheEntry(value=value, expires_at=expires_at)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key.  Returns True if it existed."""
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def invalidate_prefix(self, prefix: str) -> int:
        """Remove all entries whose key starts with *prefix*.

        Returns the number of removed entries.
        """
        to_remove = [k for k in self._entries if k.startswith(prefix)]
        for k in to_remove:
            del self._entries[k]
        return len(to_remove)

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()

    @property
    def stats(self) -> CacheStats:
        return self._stats

    @property
    def size(self) -> int:
        return len(self._entries)
