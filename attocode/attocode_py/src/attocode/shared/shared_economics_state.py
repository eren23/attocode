"""Shared economics state for cross-worker doom loop detection.

Tracks tool fingerprints globally across all swarm workers to detect
doom loops that span multiple agents.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SharedEconomicsConfig:
    """Configuration for shared economics state."""

    global_doom_threshold: int = 10


@dataclass(slots=True)
class GlobalLoopInfo:
    """Information about a global tool call pattern."""

    fingerprint: str
    total_calls: int
    worker_count: int
    workers: list[str]


@dataclass
class SharedEconomicsState:
    """Cross-worker doom loop detection and aggregation.

    Tracks tool fingerprints from all workers to detect global patterns
    like multiple workers hitting the same error or calling the same
    tool with identical arguments.
    """

    config: SharedEconomicsConfig = field(default_factory=SharedEconomicsConfig)

    # fingerprint -> {worker_id -> count}
    _global_calls: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_tool_call(self, worker_id: str, fingerprint: str) -> None:
        """Report a tool call to the shared pool."""
        with self._lock:
            self._global_calls[fingerprint][worker_id] += 1

    def is_global_doom_loop(self, fingerprint: str) -> bool:
        """Check if fingerprint exceeded global threshold."""
        with self._lock:
            if fingerprint not in self._global_calls:
                return False
            total = sum(self._global_calls[fingerprint].values())
            return total >= self.config.global_doom_threshold

    def get_global_loop_info(self, fingerprint: str) -> GlobalLoopInfo | None:
        """Get call count and worker count for a fingerprint."""
        with self._lock:
            if fingerprint not in self._global_calls:
                return None
            workers = self._global_calls[fingerprint]
            return GlobalLoopInfo(
                fingerprint=fingerprint,
                total_calls=sum(workers.values()),
                worker_count=len(workers),
                workers=list(workers.keys()),
            )

    def get_global_loops(self) -> list[GlobalLoopInfo]:
        """List all fingerprints exceeding threshold."""
        with self._lock:
            results = []
            for fp, workers in self._global_calls.items():
                total = sum(workers.values())
                if total >= self.config.global_doom_threshold:
                    results.append(GlobalLoopInfo(
                        fingerprint=fp,
                        total_calls=total,
                        worker_count=len(workers),
                        workers=list(workers.keys()),
                    ))
            return results

    def get_stats(self) -> dict[str, int]:
        """Get aggregated stats."""
        with self._lock:
            unique_fingerprints = len(self._global_calls)
            total_calls = sum(
                sum(w.values()) for w in self._global_calls.values()
            )
            loops = sum(
                1 for w in self._global_calls.values()
                if sum(w.values()) >= self.config.global_doom_threshold
            )
            return {
                "unique_fingerprints": unique_fingerprints,
                "total_calls": total_calls,
                "active_doom_loops": loops,
            }

    def to_json(self) -> dict[str, Any]:
        """Serialize for checkpoint persistence."""
        with self._lock:
            return {
                "global_calls": {
                    fp: dict(workers)
                    for fp, workers in self._global_calls.items()
                },
            }

    def restore_from(self, data: dict[str, Any]) -> None:
        """Restore from checkpoint data."""
        with self._lock:
            self._global_calls = defaultdict(lambda: defaultdict(int))
            for fp, workers in data.get("global_calls", {}).items():
                for w, count in workers.items():
                    self._global_calls[fp][w] = count

    def clear(self) -> None:
        """Clear all state."""
        with self._lock:
            self._global_calls.clear()
