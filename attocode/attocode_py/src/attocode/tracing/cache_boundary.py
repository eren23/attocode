"""KV cache boundary tracking.

Monitors cache hit/miss patterns across LLM requests to help optimise prompt
construction for maximum KV-cache reuse.  The tracker maintains a running
estimate of where the cache boundary sits (in tokens) and the overall hit
rate.

Usage::

    tracker = CacheBoundaryTracker()
    tracker.record_request(
        input_tokens=4000,
        cache_read_tokens=3200,
        cache_write_tokens=800,
    )
    print(tracker.get_cache_hit_rate())   # 0.8
    print(tracker.get_stats())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CacheHitRecord:
    """A single cache observation from one LLM request."""

    timestamp: float
    input_tokens: int
    cache_read: int
    cache_write: int
    hit_rate: float


@dataclass(slots=True)
class CacheStats:
    """Aggregate cache statistics across all recorded requests."""

    total_requests: int = 0
    total_input_tokens: int = 0
    total_cache_read: int = 0
    total_cache_write: int = 0
    hit_rate: float = 0.0
    estimated_boundary: int = 0

    def to_dict(self) -> dict[str, object]:
        """Plain-dict representation for JSON serialisation."""
        return {
            "total_requests": self.total_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_cache_read": self.total_cache_read,
            "total_cache_write": self.total_cache_write,
            "hit_rate": round(self.hit_rate, 4),
            "estimated_boundary": self.estimated_boundary,
        }


# ---------------------------------------------------------------------------
# CacheBoundaryTracker
# ---------------------------------------------------------------------------

class CacheBoundaryTracker:
    """Track KV-cache hit/miss boundaries across LLM requests.

    The tracker records every request and maintains running totals.  The
    *estimated boundary* is the token offset beyond which the prompt is
    typically *not* cached, computed as a weighted moving average of
    ``cache_read_tokens`` across requests.

    Typical lifecycle::

        tracker = CacheBoundaryTracker()

        # After each LLM call:
        tracker.record_request(input_tokens, cache_read, cache_write)

        # Periodically inspect:
        rate = tracker.get_cache_hit_rate()
        stats = tracker.get_stats()

    Parameters:
        window_size: Maximum number of recent records to retain for the
            moving-average boundary estimate.  Older records are discarded.
    """

    def __init__(self, *, window_size: int = 50) -> None:
        self._window_size = max(1, window_size)
        self._records: list[CacheHitRecord] = []

        # Running totals (never trimmed).
        self._total_requests: int = 0
        self._total_input_tokens: int = 0
        self._total_cache_read: int = 0
        self._total_cache_write: int = 0

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_request(
        self,
        input_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> CacheHitRecord:
        """Record a single LLM request's cache metrics.

        Args:
            input_tokens: Total input tokens for the request.
            cache_read_tokens: Tokens served from the KV cache.
            cache_write_tokens: Tokens written into the KV cache.

        Returns:
            The :class:`CacheHitRecord` created for this observation.
        """
        hit_rate = (
            cache_read_tokens / input_tokens if input_tokens > 0 else 0.0
        )

        record = CacheHitRecord(
            timestamp=time.time(),
            input_tokens=input_tokens,
            cache_read=cache_read_tokens,
            cache_write=cache_write_tokens,
            hit_rate=hit_rate,
        )

        self._records.append(record)
        self._total_requests += 1
        self._total_input_tokens += input_tokens
        self._total_cache_read += cache_read_tokens
        self._total_cache_write += cache_write_tokens

        # Trim to window.
        if len(self._records) > self._window_size:
            self._records = self._records[-self._window_size :]

        return record

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_cache_hit_rate(self) -> float:
        """Return the overall cache hit rate (0.0 -- 1.0).

        Computed over *all* requests ever recorded (not windowed).
        """
        if self._total_input_tokens == 0:
            return 0.0
        return self._total_cache_read / self._total_input_tokens

    def get_boundary_position(self) -> int:
        """Estimate the token offset of the cache boundary.

        The boundary is the weighted-average of ``cache_read_tokens`` over
        the most recent requests in the window.  A higher value means more
        of the prompt prefix is cached.

        Returns:
            Estimated boundary in tokens.  ``0`` if no data is available.
        """
        if not self._records:
            return 0

        total_weight = 0.0
        weighted_sum = 0.0
        for idx, rec in enumerate(self._records):
            # More recent records get higher weight.
            weight = idx + 1
            weighted_sum += rec.cache_read * weight
            total_weight += weight

        if total_weight == 0:
            return 0
        return int(weighted_sum / total_weight)

    def get_stats(self) -> CacheStats:
        """Compute aggregate cache statistics.

        Returns:
            A :class:`CacheStats` snapshot.
        """
        return CacheStats(
            total_requests=self._total_requests,
            total_input_tokens=self._total_input_tokens,
            total_cache_read=self._total_cache_read,
            total_cache_write=self._total_cache_write,
            hit_rate=self.get_cache_hit_rate(),
            estimated_boundary=self.get_boundary_position(),
        )

    def get_recent_records(self, n: int = 10) -> list[CacheHitRecord]:
        """Return the *n* most recent cache hit records.

        Args:
            n: Number of records to return.

        Returns:
            List of :class:`CacheHitRecord`, most recent last.
        """
        return self._records[-n:]

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded data and reset counters to zero."""
        self._records.clear()
        self._total_requests = 0
        self._total_input_tokens = 0
        self._total_cache_read = 0
        self._total_cache_write = 0
