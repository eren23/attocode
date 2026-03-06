"""LRU file content cache with invalidation.

Caches file contents in memory with LRU eviction and
mtime-based invalidation for fast repeated reads.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CacheEntry:
    """A cached file entry."""

    path: str
    content: str
    mtime: float
    size: int
    cached_at: float
    hit_count: int = 0


@dataclass(slots=True)
class FileCacheStats:
    """Cache statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0
    total_bytes_cached: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class FileCache:
    """LRU file content cache with mtime-based invalidation.

    Keeps file contents in memory for fast access. Files are
    automatically invalidated when their mtime changes.

    Args:
        max_entries: Maximum number of files to cache.
        max_total_bytes: Maximum total bytes of cached content.
        ttl_seconds: Time-to-live for cache entries (0 = no TTL).
    """

    def __init__(
        self,
        *,
        max_entries: int = 500,
        max_total_bytes: int = 50_000_000,  # 50 MB
        ttl_seconds: float = 0,
    ) -> None:
        self._max_entries = max_entries
        self._max_total_bytes = max_total_bytes
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._total_bytes = 0
        self._stats = FileCacheStats()

    @property
    def stats(self) -> FileCacheStats:
        return self._stats

    @property
    def size(self) -> int:
        """Number of cached entries."""
        return len(self._cache)

    def get(self, file_path: str) -> str | None:
        """Get cached file content, or None if not cached/stale.

        Validates mtime to detect external changes.
        Returns None on cache miss or stale entry.
        """
        path = os.path.abspath(file_path)
        entry = self._cache.get(path)

        if entry is None:
            self._stats.misses += 1
            return None

        # Check TTL
        if self._ttl_seconds > 0:
            age = time.monotonic() - entry.cached_at
            if age > self._ttl_seconds:
                self._invalidate(path)
                self._stats.misses += 1
                return None

        # Check mtime for staleness
        try:
            current_mtime = os.path.getmtime(path)
            if current_mtime != entry.mtime:
                self._invalidate(path)
                self._stats.misses += 1
                return None
        except OSError:
            self._invalidate(path)
            self._stats.misses += 1
            return None

        # Cache hit — move to end (most recently used)
        self._cache.move_to_end(path)
        entry.hit_count += 1
        self._stats.hits += 1
        return entry.content

    def put(self, file_path: str, content: str) -> None:
        """Cache file content.

        Evicts least-recently-used entries if capacity is exceeded.
        """
        path = os.path.abspath(file_path)
        size = len(content.encode("utf-8", errors="replace"))

        # Remove old entry if exists
        if path in self._cache:
            self._remove(path)

        # Don't cache files larger than 25% of max total
        if size > self._max_total_bytes // 4:
            return

        # Evict until we have space
        while (
            len(self._cache) >= self._max_entries
            or self._total_bytes + size > self._max_total_bytes
        ) and self._cache:
            self._evict_lru()

        # Get mtime
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0

        entry = CacheEntry(
            path=path,
            content=content,
            mtime=mtime,
            size=size,
            cached_at=time.monotonic(),
        )
        self._cache[path] = entry
        self._total_bytes += size
        self._stats.total_bytes_cached = self._total_bytes

    def invalidate(self, file_path: str) -> bool:
        """Invalidate a specific cache entry. Returns True if entry existed."""
        path = os.path.abspath(file_path)
        return self._invalidate(path)

    def invalidate_dir(self, dir_path: str) -> int:
        """Invalidate all cached files under a directory. Returns count."""
        prefix = os.path.abspath(dir_path) + os.sep
        to_remove = [p for p in self._cache if p.startswith(prefix)]
        for path in to_remove:
            self._invalidate(path)
        return len(to_remove)

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()
        self._total_bytes = 0
        self._stats.total_bytes_cached = 0

    def get_or_read(self, file_path: str) -> str | None:
        """Get from cache or read from disk. Returns None if file not found."""
        cached = self.get(file_path)
        if cached is not None:
            return cached

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            self.put(file_path, content)
            return content
        except (OSError, UnicodeDecodeError):
            return None

    def _invalidate(self, path: str) -> bool:
        if path in self._cache:
            self._remove(path)
            self._stats.invalidations += 1
            return True
        return False

    def _remove(self, path: str) -> None:
        entry = self._cache.pop(path, None)
        if entry:
            self._total_bytes -= entry.size
            self._stats.total_bytes_cached = self._total_bytes

    def _evict_lru(self) -> None:
        if self._cache:
            path, _ = self._cache.popitem(last=False)
            entry = self._cache.get(path)
            if entry:
                self._total_bytes -= entry.size
            self._stats.evictions += 1
            self._stats.total_bytes_cached = self._total_bytes
